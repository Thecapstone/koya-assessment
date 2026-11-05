from __future__ import annotations

import hmac
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from contracts import (
    Booking,
    BookingPage,
    ErrorResponse,
    NewBooking,
    ResetRequest,
    ResetResponse,
    SlotsResponse,
    SlotWithAvailability,
)
from database import connection_scope, transaction
from logic import (
    ApiError,
    booking_from_row,
    json_error,
    lifespan,
    response_for_booking,
    timestamp_text,
)
from settings import (
    ALLOWED_ORIGINS,
    API_KEY,
    RATE_LIMIT_ATTEMPTS,
    RATE_LIMIT_WINDOW_SECONDS,
)

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

app = FastAPI(title="Clinic booking API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "Idempotency-Key"],
    expose_headers=["Retry-After"],
)


async def verify_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if x_api_key is None or not hmac.compare_digest(x_api_key, API_KEY):
        raise ApiError(401, "invalid or missing API key")


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exception: ApiError) -> JSONResponse:
    return json_error(exception.status_code, exception.message, exception.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request, exception: RequestValidationError
) -> JSONResponse:
    if any(error.get("loc", ())[-1:] == ("limit",) for error in exception.errors()):
        return json_error(400, "limit must be between 1 and 50")
    return json_error(400, "invalid request")


@app.post(
    "/reset",
    status_code=200,
    response_model=ResetResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    dependencies=[Depends(verify_api_key)],
)
def reset(request: ResetRequest) -> ResetResponse:
    slot_ids = [slot.id for slot in request.slots]
    if len(slot_ids) != len(set(slot_ids)):
        raise ApiError(400, "slot ids must be unique")
    with transaction() as connection:
        connection.execute("DELETE FROM bookings")
        connection.execute("DELETE FROM slots")
        connection.execute("DELETE FROM idempotency")
        connection.execute("DELETE FROM booking_attempts")
        connection.executemany(
            "INSERT INTO slots(id, provider, start, end) VALUES (?, ?, ?, ?)",
            [
                (
                    slot.id,
                    slot.provider,
                    timestamp_text(slot.start),
                    timestamp_text(slot.end),
                )
                for slot in request.slots
            ],
        )
    return ResetResponse(ok=True)


@app.get(
    "/slots",
    response_model=SlotsResponse,
    responses={401: {"model": ErrorResponse}},
    dependencies=[Depends(verify_api_key)],
)
def list_slots(provider: str | None = None) -> SlotsResponse:
    with connection_scope() as connection:
        if provider is None:
            rows = connection.execute(
                """SELECT s.*, NOT EXISTS (
                       SELECT 1 FROM bookings b
                       WHERE b.slot_id = s.id AND b.status = 'confirmed'
                   ) AS available
                   FROM slots s ORDER BY s.start ASC, s.id ASC"""
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT s.*, NOT EXISTS (
                       SELECT 1 FROM bookings b
                       WHERE b.slot_id = s.id AND b.status = 'confirmed'
                   ) AS available
                   FROM slots s WHERE s.provider = ? ORDER BY s.start ASC, s.id ASC""",
                (provider,),
            ).fetchall()
    return SlotsResponse(
        slots=[SlotWithAvailability.model_validate(dict(row)) for row in rows]
    )


@app.post(
    "/bookings",
    status_code=201,
    response_model=Booking,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {
            "model": ErrorResponse,
            "headers": {
                "Retry-After": {
                    "schema": {"type": "integer"},
                    "description": "Seconds to wait",
                }
            },
        },
    },
    dependencies=[Depends(verify_api_key)],
)
def create_booking(
    request: NewBooking,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Booking | JSONResponse:
    slot_id = request.slot_id.strip()
    name = request.name.strip()
    email = request.email.strip().lower()
    request_body = json.dumps(
        {"slot_id": slot_id, "name": name, "email": email},
        sort_keys=True,
        separators=(",", ":"),
    )
    attempt_email = email or request.email.strip().lower()
    now = time.time()

    with transaction() as connection:
        if idempotency_key:
            previous = connection.execute(
                "SELECT request_body, status_code, response_body FROM idempotency WHERE key = ?",
                (idempotency_key,),
            ).fetchone()
            if previous is not None and previous["request_body"] == request_body:
                previous_body = json.loads(previous["response_body"])
                if previous["status_code"] == 201:
                    return Booking.model_validate(previous_body)
                return response_for_booking(previous["status_code"], previous_body)

        if attempt_email:
            cutoff = now - RATE_LIMIT_WINDOW_SECONDS
            connection.execute(
                "DELETE FROM booking_attempts WHERE email = ? AND attempted_at <= ?",
                (attempt_email, cutoff),
            )
            recent = connection.execute(
                "SELECT attempted_at FROM booking_attempts WHERE email = ? ORDER BY attempted_at",
                (attempt_email,),
            ).fetchall()
            if len(recent) >= RATE_LIMIT_ATTEMPTS:
                retry_after = max(
                    1,
                    math.ceil(
                        recent[0]["attempted_at"] + RATE_LIMIT_WINDOW_SECONDS - now
                    ),
                )
                raise ApiError(
                    429, "too many booking attempts", {"Retry-After": str(retry_after)}
                )
            connection.execute(
                "INSERT INTO booking_attempts(email, attempted_at) VALUES (?, ?)",
                (attempt_email, now),
            )

        if idempotency_key:
            previous = connection.execute(
                "SELECT request_body FROM idempotency WHERE key = ?", (idempotency_key,)
            ).fetchone()
            if previous is not None:
                return response_for_booking(
                    422, {"error": "idempotency key reused with a different body"}
                )

        if not slot_id or not name or not email or not EMAIL_PATTERN.fullmatch(email):
            status_code, body = (
                400,
                {"error": "slot_id, name and a valid email are required"},
            )
        else:
            slot = connection.execute(
                "SELECT start FROM slots WHERE id = ?", (slot_id,)
            ).fetchone()
            if slot is None:
                status_code, body = 404, {"error": "slot not found"}
            elif datetime.fromisoformat(
                slot["start"].replace("Z", "+00:00")
            ) <= datetime.now(timezone.utc):
                status_code, body = 400, {"error": "slot has already started"}
            elif connection.execute(
                "SELECT 1 FROM bookings WHERE slot_id = ? AND status = 'confirmed'",
                (slot_id,),
            ).fetchone():
                status_code, body = 409, {"error": "slot is already booked"}
            else:
                booking = Booking(
                    id=str(uuid.uuid4()),
                    slot_id=slot_id,
                    name=name,
                    email=email,
                    status="confirmed",
                    created_at=datetime.fromtimestamp(
                        math.floor(now * 1000) / 1000, timezone.utc
                    ),
                )
                body = booking.model_dump(mode="json")
                status_code = 201
                connection.execute(
                    "INSERT INTO bookings(id, slot_id, name, email, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        booking.id,
                        booking.slot_id,
                        booking.name,
                        booking.email,
                        booking.status,
                        timestamp_text(booking.created_at),
                    ),
                )

        if idempotency_key:
            connection.execute(
                "INSERT INTO idempotency(key, request_body, status_code, response_body) VALUES (?, ?, ?, ?)",
                (
                    idempotency_key,
                    request_body,
                    status_code,
                    json.dumps(body, separators=(",", ":")),
                ),
            )

    if status_code == 201:
        return Booking.model_validate(body)
    return response_for_booking(status_code, body)


@app.get(
    "/bookings",
    response_model=BookingPage,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    dependencies=[Depends(verify_api_key)],
)
def list_bookings(
    email: str,
    limit: int = Query(default=10),
    cursor: str | None = None,
) -> BookingPage:
    if limit < 1 or limit > 50:
        raise ApiError(400, "limit must be between 1 and 50")
    normalized_email = email.strip().lower()
    with connection_scope() as connection:
        if cursor:
            cursor_row = connection.execute(
                "SELECT created_at, id FROM bookings WHERE id = ? AND email = ?",
                (cursor, normalized_email),
            ).fetchone()
            if cursor_row is None:
                raise ApiError(400, "invalid cursor")
            rows = connection.execute(
                """SELECT * FROM bookings WHERE email = ? AND (created_at, id) > (?, ?)
                   ORDER BY created_at ASC, id ASC LIMIT ?""",
                (
                    normalized_email,
                    cursor_row["created_at"],
                    cursor_row["id"],
                    limit + 1,
                ),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM bookings WHERE email = ? ORDER BY created_at ASC, id ASC LIMIT ?",
                (normalized_email, limit + 1),
            ).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = page_rows[-1]["id"] if has_more and page_rows else None
    return BookingPage(
        bookings=[booking_from_row(row) for row in page_rows], next_cursor=next_cursor
    )


@app.get(
    "/bookings/{booking_id}",
    response_model=Booking,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    dependencies=[Depends(verify_api_key)],
)
def get_booking(booking_id: str) -> Booking:
    with connection_scope() as connection:
        row = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
    if row is None:
        raise ApiError(404, "booking not found")
    return booking_from_row(row)


@app.delete(
    "/bookings/{booking_id}",
    response_model=Booking,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    dependencies=[Depends(verify_api_key)],
)
def cancel_booking(booking_id: str) -> Booking:
    with transaction() as connection:
        row = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "booking not found")
        if row["status"] == "cancelled":
            raise ApiError(409, "booking is already cancelled")
        connection.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,)
        )
        row = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
    return booking_from_row(row)

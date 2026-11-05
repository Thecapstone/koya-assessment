from __future__ import annotations


from datetime import datetime, timezone


from fastapi.responses import JSONResponse




def timestamp_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def json_error(
    status_code: int, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": message}, headers=headers
    )


class ApiError(Exception):
    def __init__(
        self, status_code: int, message: str, headers: dict[str, str] | None = None
    ):
        self.status_code = status_code
        self.message = message
        self.headers = headers


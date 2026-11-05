from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Slot(ContractModel):
    id: str
    provider: str
    start: datetime
    end: datetime


class ResetRequest(ContractModel):
    slots: list[Slot]


class ResetResponse(ContractModel):
    ok: bool


class SlotWithAvailability(Slot):
    available: bool


class SlotsResponse(ContractModel):
    slots: list[SlotWithAvailability]


class NewBooking(ContractModel):
    slot_id: str
    name: str
    email: str


class Booking(ContractModel):
    id: str
    slot_id: str
    name: str
    email: str
    status: Literal["confirmed", "cancelled"]
    created_at: datetime


class ErrorResponse(ContractModel):
    error: str


class BookingPage(ContractModel):
    bookings: list[Booking]
    next_cursor: str | None

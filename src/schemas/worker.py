from datetime import datetime

from pydantic import BaseModel


class PingRequest(BaseModel):
    node_id: str
    node_type: str


class Command(BaseModel):
    command: str
    slot: int | None = None
    count: int | None = None


class Status(BaseModel):
    worker_id: str
    worker_type: str
    last_seen: datetime
    ping_count: int
    fuel: int | None = None
    inventory: dict | None = None
    block: dict | str | None = None
    peripherals: dict | None = None  # <-- ADD THIS LINE

from datetime import datetime

from pydantic import BaseModel


class PingRequest(BaseModel):
    node_id: str
    node_type: str


class Status(BaseModel):
    node_id: str
    node_type: str
    last_seen: datetime
    ping_count: int

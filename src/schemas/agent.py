from typing import Optional

from pydantic import BaseModel


class StartAgentRequest(BaseModel):
    agent: str
    args: dict = {}


class AgentResponse(BaseModel):
    ok: bool
    worker_id: str
    agent_type: Optional[str] = None
    state: Optional[str] = None
    detail: Optional[str] = None
    extra: dict = {}

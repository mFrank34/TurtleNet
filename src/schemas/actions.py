from pydantic import BaseModel


class ActionRequest(BaseModel):
    action: str
    args: dict = {}

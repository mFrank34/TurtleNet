from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.actions import ACTIONS
from api.v1.endpoints.worker_ws import connected_workers, send_command

router = APIRouter()


class ActionRequest(BaseModel):
    action: str
    args: dict = {}


@router.post("/{worker_id}/action")
async def run_action(worker_id: str, payload: ActionRequest):
    if worker_id not in connected_workers:
        raise HTTPException(status_code=404, detail="Worker not connected")

    action_fn = ACTIONS.get(payload.action)
    if not action_fn:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{payload.action}'. Available: {list(ACTIONS.keys())}"
        )

    return await action_fn(worker_id, send_command, payload.args)
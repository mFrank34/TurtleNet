from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

router = APIRouter()

connected_workers: dict[str, WebSocket] = {}


class Command(BaseModel):
    command: str


@router.websocket("/ws/{worker_id}")
async def worker_ws(websocket: WebSocket, worker_id: str):
    await websocket.accept()
    connected_workers[worker_id] = websocket
    print(f"[TurtleNet] Worker {worker_id} connected")
    try:
        while True:
            data = await websocket.receive_json()
            print(f"[TurtleNet] {worker_id} → {data}")
    except WebSocketDisconnect:
        print(f"[TurtleNet] Worker {worker_id} disconnected")
    finally:
        connected_workers.pop(worker_id, None)


@router.post("/{worker_id}/command")
async def command_worker(worker_id: str, payload: Command):
    ws = connected_workers.get(worker_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Worker not connected")
    await ws.send_json({"command": payload.command})
    return {"sent": True}
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from schemas.worker import Command
from services import worker_store

router = APIRouter()
connected_workers: dict[str, WebSocket] = {}


@router.websocket("/ws/{worker_id}")
async def worker_ws(websocket: WebSocket, worker_id: str):
    await websocket.accept()
    connected_workers[worker_id] = websocket
    worker_store.record_ping(worker_id, "turtle")
    print(f"[TurtleNet] Worker {worker_id} connected")

    async def keepalive():
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                break

    asyncio.create_task(keepalive())

    try:
        while True:
            data = await websocket.receive_json()
            print(f"[TurtleNet] {worker_id} → {data}")
            worker_store.record_ping(
                worker_id,
                "turtle",
                fuel=data.get("fuel"),
                inventory=data.get("inventory"),
                block=data.get("block"),
            )
    except WebSocketDisconnect:
        print(f"[TurtleNet] Worker {worker_id} disconnected")
    finally:
        connected_workers.pop(worker_id, None)


@router.post("/{worker_id}/command")
async def command_worker(worker_id: str, payload: Command):
    ws = connected_workers.get(worker_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Worker not connected")
    await ws.send_json({
        "command": payload.command,
        "slot": payload.slot,
        "count": payload.count,
    })
    return {"sent": True}


@router.get("/{worker_id}/inventory")
def get_inventory(worker_id: str):
    worker = worker_store.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker.inventory
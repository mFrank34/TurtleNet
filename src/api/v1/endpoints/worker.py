# Location: src/api/v1/endpoints/worker_ws.py
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from core.commands import Inventory
from schemas.worker import Command
from services import worker_store

router = APIRouter()
connected_workers: dict[str, WebSocket] = {}

# Tracks pending commands waiting for a response: { worker_id: (asyncio.Event, response_data_dict) }
pending_responses: dict[str, tuple[asyncio.Event, dict]] = {}


@router.websocket("/ws/{worker_id}")
async def worker_ws(websocket: WebSocket, worker_id: str):  # Keep this explicitly worker_ws
    await websocket.accept()
    connected_workers[worker_id] = websocket
    print(f"[TurtleNet] Worker {worker_id} connected socket successfully")

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

            try:
                worker_store.record_ping(
                    worker_id=worker_id,
                    worker_type="turtle",
                    fuel=data.get("fuel"),
                    inventory=data.get("inventory"),
                    block=data.get("block"),
                    peripherals=data.get("peripherals"),
                    location=data.get("location"),
                )
            except Exception as db_err:
                print(f"[Database Error] Failed to log state for {worker_id}: {db_err}")

            if worker_id in pending_responses:
                event, _ = pending_responses[worker_id]
                pending_responses[worker_id] = (event, data)
                event.set()

    except WebSocketDisconnect:
        print(f"[TurtleNet] Worker {worker_id} disconnected")
    finally:
        connected_workers.pop(worker_id, None)
        pending_responses.pop(worker_id, None)


async def send_command(worker_id: str, cmd: Command) -> dict | None:
    """
    Shared send helper — used by both the command endpoint and actions.
    Returns the turtle's response dict, or None on timeout/not connected.
    """
    ws = connected_workers.get(worker_id)
    if not ws:
        return None

    event = asyncio.Event()
    pending_responses[worker_id] = (event, {})

    await ws.send_json({
        "command": cmd.command,
        "slot": cmd.slot,
        "count": cmd.count,
    })

    try:
        await asyncio.wait_for(event.wait(), timeout=5.0)
        _, response_data = pending_responses[worker_id]
        return response_data
    except asyncio.TimeoutError:
        return None
    finally:
        pending_responses.pop(worker_id, None)


@router.post("/{worker_id}/command")
async def command_worker(worker_id: str, payload: Command):
    ws = connected_workers.get(worker_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Worker not connected")

    response_data = await send_command(worker_id, payload)
    if response_data is None:
        raise HTTPException(status_code=504, detail="Turtle took too long to respond")

    return {
        "sent": True,
        "status": response_data.get("status"),
        "command": response_data.get("command"),
        "fuel": response_data.get("fuel"),
        "block": response_data.get("block"),
        "peripherals": response_data.get("peripherals"),
        "location": response_data.get("location"),
    }


@router.get("/{worker_id}/inventory")
async def get_inventory(worker_id: str):
    ws = connected_workers.get(worker_id)

    if not ws:
        worker = worker_store.get_worker(worker_id)
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        return {"source": "cache_offline", "inventory": worker.inventory}

    response_data = await send_command(worker_id, Command(command=Inventory.SCAN))

    if response_data is None:
        worker = worker_store.get_worker(worker_id)
        return {"source": "cache_timeout", "inventory": worker.inventory if worker else {}}

    return {"source": "live_sync", "inventory": response_data.get("inventory")}

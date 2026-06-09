import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from schemas.worker import Command
from services import worker_store

router = APIRouter()
connected_workers: dict[str, WebSocket] = {}

# Tracks pending commands waiting for a response: { worker_id: (asyncio.Event, response_data_dict) }
pending_responses: dict[str, tuple[asyncio.Event, dict]] = {}


@router.websocket("/ws/{worker_id}")
async def worker_ws(websocket: WebSocket, worker_id: str):
    await websocket.accept()
    connected_workers[worker_id] = websocket
    print(f"[TurtleNet] Worker {worker_id} connected socket successfully")

    # Background keepalive task to ping the turtle every 30 seconds
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

            # Inside your websocket receive loop:
            print(f"[TurtleNet] {worker_id} → {data}")

            try:
                # Directly call the module function cleanly!
                worker_store.record_ping(
                    worker_id=worker_id,
                    worker_type="turtle",
                    fuel=data.get("fuel"),
                    inventory=data.get("inventory"),
                    block=data.get("block"),
                    peripherals=data.get("peripherals"),
                )
            except Exception as db_err:
                print(f"[Database Error] Failed to log state for {worker_id}: {db_err}")

            # Resolve any waiting HTTP POST command threads
            if worker_id in pending_responses:
                event, _ = pending_responses[worker_id]
                pending_responses[worker_id] = (event, data)
                event.set()

    except WebSocketDisconnect:
        print(f"[TurtleNet] Worker {worker_id} disconnected")
    finally:
        connected_workers.pop(worker_id, None)
        pending_responses.pop(worker_id, None)


@router.post("/{worker_id}/command")
async def command_worker(worker_id: str, payload: Command):
    ws = connected_workers.get(worker_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Worker not connected")

    event = asyncio.Event()
    pending_responses[worker_id] = (event, {})

    await ws.send_json({
        "command": payload.command,
        "slot": payload.slot,
        "count": payload.count,
    })

    try:
        await asyncio.wait_for(event.wait(), timeout=5.0)
        _, response_data = pending_responses[worker_id]

        return {
            "sent": True,
            "status": response_data.get("status"),
            "command": response_data.get("command"),
            "fuel": response_data.get("fuel"),
            "block": response_data.get("block"),
            "peripherals": response_data.get("peripherals")
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Turtle took too long to respond")
    finally:
        pending_responses.pop(worker_id, None)


@router.get("/{worker_id}/inventory")
async def get_inventory(worker_id: str):
    ws = connected_workers.get(worker_id)

    if not ws:
        # Handling instance check for get_worker as well
        store_instance = worker_store() if isinstance(worker_store, type) else worker_store
        worker = store_instance.get_worker(worker_id)
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        return {"source": "cache_offline", "inventory": worker.inventory}

    event = asyncio.Event()
    pending_responses[worker_id] = (event, {})

    await ws.send_json({
        "command": "scan_inventory",
        "slot": None,
        "count": None
    })

    try:
        await asyncio.wait_for(event.wait(), timeout=5.0)
        _, response_data = pending_responses[worker_id]

        return {
            "source": "live_sync",
            "inventory": response_data.get("inventory")
        }
    except asyncio.TimeoutError:
        store_instance = worker_store() if isinstance(worker_store, type) else worker_store
        worker = store_instance.get_worker(worker_id)
        return {"source": "cache_timeout", "inventory": worker.inventory if worker else {}}
    finally:
        pending_responses.pop(worker_id, None)

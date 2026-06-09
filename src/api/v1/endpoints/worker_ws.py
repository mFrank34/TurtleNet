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
    worker_store.record_ping(worker_id, "turtle")
    print(f"[TurtleNet] Worker {worker_id} connected")

    # Background keepalive task to ping the turtle every 30 seconds
    async def keepalive():
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                break

    asyncio.create_task(keepalive())

    # --- THIS IS THE EXACT LOOP YOU ARE LOOKING FOR ---
    try:
        while True:
            data = await websocket.receive_json()
            print(f"[TurtleNet] {worker_id} → {data}")

            # Record state including the new peripherals key
            worker_store.record_ping(
                worker_id,
                "turtle",
                fuel=data.get("fuel"),
                inventory=data.get("inventory"),
                block=data.get("block"),
                peripherals=data.get("peripherals"),  # <-- Integrated here
            )

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
            "peripherals": response_data.get("peripherals")  # Returns it dynamically here!
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Turtle took too long to respond")
    finally:
        pending_responses.pop(worker_id, None)


@router.get("/{worker_id}/inventory")
async def get_inventory(worker_id: str):  # Made async to handle the event wait
    ws = connected_workers.get(worker_id)

    # Fallback: If the turtle is offline, give them the last known saved inventory
    if not ws:
        worker = worker_store.get_worker(worker_id)
        if not worker:
            raise HTTPException(status_code=404, detail="Worker not found")
        return {"source": "cache_offline", "inventory": worker.inventory}

    # If the turtle IS online, force a real-time live scan!
    event = asyncio.Event()
    pending_responses[worker_id] = (event, {})

    # Send the scan command down the websocket pipeline
    await ws.send_json({
        "command": "scan_inventory",
        "slot": None,
        "count": None
    })

    try:
        # Wait up to 5 seconds for the turtle to run get_inventory() and send it back
        await asyncio.wait_for(event.wait(), timeout=5.0)
        _, response_data = pending_responses[worker_id]

        return {
            "source": "live_sync",
            "inventory": response_data.get("inventory")
        }
    except asyncio.TimeoutError:
        # If it times out, gracefully fall back to the last known database file state
        worker = worker_store.get_worker(worker_id)
        return {"source": "cache_timeout", "inventory": worker.inventory if worker else {}}
    finally:
        pending_responses.pop(worker_id, None)

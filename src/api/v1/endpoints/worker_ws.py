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

            # Save the ping state as usual
            worker_store.record_ping(
                worker_id,
                "turtle",
                fuel=data.get("fuel"),
                inventory=data.get("inventory"),
                block=data.get("block"),
            )

            # NEW: If an HTTP request is waiting for this turtle's answer, give it the data
            if worker_id in pending_responses and "command" in data:
                event, _ = pending_responses[worker_id]
                pending_responses[worker_id] = (event, data)  # Store the actual reply packet
                event.set()  # Wake up the HTTP endpoint thread

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

    # Create an event tracker for this specific command round-trip
    event = asyncio.Event()
    pending_responses[worker_id] = (event, {})

    # Forward command to turtle
    await ws.send_json({
        "command": payload.command,
        "slot": payload.slot,
        "count": payload.count,
    })

    try:
        # Wait up to 5 seconds for the turtle to execute it and respond over the WS loop
        await asyncio.wait_for(event.wait(), timeout=5.0)
        _, response_data = pending_responses[worker_id]

        # Return the actual feedback from the turtle back to your curl client
        return {
            "sent": True,
            "status": response_data.get("status"),
            "command": response_data.get("command"),
            "block": response_data.get("block"),
            "fuel": response_data.get("fuel")
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Turtle took too long to respond")
    finally:
        # Always clean up our tracker dictionary
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

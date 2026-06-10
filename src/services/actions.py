"""
actions.py
----------
High-level action macros that orchestrate sequences of commands.
Each action takes a worker_id, send_command coroutine, and optional args dict.

Add new actions as async functions and register them in ACTIONS at the bottom.
"""

from __future__ import annotations

from typing import Callable, Awaitable

from core.commands import Move, Inspect, Equip, Inventory, GPS
from schemas.worker import Command

# Type alias for the send_command function passed in from the endpoint
SendCommand = Callable[[str, Command], Awaitable[dict | None]]

MODEM_NAMES = (
    "computercraft:wireless_modem",
    "computercraft:wired_modem",
    "modem",
)


def _find_slot(inventory: dict, *keywords: str) -> int | None:
    """Find the first inventory slot whose item name contains any of the keywords."""
    for slot, item in inventory.items():
        name = item.get("name", "").lower()
        if any(k in name for k in keywords):
            return int(slot)
    return None


async def _scan(worker_id: str, send: SendCommand) -> dict | None:
    """Scan inventory and return it, or None on failure."""
    result = await send(worker_id, Command(command=Inventory.SCAN))
    if not result or result.get("status") != "ok":
        return None
    return result.get("inventory") or {}


async def _find_and_select(worker_id: str, send: SendCommand, *keywords: str) -> tuple[int, str] | dict:
    """Scan inventory, find item by keywords, select it. Returns (slot, name) or error dict."""
    inventory = await _scan(worker_id, send)
    if inventory is None:
        return {"ok": False, "error": "inventory scan failed"}

    slot = _find_slot(inventory, *keywords)
    if slot is None:
        return {"ok": False, "error": f"{keywords[0]} not found in inventory"}

    result = await send(worker_id, Command(command=Inventory.SELECT, slot=slot))
    if not result or result.get("status") != "ok":
        return {"ok": False, "error": f"failed to select slot {slot}"}

    name = inventory[str(slot)].get("name", keywords[0])
    return slot, name


async def get_gps_location(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Equip modem, get GPS, swap back."""
    inventory = await _scan(worker_id, send)
    if inventory is None:
        return {"ok": False, "error": "inventory scan failed"}

    modem_slot = _find_slot(inventory, *MODEM_NAMES)
    if modem_slot is None:
        return {"ok": False, "error": "no modem found in inventory"}

    if not (await send(worker_id, Command(command=Inventory.SELECT, slot=modem_slot))):
        return {"ok": False, "error": f"failed to select slot {modem_slot}"}

    if not (await send(worker_id, Command(command=Equip.LEFT))):
        return {"ok": False, "error": "failed to equip modem"}

    locate = await send(worker_id, Command(command=GPS.LOCATE))
    location = locate.get("location") if locate else None

    # always swap back regardless of GPS result
    await send(worker_id, Command(command=Equip.LEFT))

    if not location:
        return {"ok": False, "error": "modem equipped but no GPS signal"}

    return {"ok": True, "location": location}


async def auto_refuel(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Find coal/charcoal in inventory and refuel."""
    inventory = await _scan(worker_id, send)
    if inventory is None:
        return {"ok": False, "error": "inventory scan failed"}

    fuel_slot = _find_slot(inventory, "coal", "charcoal")
    if fuel_slot is None:
        return {"ok": False, "error": "no fuel found in inventory"}

    await send(worker_id, Command(command=Inventory.SELECT, slot=fuel_slot))
    result = await send(worker_id, Command(command=Inventory.REFUEL))

    if not result or result.get("status") != "ok":
        return {"ok": False, "error": "refuel failed"}

    return {"ok": True, "fuel": result.get("fuel")}


async def equip_item(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Find an item by name and equip it on the left."""
    item_name = args.get("item")
    if not item_name:
        return {"ok": False, "error": "no item specified — pass args.item"}

    result = await _find_and_select(worker_id, send, item_name.lower())
    if isinstance(result, dict):
        return result

    slot, name = result
    equip = await send(worker_id, Command(command=Equip.LEFT))
    if not equip or equip.get("status") != "ok":
        return {"ok": False, "error": "equip failed"}

    return {"ok": True, "equipped": name}


async def select_block(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Find a block by name in inventory and select its slot."""
    block_name = args.get("block")
    if not block_name:
        return {"ok": False, "error": "no block specified — pass args.block"}

    result = await _find_and_select(worker_id, send, block_name.lower())
    if isinstance(result, dict):
        return result

    slot, name = result
    return {"ok": True, "block": name, "slot": slot}


async def verify_move_forward(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """
    Moves the worker forward and verifies if its GPS position actually changed.
    Returns a dict with verification status and positions.
    """
    # 1. Get initial position
    initial_gps = await get_gps_location(worker_id, send, args)
    if not initial_gps.get("ok"):
        return {"ok": False, "error": f"Initial GPS failed: {initial_gps.get('error')}"}
    pos1 = initial_gps["location"]

    # 2. Attempt to move forward
    move = await send(worker_id, Command(command=Move.FORWARD))
    if not move or move.get("status") != "ok":
        return {"ok": False, "error": "move forward command rejected or blocked"}

    # 3. Get post-move position
    post_gps = await get_gps_location(worker_id, send, args)
    if not post_gps.get("ok"):
        return {"ok": False, "error": f"Post-move GPS failed: {post_gps.get('error')}"}
    pos2 = post_gps["location"]

    # 4. Calculate coordinate deltas
    dx = pos2["x"] - pos1["x"]
    dy = pos2["y"] - pos1["y"]
    dz = pos2["z"] - pos1["z"]

    moved = (abs(dx) + abs(dy) + abs(dz)) == 1

    if not moved:
        return {"ok": False, "error": "Move command executed, but GPS position did not change."}

    return {
        "ok": True,
        "current_position": pos2,
        "delta": {"x": dx, "y": dy, "z": dz}
    }


async def move_and_scan(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Move forward (verified via GPS) then inspect up, middle and down."""
    # Call the verification function to handle the movement step
    move_result = await verify_move_forward(worker_id, send, args)
    if not move_result.get("ok"):
        return move_result  # Return early if movement or GPS verification failed

    # Perform environmental scans since we confirmed we moved successfully
    up = await send(worker_id, Command(command=Inspect.UP))
    forward = await send(worker_id, Command(command=Inspect.FORWARD))
    down = await send(worker_id, Command(command=Inspect.DOWN))

    return {
        "ok": True,
        "location": move_result["current_position"],
        "delta": move_result["delta"],
        "blocks": {
            "up": up.get("block") if up else None,
            "forward": forward.get("block") if forward else None,
            "down": down.get("block") if down else None,
        }
    }


async def turn_left(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Turn the worker left."""
    result = await send(worker_id, Command(command=Move.TURN_LEFT))
    return {"ok": True} if result and result.get("status") == "ok" else {"ok": False, "error": "turn left failed"}


async def turn_right(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Turn the worker right."""
    result = await send(worker_id, Command(command=Move.TURN_RIGHT))
    return {"ok": True} if result and result.get("status") == "ok" else {"ok": False, "error": "turn right failed"}


# Registry — add new actions here
ACTIONS: dict[str, Callable] = {
    "get_gps_location": get_gps_location,
    "auto_refuel": auto_refuel,
    "equip_item": equip_item,
    "select_block": select_block,
    "move_and_scan": move_and_scan,
    "verify_move_forward": verify_move_forward,
    "turn_left": turn_left,
    "turn_right": turn_right,
}

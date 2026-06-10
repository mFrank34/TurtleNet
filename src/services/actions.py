"""
actions.py
----------
High-level action macros that orchestrate sequences of commands.
Each action takes a worker_id, send_command coroutine, and optional args dict.

Add new actions as async functions and register them in ACTIONS at the bottom.
"""

from __future__ import annotations
from typing import Callable, Awaitable

from schemas.worker import Command

# Type alias for the send_command function passed in from the endpoint
SendCommand = Callable[[str, Command], Awaitable[dict | None]]

MODEM_NAMES = (
    "computercraft:wireless_modem",
    "computercraft:wired_modem",
    "advancedperipherals:end_automata",
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
    result = await send(worker_id, Command(command="scan_inventory"))
    if not result or result.get("status") != "ok":
        return None
    return result.get("inventory") or {}


async def get_gps_location(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Equip modem, get GPS, swap back."""
    inventory = await _scan(worker_id, send)
    if inventory is None:
        return {"ok": False, "error": "inventory scan failed"}

    modem_slot = _find_slot(inventory, *MODEM_NAMES)
    if modem_slot is None:
        return {"ok": False, "error": "no modem found in inventory"}

    if not (await send(worker_id, Command(command="select_slot", slot=modem_slot))):
        return {"ok": False, "error": f"failed to select slot {modem_slot}"}

    if not (await send(worker_id, Command(command="equip_left"))):
        return {"ok": False, "error": "failed to equip modem"}

    locate = await send(worker_id, Command(command="get_location"))
    location = locate.get("location") if locate else None

    # always swap back regardless of GPS result
    await send(worker_id, Command(command="equip_left"))

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

    await send(worker_id, Command(command="select_slot", slot=fuel_slot))
    result = await send(worker_id, Command(command="refuel"))

    if not result or result.get("status") != "ok":
        return {"ok": False, "error": "refuel failed"}

    return {"ok": True, "fuel": result.get("fuel")}


async def equip_item(worker_id: str, send: SendCommand, args: dict = {}) -> dict:
    """Find an item by name and equip it on the left."""
    item_name = args.get("item")
    if not item_name:
        return {"ok": False, "error": "no item specified — pass args.item"}

    inventory = await _scan(worker_id, send)
    if inventory is None:
        return {"ok": False, "error": "inventory scan failed"}

    item_slot = _find_slot(inventory, item_name.lower())
    if item_slot is None:
        return {"ok": False, "error": f"{item_name} not found in inventory"}

    await send(worker_id, Command(command="select_slot", slot=item_slot))
    result = await send(worker_id, Command(command="equip_left"))

    if not result or result.get("status") != "ok":
        return {"ok": False, "error": "equip failed"}

    return {"ok": True, "equipped": item_name}


# Registry — add new actions here
ACTIONS: dict[str, Callable] = {
    "get_gps_location": get_gps_location,
    "auto_refuel": auto_refuel,
    "equip_item": equip_item,
}
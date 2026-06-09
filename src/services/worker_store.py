import json
from datetime import datetime, timezone
from pathlib import Path

from schemas.worker import Status

STORE_PATH = Path("data/workers.json")


def _load() -> dict:
    if not STORE_PATH.exists():
        return {}
    with STORE_PATH.open() as f:
        return json.load(f)


def _save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STORE_PATH.open("w") as f:
        json.dump(data, f, indent=2, default=str)


# FIXED: Removed 'self' and swapped internal calls to match _load() and _save()
def record_ping(worker_id: str, worker_type: str, fuel: int = None, inventory: dict = None, block: dict = None,
                peripherals: dict = None):
    workers = _load()  # FIXED: matches function name above
    worker = workers.get(worker_id)

    if worker:
        worker["last_seen"] = datetime.now(timezone.utc).isoformat()
        worker["ping_count"] += 1
        if fuel is not None: worker["fuel"] = fuel
        if inventory is not None: worker["inventory"] = inventory
        if block is not None: worker["block"] = block
        if peripherals is not None: worker["peripherals"] = peripherals
    else:
        worker = {
            "worker_id": worker_id,
            "worker_type": worker_type,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "ping_count": 1,
            "fuel": fuel,
            "inventory": inventory or {},
            "block": block,
            "peripherals": peripherals or {},
        }
        workers[worker_id] = worker

    _save(workers)  # FIXED: matches function name above
    return Status(**worker)


def get_all_workers() -> list[Status]:
    data = _load()
    return [Status(**w) for w in data.values()]


def get_worker(worker_id: str) -> Status | None:
    data = _load()
    worker = data.get(worker_id)
    return Status(**worker) if worker else None


def delete_worker(worker_id: str) -> bool:
    data = _load()
    if worker_id not in data:
        return False
    del data[worker_id]
    _save(data)
    return True
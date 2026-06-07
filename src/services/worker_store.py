import json
from datetime import datetime, timezone
from pathlib import Path

from src.schemas.worker import Status

STORE_PATH = Path("data/nodes.json")


def _load() -> dict:
    if not STORE_PATH.exists():
        return {}
    with STORE_PATH.open() as f:
        return json.load(f)


def _save(data: dict) -> None:
    with STORE_PATH.open("w") as f:
        json.dump(data, f, indent=2, default=str)


def record_ping(node_id: str, node_type: str) -> Status:
    data = _load()
    node = data.get(node_id)

    if node:
        node["last_seen"] = datetime.now(timezone.utc).isoformat()
        node["ping_count"] += 1
    else:
        node = {
            "node_id": node_id,
            "node_type": node_type,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "ping_count": 1,
        }

    data[node_id] = node
    _save(data)
    return Status(**node)


def get_all_nodes() -> list[Status]:
    data = _load()
    return [Status(**n) for n in data.values()]


def get_node(node_id: str) -> Status | None:
    data = _load()
    node = data.get(node_id)
    return Status(**node) if node else None


def delete_node(node_id: str) -> bool:
    data = _load()
    if node_id not in data:
        return False
    del data[node_id]
    _save(data)
    return True

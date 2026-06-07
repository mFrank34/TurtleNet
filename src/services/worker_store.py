import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.node import NodeStatus

STORE_PATH = Path("nodes.json")


def _load() -> dict:
    if not STORE_PATH.exists():
        return {}
    with STORE_PATH.open() as f:
        return json.load(f)


def _save(data: dict) -> None:
    with STORE_PATH.open("w") as f:
        json.dump(data, f, indent=2, default=str)


def record_ping(node_id: str, node_type: str) -> NodeStatus:
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
    return NodeStatus(**node)


def get_all_nodes() -> list[NodeStatus]:
    data = _load()
    return [NodeStatus(**n) for n in data.values()]


def get_node(node_id: str) -> NodeStatus | None:
    data = _load()
    node = data.get(node_id)
    return NodeStatus(**node) if node else None


def delete_node(node_id: str) -> bool:
    data = _load()
    if node_id not in data:
        return False
    del data[node_id]
    _save(data)
    return True

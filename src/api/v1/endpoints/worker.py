from fastapi import APIRouter, HTTPException

from app.schemas.node import NodeStatus, PingRequest
from app.services import node_store

router = APIRouter()


@router.post("/ping", response_model=NodeStatus)
def ping(payload: PingRequest):
    """Worker nodes call this to register their heartbeat."""
    return node_store.record_ping(payload.node_id, payload.node_type)


@router.get("/", response_model=list[NodeStatus])
def list_nodes():
    """List all known worker nodes."""
    return node_store.get_all_nodes()


@router.get("/{node_id}", response_model=NodeStatus)
def get_node(node_id: str):
    """Get status of a specific node."""
    node = node_store.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.delete("/{node_id}", status_code=204)
def remove_node(node_id: str):
    """Remove a node from the store."""
    if not node_store.delete_node(node_id):
        raise HTTPException(status_code=404, detail="Node not found")
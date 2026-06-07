from fastapi import APIRouter, HTTPException

from schemas.worker import Status, PingRequest
from services import worker_store

router = APIRouter()


@router.post("/ping", response_model=Status)
def ping(payload: PingRequest):
    """Worker nodes call this to register their heartbeat."""
    return worker_store.record_ping(payload.node_id, payload.node_type)


@router.get("/", response_model=list[Status])
def list_nodes():
    """List all known worker nodes."""
    return worker_store.get_all_nodes()


@router.get("/{node_id}", response_model=Status)
def get_node(node_id: str):
    """Get status of a specific node."""
    node = worker_store.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.delete("/{node_id}", status_code=204)
def remove_node(node_id: str):
    """Remove a node from the store."""
    if not worker_store.delete_node(node_id):
        raise HTTPException(status_code=404, detail="Node not found")
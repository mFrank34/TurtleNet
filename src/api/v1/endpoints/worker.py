from fastapi import APIRouter, HTTPException

from schemas.worker import Status, PingRequest
from services import worker_store

router = APIRouter()


@router.post("/ping", response_model=Status)
def ping(payload: PingRequest):
    """Worker nodes call this to register their heartbeat."""
    return worker_store.record_ping(payload.node_id, payload.node_type)


@router.get("/", response_model=list[Status])
def list_workers():
    """List all known workers."""
    return worker_store.get_all_workers()


@router.get("/{worker_id}", response_model=Status)
def get_worker(worker_id: str):
    """Get status of a specific worker."""
    worker = worker_store.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


@router.delete("/{worker_id}", status_code=204)
def delete_worker(worker_id: str):
    """Remove a worker from the store."""
    if not worker_store.delete_worker(worker_id):
        raise HTTPException(status_code=404, detail="Worker not found")
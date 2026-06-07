from fastapi import APIRouter

from api.v1.endpoints import items, worker, worker_ws

router = APIRouter()

router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(worker.router, prefix="/workers", tags=["workers"])
router.include_router(worker_ws.router, prefix="/workers", tags=["workers"])
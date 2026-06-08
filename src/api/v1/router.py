from fastapi import APIRouter

from src.api.v1.endpoints import worker_ws

router = APIRouter()

router.include_router(worker_ws.router, prefix="/workers", tags=["workers"])
from fastapi import APIRouter

from api.v1.endpoints import worker_ws
from api.v1.endpoints import actions

router = APIRouter()

router.include_router(worker_ws.router, prefix="/workers", tags=["workers"])
router.include_router(actions, prefix="/workers", tags=["actions"])
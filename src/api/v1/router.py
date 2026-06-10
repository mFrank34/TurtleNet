from fastapi import APIRouter

from api.v1.endpoints import worker_ws
from api.v1.endpoints.actions import router as actions_router
from api.v1.endpoints.agent_endpoint import router as agent_router

router = APIRouter()

router.include_router(worker_ws.router, prefix="/workers", tags=["workers"])
router.include_router(actions_router, prefix="/workers", tags=["actions"])


router.include_router(agent_router, prefix="/api/v1")
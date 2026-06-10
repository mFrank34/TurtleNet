from fastapi import APIRouter

from api.v1.endpoints import worker
from api.v1.endpoints.actions import router as actions_router
from api.v1.endpoints.agent import router as agent_router

router = APIRouter()

router.include_router(worker.router, prefix="/workers", tags=["workers"])
router.include_router(actions_router, prefix="/workers", tags=["actions"])

# FIX: Remove the prefix entirely so it respects the paths inside agent.py
router.include_router(agent_router, tags=["agents"])

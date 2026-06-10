"""
Agent & World Store endpoints

Location: src/api/v1/endpoints/agent.py
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from agents.registry import agent_registry
from api.v1.endpoints.worker import send_command, connected_workers
from schemas.agent import AgentResponse, StartAgentRequest
from services.world_store import world_store

router = APIRouter()


def _make_sender(worker_id: str):
    """
    Bind worker_id into send_command so agents can call:
        await send(worker_id, Command(...))
    matching the SendCommand type alias.
    """

    async def _send(wid: str, cmd):
        return await send_command(wid, cmd)

    return _send


# ------------------------------------------------------------------
# Agent control
# ------------------------------------------------------------------

@router.post("/workers/{worker_id}/agent", response_model=AgentResponse)
async def start_agent(worker_id: str, body: StartAgentRequest):
    if worker_id not in connected_workers:
        raise HTTPException(404, f"Worker '{worker_id}' not connected")
    try:
        status = await agent_registry.start(
            worker_id, _make_sender(worker_id), body.agent, body.args
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return AgentResponse(ok=True, worker_id=worker_id,
                         agent_type=status.agent_type, state=status.state, extra=status.extra)


@router.delete("/workers/{worker_id}/agent", response_model=AgentResponse)
async def stop_agent(worker_id: str):
    if not await agent_registry.stop(worker_id):
        raise HTTPException(404, f"No agent running for '{worker_id}'")
    return AgentResponse(ok=True, worker_id=worker_id, detail="stopped")


@router.post("/workers/{worker_id}/agent/pause", response_model=AgentResponse)
async def pause_agent(worker_id: str):
    if not agent_registry.pause(worker_id):
        raise HTTPException(404, f"No agent running for '{worker_id}'")
    return AgentResponse(ok=True, worker_id=worker_id, state="paused")


@router.post("/workers/{worker_id}/agent/resume", response_model=AgentResponse)
async def resume_agent(worker_id: str):
    if not agent_registry.resume(worker_id):
        raise HTTPException(404, f"No agent running for '{worker_id}'")
    return AgentResponse(ok=True, worker_id=worker_id, state="running")


@router.get("/workers/{worker_id}/agent", response_model=AgentResponse)
async def get_agent_status(worker_id: str):
    status = agent_registry.status(worker_id)
    if not status:
        raise HTTPException(404, f"No agent running for '{worker_id}'")
    return AgentResponse(ok=True, worker_id=worker_id,
                         agent_type=status.agent_type, state=status.state,
                         extra={**status.extra, "ticks": status.ticks, "position": status.position})


@router.get("/agents")
async def list_agents():
    return {"available": agent_registry.available_agents(),
            "running": agent_registry.all_statuses()}


# ------------------------------------------------------------------
# World store
# ------------------------------------------------------------------

@router.get("/world")
async def world_stats():
    return {"ok": True, **world_store.stats()}


@router.get("/world/search")
async def search_world(block: str, near_worker: Optional[str] = None, limit: int = 10):
    origin = (0, 0, 0)
    if near_worker:
        s = agent_registry.status(near_worker)
        if s and s.position:
            origin = (s.position["x"], s.position["y"], s.position["z"])
    results = world_store.find_nearest(origin, block, limit=limit)
    return {"ok": True, "query": block, "count": len(results),
            "cells": [c.to_dict() for c in results]}


@router.delete("/world")
async def clear_world():
    world_store._cells.clear()
    return {"ok": True, "detail": "World store cleared"}

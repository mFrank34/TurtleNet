"""
Agent Registry

Location: src/agents/__init__.py
"""

from __future__ import annotations

import asyncio
import logging
from typing import Type

from agents.base import BaseAgent, AgentStatus, SendCommand

logger = logging.getLogger(__name__)


def _build_registry() -> dict[str, Type[BaseAgent]]:
    from agents.wander import WanderAgent
    return {
        "wander": WanderAgent,
        # "miner":  MinerAgent,
        # "patrol": PatrolAgent,
    }


class AgentRegistry:
    """One active agent per worker. start() replaces any existing agent."""

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}
        self._registry = _build_registry()

    async def start(
            self,
            worker_id: str,
            send: SendCommand,
            agent_name: str,
            args: dict | None = None,
    ) -> AgentStatus:
        if agent_name not in self._registry:
            raise ValueError(f"Unknown agent '{agent_name}'. Available: {list(self._registry)}")
        await self.stop(worker_id)
        cls = self._registry[agent_name]
        agent = cls(worker_id=worker_id, send=send, args=args or {})
        self._agents[worker_id] = agent
        agent.start()
        logger.info(f"[{worker_id}] Started agent '{agent_name}'")
        return agent.status()

    async def stop(self, worker_id: str) -> bool:
        agent = self._agents.get(worker_id)
        if not agent:
            return False
        agent.stop()
        if agent._task:
            try:
                await asyncio.wait_for(agent._task, timeout=6.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                agent._task.cancel()
        del self._agents[worker_id]
        logger.info(f"[{worker_id}] Agent stopped")
        return True

    def pause(self, worker_id: str) -> bool:
        agent = self._agents.get(worker_id)
        if not agent:
            return False
        agent.pause()
        return True

    def resume(self, worker_id: str) -> bool:
        agent = self._agents.get(worker_id)
        if not agent:
            return False
        agent.resume()
        return True

    def status(self, worker_id: str) -> AgentStatus | None:
        agent = self._agents.get(worker_id)
        return agent.status() if agent else None

    def all_statuses(self) -> dict[str, dict]:
        return {wid: a.status().__dict__ for wid, a in self._agents.items()}

    def available_agents(self) -> list[str]:
        return list(self._registry)

    def is_running(self, worker_id: str) -> bool:
        agent = self._agents.get(worker_id)
        return agent is not None and not agent._task.done()


agent_registry = AgentRegistry()

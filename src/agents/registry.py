from __future__ import annotations

import asyncio
import logging
from typing import Type

from agents.base import BaseAgent, AgentStatus, SendCommand

logger = logging.getLogger(__name__)


def _build_registry() -> dict[str, Type[BaseAgent]]:
    # Move specific agent imports inside here to avoid circular imports
    from agents.wander import WanderAgent
    return {
        "wander": WanderAgent,
    }


class AgentRegistry:
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

        key = worker_id.lower()
        await self.stop(worker_id)

        cls = self._registry[agent_name]
        agent = cls(worker_id=worker_id, send=send, args=args or {})
        self._agents[key] = agent

        agent.start()

        # Monitor the task for silent crashes
        if hasattr(agent, '_task') and agent._task:
            agent._task.add_done_callback(lambda t: self._handle_crash(worker_id, t))

        logger.info(f"[{worker_id}] Started agent '{agent_name}'")
        return agent.status()

    def _handle_crash(self, worker_id: str, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"──► [CRITICAL] Agent loop for {worker_id} crashed: {e}", exc_info=True)

    async def stop(self, worker_id: str) -> bool:
        key = worker_id.lower()
        agent = self._agents.get(key)
        if not agent:
            return False
        agent.stop()
        if agent._task:
            try:
                await asyncio.wait_for(agent._task, timeout=6.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                agent._task.cancel()
        del self._agents[key]
        logger.info(f"[{worker_id}] Agent stopped")
        return True

    def status(self, worker_id: str) -> AgentStatus | None:
        return self._agents.get(worker_id.lower()).status() if worker_id.lower() in self._agents else None

    def all_statuses(self) -> dict[str, dict]:
        return {wid: a.status().__dict__ for wid, a in self._agents.items()}

    def available_agents(self) -> list[str]:
        return list(self._registry)

    def is_running(self, worker_id: str) -> bool:
        key = worker_id.lower()
        agent = self._agents.get(key)
        return agent is not None and not agent._task.done()


agent_registry = AgentRegistry()

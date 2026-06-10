"""
Base Agent — all turtle agents inherit from this.

Provides:
  - Async task loop (start / stop / pause)
  - Fuel monitor: checks inventory after every tick, triggers auto_refuel < 15%
  - 6-direction obstacle escape: forward → left → right → back → up → down
  - GPS position tracking via get_gps_location action
  - Heading tracking updated by turn_left / turn_right actions
  - State reporting
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Awaitable

from core.commands import Move, Inventory
from schemas.worker import Command

logger = logging.getLogger(__name__)

# Type alias matching TurtleNet's send_command signature
SendCommand = Callable[[str, Command], Awaitable[dict | None]]


# Helper — call an action from the ACTIONS registry
async def run_action(worker_id: str, send: SendCommand, name: str, args: dict = {}) -> dict:
    from services.actions import ACTIONS
    fn = ACTIONS.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown action '{name}'"}
    return await fn(worker_id, send, args)


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    RECOVERING = "recovering"  # handling obstacle or low fuel
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentStatus:
    agent_type: str
    state: AgentState
    worker_id: str
    position: Optional[dict]  # { x, y, z } or None
    ticks: int = 0
    last_error: Optional[str] = None
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    extra: dict = field(default_factory=dict)


# Heading → forward world-offset (Minecraft: Y is vertical, X/Z are horizontal)
HEADING_OFFSETS = {
    0: (0, 0, 1),  # North  +Z
    90: (1, 0, 0),  # East   +X
    180: (0, 0, -1),  # South  -Z
    270: (-1, 0, 0),  # West   -X
}

FUEL_LOW_THRESHOLD = 0.15  # 15%
FUEL_MAX_DEFAULT = 1000  # fallback when turtle doesn't report max


class BaseAgent(ABC):
    """
    Abstract base for all TurtleNet agents.

    Subclasses implement tick() — one logical step per loop iteration.
    Return True from tick() to continue, False to stop cleanly.
    """

    agent_type: str = "base"

    def __init__(
            self,
            worker_id: str,
            send: SendCommand,
            tick_delay: float = 0.5,
            args: dict | None = None,
    ):
        self.worker_id = worker_id
        self.send = send
        self.args = args or {}
        self.tick_delay = tick_delay

        self.state: AgentState = AgentState.IDLE
        self.position: Optional[dict] = None  # { x, y, z }
        self.heading: int = 0  # degrees clockwise, 0 = North
        self.fuel_level: Optional[int] = None
        self.fuel_max: int = FUEL_MAX_DEFAULT
        self.ticks: int = 0
        self.last_error: Optional[str] = None
        self.started_at: Optional[str] = None
        self.stopped_at: Optional[str] = None

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused initially

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> asyncio.Task:
        if self._task and not self._task.done():
            raise RuntimeError(f"Agent {self.worker_id} is already running")
        self._stop_event.clear()
        self._pause_event.set()
        self.state = AgentState.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._task = asyncio.create_task(self._loop(), name=f"agent-{self.worker_id}")
        logger.info(f"[{self.worker_id}] {self.agent_type} agent started")
        return self._task

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # unblock if paused so the loop can exit

    def pause(self):
        self._pause_event.clear()
        self.state = AgentState.PAUSED

    def resume(self):
        self._pause_event.set()
        self.state = AgentState.RUNNING

    def status(self) -> AgentStatus:
        return AgentStatus(
            agent_type=self.agent_type,
            state=self.state,
            worker_id=self.worker_id,
            position=self.position,
            ticks=self.ticks,
            last_error=self.last_error,
            started_at=self.started_at,
            stopped_at=self.stopped_at,
            extra=self._extra_status(),
        )

    def _extra_status(self) -> dict:
        """Override in subclasses to surface agent-specific fields."""
        return {}

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self):
        try:
            await self._on_start()
            while not self._stop_event.is_set():
                await self._pause_event.wait()
                if self._stop_event.is_set():
                    break
                try:
                    should_continue = await self._safe_tick()
                    if not should_continue:
                        break
                except Exception as exc:
                    logger.exception(f"[{self.worker_id}] Unhandled error in tick")
                    self.last_error = str(exc)
                    self.state = AgentState.ERROR
                    break
                self.ticks += 1
                await asyncio.sleep(self.tick_delay)
        finally:
            self.state = AgentState.STOPPED
            self.stopped_at = datetime.now(timezone.utc).isoformat()
            await self._on_stop()
            logger.info(f"[{self.worker_id}] {self.agent_type} agent stopped (ticks={self.ticks})")

    async def _safe_tick(self) -> bool:
        """Fuel check → subclass tick."""
        await self._check_fuel()
        return await self.tick()

    # ------------------------------------------------------------------
    # Fuel monitor
    # ------------------------------------------------------------------

    async def _check_fuel(self):
        """
        Scan inventory to infer fuel state, then call auto_refuel if low.
        We use Inventory.SCAN (already in actions) rather than a raw Lua
        string, keeping all comms through the Command schema.
        """
        result = await self.send(self.worker_id, Command(command=Inventory.SCAN))
        if result and result.get("status") == "ok":
            # Worker status pings include fuel_level; grab it if present
            fuel = result.get("fuel_level")
            if fuel is not None:
                try:
                    self.fuel_level = int(fuel)
                except (TypeError, ValueError):
                    pass

        if self.fuel_level is None:
            return

        ratio = self.fuel_level / self.fuel_max
        if ratio < FUEL_LOW_THRESHOLD:
            logger.info(f"[{self.worker_id}] Low fuel ({self.fuel_level}/{self.fuel_max}), refuelling")
            prev_state = self.state
            self.state = AgentState.RECOVERING
            result = await run_action(self.worker_id, self.send, "auto_refuel")
            if not result.get("ok"):
                self.last_error = "refuel failed: " + result.get("error", "unknown")
                logger.warning(f"[{self.worker_id}] {self.last_error}")
            self.state = prev_state

    # ------------------------------------------------------------------
    # Movement — all motion goes through actions so heading stays in sync
    # ------------------------------------------------------------------

    async def move(self, direction: str) -> bool:
        """
        Move in a relative direction: forward / back / up / down / left / right.
        left/right = turn + forward (+ undo turn on failure).
        Updates self.heading and self.position on success.
        Returns True on success.
        """
        if direction == "left":
            return await self._turn_and_move("left")
        elif direction == "right":
            return await self._turn_and_move("right")
        else:
            return await self._simple_move(direction)

    async def _simple_move(self, direction: str) -> bool:
        """forward / back / up / down."""
        cmd_map = {
            "forward": Move.FORWARD,
            "back": Move.BACK,
            "up": Move.UP,
            "down": Move.DOWN,
        }
        cmd = cmd_map.get(direction)
        if cmd is None:
            return False
        result = await self.send(self.worker_id, Command(command=cmd))
        ok = result is not None and result.get("status") == "ok"
        if ok:
            self._update_position(direction)
        return ok

    async def _turn_and_move(self, side: str) -> bool:
        """Turn left/right then move forward; undo turn if blocked."""
        turn_cmd = Move.LEFT if side == "left" else Move.RIGHT
        unturn_cmd = Move.RIGHT if side == "left" else Move.LEFT
        heading_delta = -90 if side == "left" else 90

        # Turn
        result = await self.send(self.worker_id, Command(command=turn_cmd))
        if not result or result.get("status") != "ok":
            return False
        self.heading = (self.heading + heading_delta) % 360

        # Move forward
        fwd = await self.send(self.worker_id, Command(command=Move.FORWARD))
        ok = fwd is not None and fwd.get("status") == "ok"

        if ok:
            self._update_position("forward")
        else:
            # Undo the turn so heading stays consistent
            await self.send(self.worker_id, Command(command=unturn_cmd))
            self.heading = (self.heading - heading_delta) % 360

        return ok

    def _update_position(self, direction: str):
        """Dead-reckon position after a confirmed move."""
        if self.position is None:
            return
        dx, dy, dz = HEADING_OFFSETS.get(self.heading, (0, 0, 0))
        if direction == "forward":
            self.position["x"] += dx
            self.position["z"] += dz
        elif direction == "back":
            self.position["x"] -= dx
            self.position["z"] -= dz
        elif direction == "up":
            self.position["y"] += 1
        elif direction == "down":
            self.position["y"] -= 1

    # ------------------------------------------------------------------
    # Obstacle escape — tries all 6 directions
    # ------------------------------------------------------------------

    ESCAPE_ORDER = ["left", "right", "up", "down", "back"]

    async def escape_obstacle(self, blocked_direction: str = "forward") -> bool:
        """Try alternate directions until one succeeds. Returns True if escaped."""
        logger.info(f"[{self.worker_id}] Obstacle on {blocked_direction}, attempting escape")
        prev_state = self.state
        self.state = AgentState.RECOVERING

        for direction in self.ESCAPE_ORDER:
            if direction == blocked_direction:
                continue
            ok = await self.move(direction)
            if ok:
                logger.info(f"[{self.worker_id}] Escaped via {direction}")
                self.state = prev_state
                return True

        logger.warning(f"[{self.worker_id}] Fully blocked — no escape found")
        self.state = prev_state
        return False

    # ------------------------------------------------------------------
    # GPS sync
    # ------------------------------------------------------------------

    async def sync_gps(self) -> bool:
        """Pull real GPS coords from get_gps_location action and store them."""
        result = await run_action(self.worker_id, self.send, "get_gps_location")
        if result.get("ok") and result.get("location"):
            self.position = result["location"]
            logger.info(f"[{self.worker_id}] GPS synced: {self.position}")
            return True
        logger.warning(f"[{self.worker_id}] GPS sync failed: {result.get('error')}")
        return False

    # ------------------------------------------------------------------
    # Hooks & abstract interface
    # ------------------------------------------------------------------

    async def _on_start(self):
        """Called once before the loop. Sync GPS so position is set immediately."""
        await self.sync_gps()

    async def _on_stop(self):
        """Called once after the loop ends."""
        pass

    @abstractmethod
    async def tick(self) -> bool:
        """One step of agent logic. Return True to continue, False to stop."""
        ...

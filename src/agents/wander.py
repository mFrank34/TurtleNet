"""
Wander Agent — explores the world, preferring unscanned territory.

Movement memory: tracks last HISTORY_SIZE moves and penalises directions
that would retrace recent steps, preventing back-and-forth looping.

Vertical bias: strongly prefers down over up to avoid floating into sky.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from typing import Optional

from agents.base import BaseAgent, SendCommand, run_action, HEADING_OFFSETS
from services.world_store import world_store

logger = logging.getLogger(__name__)

GPS_SYNC_INTERVAL = 20
HISTORY_SIZE = 6  # how many recent moves to remember

# Opposite of each direction — used to detect immediate reversal
OPPOSITE = {
    "forward": "back",
    "back": "forward",
    "left": "right",
    "right": "left",
    "up": "down",
    "down": "up",
}


class WanderAgent(BaseAgent):
    agent_type = "wander"

    def __init__(self, worker_id: str, send: SendCommand, args: dict | None = None):
        super().__init__(worker_id, send, tick_delay=0.5, args=args or {})
        self.steps_taken: int = 0
        self.blocks_found: int = 0
        self.cells_scanned: int = 0
        self.last_direction: Optional[str] = None
        self.history: deque[str] = deque(maxlen=HISTORY_SIZE)

    # ------------------------------------------------------------------
    # Core tick
    # ------------------------------------------------------------------

    async def tick(self) -> bool:
        if self.ticks > 0 and self.ticks % GPS_SYNC_INTERVAL == 0:
            await self.sync_gps()

        direction = self._choose_direction()

        if direction == "forward":
            moved = await self._move_and_scan()
        else:
            moved = await self.move(direction)

        if not moved:
            escaped = await self.escape_obstacle(blocked_direction=direction)
            if not escaped:
                logger.warning(f"[{self.worker_id}] Fully stuck, waiting 2s")
                await asyncio.sleep(2)

        if moved:
            self.steps_taken += 1
            self.last_direction = direction
            self.history.append(direction)

        return True

    # ------------------------------------------------------------------
    # move_and_scan wrapper
    # ------------------------------------------------------------------

    async def _move_and_scan(self) -> bool:
        result = await run_action(self.worker_id, self.send, "move_and_scan")
        if not result.get("ok"):
            return False
        if result.get("location"):
            self.position = result["location"]
        blocks = result.get("blocks", {})
        if blocks and self.position:
            self.cells_scanned += len(blocks)
            world_store.record_many(
                origin=(self.position["x"], self.position["y"], self.position["z"]),
                blocks=blocks,
                scanned_by=self.worker_id,
            )
            for b in blocks.values():
                if b and b.get("name") and "air" not in b["name"]:
                    self.blocks_found += 1
        return True

    # ------------------------------------------------------------------
    # Direction selection
    # ------------------------------------------------------------------

    def _choose_direction(self) -> str:
        # Try world-store guided direction first
        if self.position is not None:
            unscanned = world_store.find_unscanned_neighbours(
                (self.position["x"], self.position["y"], self.position["z"]),
                radius=6,
            )
            if unscanned:
                # Try candidates in order until we find one not penalised by history
                for target in unscanned[:8]:
                    direction = self._direction_toward(target)
                    if direction and not self._is_backtrack(direction):
                        return direction
                # All candidates look like backtracks — take the least-repeated one
                for target in unscanned[:8]:
                    direction = self._direction_toward(target)
                    if direction:
                        return direction

        return self._weighted_random()

    def _weighted_random(self) -> str:
        """
        Weighted random pick across all 6 directions.
        Penalties applied from movement history to break loops.
        """
        directions = ["forward", "left", "right", "back", "down", "up"]
        weights = []

        for d in directions:
            w = 3  # base horizontal weight

            # Vertical bias
            if d == "up":
                w = 1
            elif d == "down":
                w = 4

            # Penalise directions that appeared recently in history
            recent_count = sum(1 for h in self.history if h == d)
            w = max(1, w - recent_count * 2)

            # Hard penalise immediate reversal of last move
            if self.last_direction and d == OPPOSITE.get(self.last_direction):
                w = 1

            weights.append(w)

        return random.choices(directions, weights=weights, k=1)[0]

    def _is_backtrack(self, direction: str) -> bool:
        """
        Returns True if this direction would likely retrace recent steps.
        - Immediate reversal of last move = always backtrack
        - Direction appeared 2+ times in recent history = likely loop
        """
        if self.last_direction and direction == OPPOSITE.get(self.last_direction):
            return True
        recent_count = sum(1 for h in self.history if h == direction)
        return recent_count >= 2

    def _direction_toward(self, target: tuple[int, int, int]) -> Optional[str]:
        if self.position is None:
            return None

        dx = target[0] - self.position["x"]
        dy = target[1] - self.position["y"]
        dz = target[2] - self.position["z"]

        # Only go up if target is massively above and horizontal gap is tiny
        if dy > 0 and abs(dy) > max(abs(dx), abs(dz)) * 2:
            return "up"

        # Go down readily
        if dy < 0 and abs(dy) > max(abs(dx), abs(dz)):
            return "down"

        # Prefer horizontal
        fwd_dx, _, fwd_dz = HEADING_OFFSETS[self.heading]
        right_dx, _, right_dz = HEADING_OFFSETS[(self.heading + 90) % 360]

        fwd_dot = dx * fwd_dx + dz * fwd_dz
        right_dot = dx * right_dx + dz * right_dz

        if abs(fwd_dot) >= abs(right_dot):
            return "forward" if fwd_dot >= 0 else "back"
        else:
            return "right" if right_dot >= 0 else "left"

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _extra_status(self) -> dict:
        return {
            "steps_taken": self.steps_taken,
            "blocks_found": self.blocks_found,
            "cells_scanned": self.cells_scanned,
            "last_direction": self.last_direction,
            "recent_moves": list(self.history),
            "heading_deg": self.heading,
            "world_cells": world_store.stats()["total_cells"],
        }

"""
Wander Agent — explores the world, preferring unscanned territory.

Each tick:
  1. Choose the best direction toward nearest unscanned area (random fallback)
  2. Call move_and_scan action — moves forward AND scans in one round trip
  3. If blocked, try escape_obstacle then retry
  4. Write scanned blocks to world_store
  5. Re-sync GPS every GPS_SYNC_INTERVAL ticks to correct drift

Note: move_and_scan moves forward only, so left/right/up/down are handled
as plain moves (no scan) when navigating toward unscanned areas.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from agents.base import BaseAgent, SendCommand, run_action, HEADING_OFFSETS

from services.world_store import world_store

logger = logging.getLogger(__name__)

GPS_SYNC_INTERVAL = 20


class WanderAgent(BaseAgent):
    agent_type = "wander"

    def __init__(self, worker_id: str, send: SendCommand, args: dict | None = None):
        super().__init__(worker_id, send, tick_delay=0.5, args=args or {})
        self.steps_taken: int = 0
        self.blocks_found: int = 0
        self.cells_scanned: int = 0
        self.last_direction: Optional[str] = None

    # ------------------------------------------------------------------
    # Core tick
    # ------------------------------------------------------------------

    async def tick(self) -> bool:
        # Periodically re-anchor via real GPS to correct dead-reckoning drift
        if self.ticks > 0 and self.ticks % GPS_SYNC_INTERVAL == 0:
            await self.sync_gps()

        direction = self._choose_direction()

        if direction == "forward":
            # move_and_scan moves forward and scans surroundings in one action
            moved = await self._move_and_scan()
        else:
            # For any non-forward direction, just move (facing will change heading)
            moved = await self.move(direction)

        if not moved:
            escaped = await self.escape_obstacle(blocked_direction=direction)
            if not escaped:
                logger.warning(f"[{self.worker_id}] Fully stuck, waiting 2s")
                await asyncio.sleep(2)
                return True  # keep running — something may unblock

        self.steps_taken += 1
        self.last_direction = direction
        return True  # wander runs until explicitly stopped

    # ------------------------------------------------------------------
    # move_and_scan wrapper
    # ------------------------------------------------------------------

    async def _move_and_scan(self) -> bool:
        """
        Call the move_and_scan action. It moves forward, verifies via GPS,
        and returns scanned blocks + confirmed position.
        Returns True if move succeeded.
        """
        result = await run_action(self.worker_id, self.send, "move_and_scan")

        if not result.get("ok"):
            # move_and_scan returns ok=False when movement was blocked
            return False

        # Update our position from the GPS-verified location in the result
        if result.get("location"):
            self.position = result["location"]

        # Write scanned blocks to world store
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
    # Direction selection — prefer unscanned neighbours
    # ------------------------------------------------------------------

    def _choose_direction(self) -> str:
        """
        Pick the best next direction.
        - If we know our position, aim toward the nearest unscanned cell.
        - Otherwise fall back to weighted random (avoid repeating last direction).
        """
        if self.position is not None:
            unscanned = world_store.find_unscanned_neighbours(
                (self.position["x"], self.position["y"], self.position["z"]),
                radius=6,
            )
            if unscanned:
                # Pick from nearest 5 to avoid always beelining the same spot
                target = random.choice(unscanned[:5])
                direction = self._direction_toward(target)
                if direction:
                    return direction

        # Weighted random — down-weight last direction to reduce backtracking
        horizontal = ["forward", "left", "right", "back"]
        weights = [
            1 if d == self.last_direction else 3
            for d in horizontal
        ]
        return random.choices(horizontal, weights=weights, k=1)[0]

    def _direction_toward(self, target: tuple[int, int, int]) -> Optional[str]:
        """
        Return the relative direction (forward/back/left/right/up/down)
        that moves closest to target given the current heading.
        """
        if self.position is None:
            return None

        tx, ty, tz = target
        px = self.position["x"]
        py = self.position["y"]
        pz = self.position["z"]
        dx, dy, dz = tx - px, ty - py, tz - pz

        # Go vertical first if the Y gap is dominant
        if abs(dy) > max(abs(dx), abs(dz)):
            return "up" if dy > 0 else "down"

        # Project world delta onto our current facing axes
        fwd_dx, _, fwd_dz = HEADING_OFFSETS[self.heading]
        right_dx, _, right_dz = HEADING_OFFSETS[(self.heading + 90) % 360]

        fwd_dot = dx * fwd_dx + dz * fwd_dz
        right_dot = dx * right_dx + dz * right_dz

        if abs(fwd_dot) >= abs(right_dot):
            return "forward" if fwd_dot >= 0 else "back"
        else:
            return "right" if right_dot >= 0 else "left"

    # ------------------------------------------------------------------
    # Status extras
    # ------------------------------------------------------------------

    def _extra_status(self) -> dict:
        return {
            "steps_taken": self.steps_taken,
            "blocks_found": self.blocks_found,
            "cells_scanned": self.cells_scanned,
            "last_direction": self.last_direction,
            "heading_deg": self.heading,
            "world_cells": world_store.stats()["total_cells"],
        }

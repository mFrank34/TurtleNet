"""
Wander Agent — explores the world, preferring unscanned territory.

Each tick:
  1. Choose best direction toward nearest unscanned area (random fallback)
  2. Call move_and_scan action — moves forward AND scans in one round trip
  3. If blocked, try escape_obstacle then retry
  4. Write scanned blocks to world_store
  5. Re-sync GPS every GPS_SYNC_INTERVAL ticks to correct drift

Vertical bias: strongly prefers moving down over up to avoid floating into sky.
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
    # Direction selection — prefer unscanned neighbours, bias downward
    # ------------------------------------------------------------------

    def _choose_direction(self) -> str:
        if self.position is not None:
            unscanned = world_store.find_unscanned_neighbours(
                (self.position["x"], self.position["y"], self.position["z"]),
                radius=6,
            )
            if unscanned:
                target = random.choice(unscanned[:5])
                direction = self._direction_toward(target)
                if direction:
                    return direction

        # Weighted random fallback:
        #   up   = 1  (strongly avoid — ends up in sky)
        #   down = 4  (bias downward — explore underground)
        #   horizontal = 3 each
        #   repeat last direction = 1 (avoid backtracking)
        directions = ["forward", "left", "right", "back", "down", "up"]
        weights = []
        for d in directions:
            if d == self.last_direction:
                weights.append(1)
            elif d == "up":
                weights.append(1)
            elif d == "down":
                weights.append(4)
            else:
                weights.append(3)
        return random.choices(directions, weights=weights, k=1)[0]

    def _direction_toward(self, target: tuple[int, int, int]) -> Optional[str]:
        if self.position is None:
            return None

        dx = target[0] - self.position["x"]
        dy = target[1] - self.position["y"]
        dz = target[2] - self.position["z"]

        # Only go UP if target is massively above and horizontal gap is tiny
        # High multiplier means horizontal movement is strongly preferred over up
        if dy > 0 and abs(dy) > max(abs(dx), abs(dz)) * 2:
            return "up"

        # Go DOWN readily — target just needs to be below and somewhat dominant
        if dy < 0 and abs(dy) > max(abs(dx), abs(dz)):
            return "down"

        # Otherwise stay horizontal
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
            "heading_deg": self.heading,
            "world_cells": world_store.stats()["total_cells"],
        }

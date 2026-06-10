"""
World Store — persistent map of everything turtles have scanned.

Keyed by (x, y, z) tuples. Populated by agents automatically.
Queryable by block name, proximity, scan time, etc.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class WorldCell:
    x: int
    y: int
    z: int
    block: str  # e.g. "minecraft:coal_ore"
    scanned_by: str  # worker_id
    scanned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scanned_at"] = self.scanned_at.isoformat()
        return d


class WorldStore:
    """
    In-memory store of scanned world cells.

    Coords are stored as integer keys — GPS returns floats so we round on insert.
    """

    def __init__(self):
        self._cells: dict[tuple[int, int, int], WorldCell] = {}

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, x: float, y: float, z: float, block: str, scanned_by: str) -> WorldCell:
        """Insert or update a cell. Always overwrites with latest scan."""
        key = (round(x), round(y), round(z))
        cell = WorldCell(x=key[0], y=key[1], z=key[2], block=block, scanned_by=scanned_by)
        self._cells[key] = cell
        return cell

    def record_many(self, origin: tuple[float, float, float], blocks: dict, scanned_by: str):
        """
        Record a batch from a move_and_scan result.
        `blocks` is { "forward": {...}, "up": {...}, "down": {...} }
        `origin` is the turtle's current position.
        """
        ox, oy, oz = origin
        offsets = {
            "forward": (1, 0, 0),  # simplified — real offset depends on heading
            "up": (0, 1, 0),
            "down": (0, -1, 0),
        }
        for direction, offset in offsets.items():
            cell_data = blocks.get(direction)
            if cell_data and cell_data.get("name"):
                dx, dy, dz = offset
                self.record(
                    ox + dx, oy + dy, oz + dz,
                    cell_data["name"],
                    scanned_by,
                )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, x: float, y: float, z: float) -> Optional[WorldCell]:
        return self._cells.get((round(x), round(y), round(z)))

    def is_scanned(self, x: float, y: float, z: float) -> bool:
        return (round(x), round(y), round(z)) in self._cells

    def all_cells(self) -> list[WorldCell]:
        return list(self._cells.values())

    def find_nearest(
            self,
            origin: tuple[float, float, float],
            block_name: str,
            limit: int = 10,
    ) -> list[WorldCell]:
        """Return up to `limit` cells matching block_name, sorted by distance."""
        ox, oy, oz = origin
        matches = [c for c in self._cells.values() if block_name in c.block]
        matches.sort(key=lambda c: math.dist((c.x, c.y, c.z), (ox, oy, oz)))
        return matches[:limit]

    def find_unscanned_neighbours(
            self,
            origin: tuple[float, float, float],
            radius: int = 8,
    ) -> list[tuple[int, int, int]]:
        """
        Return grid positions within radius that have NOT been scanned.
        Used by the wander agent to prefer new territory.
        """
        ox, oy, oz = round(origin[0]), round(origin[1]), round(origin[2])
        candidates = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    pos = (ox + dx, oy + dy, oz + dz)
                    if pos not in self._cells:
                        dist = math.dist(pos, (ox, oy, oz))
                        if 1 <= dist <= radius:
                            candidates.append((pos, dist))
        candidates.sort(key=lambda t: t[1])
        return [pos for pos, _ in candidates]

    def stats(self) -> dict:
        total = len(self._cells)
        block_counts: dict[str, int] = {}
        for cell in self._cells.values():
            block_counts[cell.block] = block_counts.get(cell.block, 0) + 1
        return {"total_cells": total, "blocks": block_counts}


# Global singleton — import this everywhere
world_store = WorldStore()

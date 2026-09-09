"""Synthetic load generator for the "scale from 10 to 500 NPCs" menu.

The real pitch — a few Gemini-reasoned leads plus cheap, infrequent
background reasoning — cannot scale to hundreds of *live* model calls on a
shared free-tier quota (15 requests/minute; see rate_limiter.py). What
genuinely needs to scale to a crowd is the data layer: writing every tick
and answering aggregate questions about the crowd in real time. This module
writes templated (not model-generated) decision ticks for a chosen number
of synthetic extras through the same ClickHouse tables as the real cast, so
the menu proves out ClickHouse's write/query throughput honestly instead of
pretending hundreds of concurrent Gemini agents are running.
"""

import asyncio
import random
import time

from backend.ingest import _escape
from backend.mcp_client import PersistentClickHouseMCP

ID_PREFIX = "synth-"
MIN_COUNT = 10
MAX_COUNT = 500
PULSE_INTERVAL_SECONDS = 3.0
PULSE_BATCH_SIZE = 40  # synthetic NPCs refreshed with a new tick each pulse

ROLES = [
    "background extra", "crowd double", "stand-in", "featured extra",
    "set dresser", "background diner", "background dancer", "PA",
]
MOODS = ["neutral", "tense", "curious", "bored", "alert", "nervous", "amused", "focused"]
ACTIONS = [
    "adjusts their mark and waits for cue",
    "glances toward the commotion, then back to their task",
    "shuffles a step closer to get a better view",
    "keeps to the background, staying in character",
    "resets their prop and holds position",
]
REASONINGS = [
    "Nothing in the scene calls for me to react yet, so I hold my mark.",
    "The confrontation is loud enough that my character would notice it.",
    "My blocking says I stay put unless directed otherwise.",
    "Reacting too much would pull focus, so I keep it subtle.",
]


def _synth_id(i: int) -> str:
    return f"{ID_PREFIX}{i:04d}"


def build_synthetic_cast(count: int) -> list[dict]:
    return [
        {"npc_id": _synth_id(i), "name": f"{random.choice(ROLES)} #{i}", "tier": "background"}
        for i in range(1, count + 1)
    ]


def _random_decision_row(npc_id: str) -> tuple[str, str, str, str]:
    return npc_id, random.choice(REASONINGS), random.choice(ACTIONS), random.choice(MOODS)


class ScaleSimulation:
    """Owns the currently active synthetic-cast size and its pulse task.

    Uses its own write-capable ClickHouse session, separate from the
    read-only session the API's other endpoints use and from the real
    simulation's own session — so this load generator can never contend
    with or degrade the genuine Gemini-reasoned demo.
    """

    def __init__(self, mcp: PersistentClickHouseMCP):
        self._mcp = mcp
        self.active_count = 0
        self._task: asyncio.Task | None = None

    async def set_count(self, count: int) -> dict:
        count = 0 if count <= 0 else max(MIN_COUNT, min(MAX_COUNT, count))
        if count == 0:
            self.active_count = 0
            return await self.stats()

        wanted = build_synthetic_cast(count)
        existing = await self._mcp.run_query(
            f"SELECT npc_id FROM npcs WHERE npc_id LIKE '{ID_PREFIX}%'"
        )
        existing_ids = {row[0] for row in existing.get("rows") or []}
        missing = [n for n in wanted if n["npc_id"] not in existing_ids]
        if missing:
            values = ", ".join(
                f"('{_escape(n['npc_id'])}', '{_escape(n['name'])}', '{n['tier']}')"
                for n in missing
            )
            await self._mcp.run_query(f"INSERT INTO npcs (npc_id, name, tier) VALUES {values}")

        rows = [_random_decision_row(n["npc_id"]) for n in wanted]
        start = time.time()
        await self._insert_decisions(rows)
        insert_ms = (time.time() - start) * 1000

        self.active_count = count
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._pulse_loop())

        stats = await self.stats()
        stats["insert_ms"] = round(insert_ms, 1)
        return stats

    async def stop(self):
        self.active_count = 0
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _insert_decisions(self, rows: list[tuple]):
        if not rows:
            return
        values = ", ".join(
            f"('{_escape(npc_id)}', '{_escape(reasoning)}', '{_escape(action)}', '{_escape(mood)}')"
            for npc_id, reasoning, action, mood in rows
        )
        await self._mcp.run_query(
            f"INSERT INTO decisions (npc_id, reasoning, action, mood) VALUES {values}"
        )

    async def _pulse_loop(self):
        """Keep a rotating sample of the active synthetic cast ticking so the
        scale view stays visibly live, without ever calling a model."""
        while self.active_count > 0:
            await asyncio.sleep(PULSE_INTERVAL_SECONDS)
            n = min(PULSE_BATCH_SIZE, self.active_count)
            ids = random.sample(range(1, self.active_count + 1), n)
            try:
                await self._insert_decisions([_random_decision_row(_synth_id(i)) for i in ids])
            except Exception as exc:
                print(f"scale pulse insert failed: {exc}")

    async def stats(self) -> dict:
        if self.active_count == 0:
            return {"active_count": 0, "mood_counts": {}, "total_rows": 0, "recent_rows": 0}

        hi = _synth_id(self.active_count)
        start = time.time()
        mood_result = await self._mcp.run_query(f"""
            SELECT mood, count() AS c FROM (
                SELECT npc_id, argMax(mood, ts) AS mood
                FROM decisions
                WHERE npc_id LIKE '{ID_PREFIX}%' AND npc_id <= '{hi}'
                GROUP BY npc_id
            ) GROUP BY mood ORDER BY c DESC
        """)
        totals_result = await self._mcp.run_query(f"""
            SELECT count() AS total_rows,
                   countIf(ts > now64(3) - INTERVAL 10 SECOND) AS recent_rows
            FROM decisions
            WHERE npc_id LIKE '{ID_PREFIX}%' AND npc_id <= '{hi}'
        """)
        query_ms = (time.time() - start) * 1000

        mood_counts = {row[0]: row[1] for row in mood_result.get("rows") or []}
        total_rows, recent_rows = (totals_result["rows"][0] if totals_result.get("rows") else (0, 0))
        return {
            "active_count": self.active_count,
            "mood_counts": mood_counts,
            "total_rows": total_rows,
            "recent_rows": recent_rows,
            "query_ms": round(query_ms, 1),
        }

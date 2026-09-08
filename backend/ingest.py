"""Batches NPC ticks/decisions/events and writes them to ClickHouse via
mcp-clickhouse on a timer. No LLM involved on this path — see tiering.py and
agents.py for where reasoning happens; this module only persists results.
"""

import asyncio
import time

from backend.mcp_client import PersistentClickHouseMCP

FLUSH_INTERVAL_SECONDS = 1.5


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class IngestQueue:
    def __init__(self):
        self._context_ticks: list[tuple] = []
        self._decisions: list[tuple] = []
        self._events: list[tuple] = []
        self._lock = asyncio.Lock()

    async def add_context_tick(self, npc_id: str, tier: str, context_snippet: str, goal: str):
        async with self._lock:
            self._context_ticks.append((npc_id, tier, context_snippet, goal))

    async def add_decision(self, npc_id: str, reasoning: str, action: str, mood: str):
        async with self._lock:
            self._decisions.append((npc_id, reasoning, action, mood))

    async def add_event(self, npc_id: str, event_type: str, payload: str):
        async with self._lock:
            self._events.append((npc_id, event_type, payload))

    async def _drain(self):
        async with self._lock:
            batches = (self._context_ticks, self._decisions, self._events)
            self._context_ticks, self._decisions, self._events = [], [], []
            return batches

    async def run_forever(self, client: PersistentClickHouseMCP):
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await self.flush(client)

    async def flush(self, client: PersistentClickHouseMCP):
        context_ticks, decisions, events = await self._drain()

        if context_ticks:
            values = ", ".join(
                f"('{_escape(npc_id)}', '{tier}', '{_escape(snippet)}', '{_escape(goal)}')"
                for npc_id, tier, snippet, goal in context_ticks
            )
            await client.run_query(
                f"INSERT INTO context_ticks (npc_id, tier, context_snippet, goal) VALUES {values}"
            )

        if decisions:
            values = ", ".join(
                f"('{_escape(npc_id)}', '{_escape(reasoning)}', '{_escape(action)}', '{_escape(mood)}')"
                for npc_id, reasoning, action, mood in decisions
            )
            await client.run_query(
                f"INSERT INTO decisions (npc_id, reasoning, action, mood) VALUES {values}"
            )

        if events:
            values = ", ".join(
                f"('{_escape(npc_id)}', '{_escape(event_type)}', '{_escape(payload)}')"
                for npc_id, event_type, payload in events
            )
            await client.run_query(
                f"INSERT INTO events (npc_id, event_type, payload) VALUES {values}"
            )


async def upsert_npcs(client: PersistentClickHouseMCP, npcs: list[dict]):
    """One-time registration of NPC identities (npc_id, name, tier)."""
    values = ", ".join(
        f"('{_escape(n['npc_id'])}', '{_escape(n['name'])}', '{n['tier']}')"
        for n in npcs
    )
    await client.run_query(f"INSERT INTO npcs (npc_id, name, tier) VALUES {values}")

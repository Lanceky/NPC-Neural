"""Simulation loop: world state -> tiering scheduler -> ADK reasoning ticks
-> ClickHouse via the ingestion queue.

Demo cast: a noir confrontation scene (2 principal leads, 12 background
extras) — the "previz crowd simulation" pitch in miniature. Background
context is rebuilt from an immutable base each tick (base + last action),
so prompt size stays bounded no matter how many ticks have run.
"""

import asyncio
import time
from dataclasses import dataclass

from backend.agents import run_tick
from backend.ingest import IngestQueue, upsert_npcs
from backend.mcp_client import PersistentClickHouseMCP
from backend.tiering import NPCState, plan_ticks

MAX_CONCURRENT_TICKS = 4
LOOP_RESOLUTION_SECONDS = 1.0

# (seconds since sim start, npc_id, event_type, payload) — fires once each.
EVENT_TIMELINE = [
    (8.0, "guest-2", "overheard_gossip", "overhears a rumor that changes everything"),
    (20.0, "photographer", "camera_flash", "camera flash startles the room"),
    (35.0, "security", "raised_voice", "someone raises their voice near the exit"),
]


@dataclass
class NPC:
    npc_id: str
    name: str
    tier: str
    base_context: str
    goal: str
    mood: str = "neutral"
    last_action: str = ""
    last_tick_ts: float | None = None
    notable_event: bool = False
    notable_payload: str = ""

    def current_context(self) -> str:
        if not self.last_action:
            return self.base_context
        return f"{self.base_context} Moments ago you: {self.last_action} (feeling {self.mood})."


def build_cast() -> list[NPC]:
    return [
        NPC("detective", "Detective Voss", "principal",
            "You've just publicly accused the Suspect of murder in a crowded "
            "manor bar. All eyes are on you.",
            "extract a confession from the Suspect in front of the room"),
        NPC("suspect", "Mr. Ashford", "principal",
            "The Detective has just publicly accused you of murder in front "
            "of the entire party.",
            "protect your reputation and deflect suspicion"),
        NPC("bartender", "the bartender", "background",
            "standing behind the bar, drinks piling up, tension rising",
            "keep serving drinks despite the commotion"),
        NPC("waiter-1", "a waiter", "background",
            "weaving through tense guests with a full tray",
            "deliver drinks without spilling"),
        NPC("waiter-2", "a waiter", "background",
            "collecting empty glasses near the wall",
            "clear empty glasses quietly"),
        NPC("guest-1", "a party guest", "background",
            "standing near the confrontation, pretending to sip a drink",
            "eavesdrop without being noticed"),
        NPC("guest-2", "a party guest", "background",
            "leaning toward a friend at the edge of the room",
            "whisper gossip about the accusation"),
        NPC("guest-3", "a party guest", "background",
            "near the exit, unsettled by the shouting",
            "decide whether to leave the room"),
        NPC("guest-4", "a party guest", "background",
            "craning for a better view over the crowd",
            "get a better view of the confrontation"),
        NPC("musician", "the pianist", "background",
            "mid-song at the piano as the room goes tense",
            "decide whether to keep playing or stop"),
        NPC("security", "a security guard", "background",
            "posted at the wall, scanning the crowd",
            "watch the room for signs of trouble"),
        NPC("photographer", "a photographer", "background",
            "camera raised at the back of the room",
            "get a candid photo of the confrontation"),
        NPC("valet", "the valet", "background",
            "outside at the valet stand, unaware of the drama",
            "keep parking arriving cars"),
        NPC("coatcheck", "the coat-check attendant", "background",
            "at the coat-check counter, hearing muffled shouting",
            "handle the next coat-check request"),
    ]


def _apply_timeline(cast_by_id: dict[str, NPC], elapsed: float, fired: set[float]):
    for offset, npc_id, event_type, payload in EVENT_TIMELINE:
        if offset in fired or elapsed < offset:
            continue
        fired.add(offset)
        npc = cast_by_id.get(npc_id)
        if npc:
            npc.notable_event = True
            npc.notable_payload = f"{event_type}: {payload}"


async def _register_new_npcs(mcp: PersistentClickHouseMCP, cast: list[NPC]):
    existing = await mcp.run_query("SELECT npc_id FROM npcs")
    existing_ids = {row[0] for row in existing.get("rows") or []}
    new_npcs = [
        {"npc_id": n.npc_id, "name": n.name, "tier": n.tier}
        for n in cast if n.npc_id not in existing_ids
    ]
    if new_npcs:
        await upsert_npcs(mcp, new_npcs)


async def run_simulation(duration_seconds: float | None = None):
    cast = build_cast()
    cast_by_id = {n.npc_id: n for n in cast}
    ingest = IngestQueue()
    fired_events: set[float] = set()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TICKS)

    async with PersistentClickHouseMCP(allow_write=True) as mcp:
        await _register_new_npcs(mcp, cast)
        flush_task = asyncio.create_task(ingest.run_forever(mcp))
        start = time.time()

        async def run_one(plan):
            npc = cast_by_id[plan.npc_id]
            context = npc.current_context()
            try:
                async with semaphore:
                    decision = await run_tick(npc.npc_id, plan.run_tier, context, npc.goal)
            except Exception as exc:
                print(f"tick failed for {npc.npc_id}: {exc}")
                return
            await ingest.add_context_tick(npc.npc_id, plan.run_tier, context, npc.goal)
            await ingest.add_decision(npc.npc_id, decision.reasoning, decision.action, decision.mood)
            if npc.notable_event:
                await ingest.add_event(npc.npc_id, "escalation", npc.notable_payload)
            npc.mood = decision.mood
            npc.last_action = decision.action
            npc.last_tick_ts = time.time()
            npc.notable_event = False

        try:
            while duration_seconds is None or (time.time() - start) < duration_seconds:
                now = time.time()
                _apply_timeline(cast_by_id, now - start, fired_events)

                states = [
                    NPCState(n.npc_id, n.tier, n.last_tick_ts, n.notable_event)
                    for n in cast
                ]
                plans = plan_ticks(states, now)
                if plans:
                    await asyncio.gather(*(run_one(p) for p in plans))

                await asyncio.sleep(LOOP_RESOLUTION_SECONDS)
        finally:
            flush_task.cancel()
            try:
                await flush_task
            except asyncio.CancelledError:
                pass
            await ingest.flush(mcp)


if __name__ == "__main__":
    asyncio.run(run_simulation(duration_seconds=60))

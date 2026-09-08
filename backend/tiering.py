"""Deterministic tick scheduler — decides which NPCs reason this frame.

No model calls here (see Compliance Notes in optimizedcontext.md): purely
interval math plus a notable-event escalation rule, so tiering itself never
counts against the hackathon's AI-usage restriction.
"""

from dataclasses import dataclass

PRINCIPAL_INTERVAL_SECONDS = 12.0
BACKGROUND_INTERVAL_SECONDS = 30.0


@dataclass
class NPCState:
    npc_id: str
    tier: str  # "principal" | "background"
    last_tick_ts: float | None  # epoch seconds; None if never ticked
    notable_event: bool = False


@dataclass
class ScheduledTick:
    npc_id: str
    run_tier: str  # tier to actually reason as this tick (may be escalated)
    reason: str  # "interval_due" | "notable_event_escalation"


def _interval_for(tier: str) -> float:
    return PRINCIPAL_INTERVAL_SECONDS if tier == "principal" else BACKGROUND_INTERVAL_SECONDS


def plan_ticks(states: list[NPCState], now: float) -> list[ScheduledTick]:
    """Return the NPCs due to tick this frame, in a stable, explainable order.

    A background NPC with notable_event set escalates to a principal-style
    (richer) reasoning pass for this one tick, regardless of its interval.
    """
    plans = []
    for state in states:
        if state.notable_event:
            plans.append(ScheduledTick(state.npc_id, "principal", "notable_event_escalation"))
            continue
        elapsed = float("inf") if state.last_tick_ts is None else now - state.last_tick_ts
        if elapsed >= _interval_for(state.tier):
            plans.append(ScheduledTick(state.npc_id, state.tier, "interval_due"))
    return plans

"""Detects when an NPC's own action is dramatic enough for nearby NPCs to
notice, and marks those neighbors as having something to react to on their
next tick.

Nothing here decides *what* a neighbor does about it — that's still their
own Gemini call, reading the source NPC's real action in their own context
on their own next tick (see NPC.current_context in simulation.py). This
module only decides *whether* an action is loud/visible enough to be
noticed (a deterministic keyword check on the model's own generated text,
not a model call itself) and *who* is close enough to notice it (via
proximity.py). The reaction — and whether it in turn triggers anyone
else — is never scripted; it emerges from each NPC's own reasoning.
"""

from backend.proximity import neighbors_of

# Prevents A/B ping-pong: once a neighbor has been chain-triggered, it's not
# eligible again for this long, so one seed produces a ripple that spreads
# outward and settles, not an endless back-and-forth between two NPCs.
COOLDOWN_SECONDS = 25.0
MAX_PROPAGATIONS_PER_SIGNAL = 6

_FLIGHT = (
    "flee", "flees", "fled", "fleeing", "run", "runs", "ran", "running",
    "bolt", "bolts", "dash", "dashes", "duck", "ducks", "hide", "hides", "cower",
)
_ALARM = (
    "shout", "shouts", "shouted", "scream", "screams", "screamed", "yell",
    "yells", "gasp", "gasps", "cry out", "cries out", "alarm", "panic",
)
_DANGER = (
    "gun", "knife", "weapon", "draws a", "pulls a", "collapse", "collapses",
    "faint", "faints", "grabs", "lunge", "lunges", "shove", "shoves", "punch",
)
_PANIC_MOODS = {"panicked", "terrified", "alarmed", "frantic", "horrified"}


def detect_notable_signal(action: str, reasoning: str, mood: str) -> bool:
    """True if this decision is dramatic enough for nearby NPCs to plausibly
    notice. Pure keyword matching on text the model already generated —
    deciding what counts as noticeable never itself costs a model call."""
    text = f"{action} {reasoning}".lower()
    if any(kw in text for kw in (*_FLIGHT, *_ALARM, *_DANGER)):
        return True
    return mood.lower() in _PANIC_MOODS


def propagate(cast_by_id: dict, source_id: str, source_name: str, action: str, now: float) -> list[str]:
    """Mark eligible neighbors of source_id as having a notable event to
    react to on their next tick. Returns the npc_ids actually triggered."""
    triggered = []
    for neighbor_id in neighbors_of(source_id):
        if len(triggered) >= MAX_PROPAGATIONS_PER_SIGNAL:
            break
        neighbor = cast_by_id.get(neighbor_id)
        if neighbor is None or now < neighbor.chain_cooldown_until:
            continue
        neighbor.notable_event = True
        neighbor.notable_payload = f"notice {source_name} {action.rstrip('.')}"
        neighbor.notable_event_type = "chain_reaction"
        neighbor.notable_source_id = source_id
        neighbor.chain_cooldown_until = now + COOLDOWN_SECONDS
        triggered.append(neighbor_id)
    return triggered

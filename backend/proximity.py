"""Who-can-plausibly-notice-whom graph for chain reactions between NPCs.

This graph only encodes physical plausibility (who's close enough to see or
hear whom in the manor bar scene) — it is not a script of what happens.
What actually ripples through it — whether a neighbor reacts at all, and
how — is decided by that neighbor's own Gemini call reading the source
NPC's real action in its context on its next tick. Nothing here dictates
the content of any reaction, only who is close enough to plausibly have one.
"""

PROXIMITY: dict[str, set[str]] = {
    "detective": {"suspect", "guest-1", "guest-2", "guest-4", "bartender"},
    "suspect": {"detective", "guest-1", "guest-2", "guest-4"},
    "bartender": {"detective", "suspect", "waiter-1", "waiter-2", "guest-1"},
    "waiter-1": {"bartender", "guest-3", "guest-4"},
    "waiter-2": {"bartender", "guest-2", "security"},
    "guest-1": {"detective", "suspect", "bartender", "guest-2"},
    "guest-2": {"detective", "suspect", "guest-1", "guest-3", "waiter-2"},
    "guest-3": {"guest-2", "guest-4", "waiter-1", "security", "coatcheck"},
    "guest-4": {"detective", "suspect", "guest-3", "musician", "waiter-1"},
    "musician": {"guest-4", "photographer"},
    "security": {"guest-3", "waiter-2", "photographer", "coatcheck"},
    "photographer": {"musician", "security"},
    "coatcheck": {"security", "guest-3", "valet"},
    "valet": {"coatcheck"},
}


def neighbors_of(npc_id: str) -> set[str]:
    return PROXIMITY.get(npc_id, set())

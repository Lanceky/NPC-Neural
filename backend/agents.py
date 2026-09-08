"""Google ADK reasoning agents for NPC ticks.

Two tiers, per the tiering pitch: principal characters get a richer prompt,
background characters get a terse one. Both return a small structured
Decision — no conversation history is kept between ticks, so background NPCs
stay cheap regardless of how many ticks have run.
"""

import asyncio
import os
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel

from backend import quota_state

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5
ATTEMPT_TIMEOUT_SECONDS = 12

APP_NAME = "npc-neural"
PRINCIPAL_MODEL = os.environ.get("GEMINI_MODEL_PRINCIPAL", "gemini-3.5-flash")
BACKGROUND_MODEL = os.environ.get("GEMINI_MODEL_BACKGROUND", "gemini-flash-lite-latest")


class Decision(BaseModel):
    reasoning: str
    action: str
    mood: str


PRINCIPAL_INSTRUCTION = (
    "You are a principal character in a movie scene, with a distinct "
    "personality and detailed context. Given your current context and goal, "
    "decide your next beat: your internal reasoning, the concrete action you "
    "take, and your current mood. Be specific and true to character."
)

BACKGROUND_INSTRUCTION = (
    "You are a background character (an extra) in a movie scene. You get "
    "only a short context and goal. Decide your next action quickly: brief "
    "reasoning, a concrete simple action, and your mood. Keep it plausible "
    "but low-key — you are not the focus of the scene."
)


def _build_agent(tier: str) -> LlmAgent:
    instruction = PRINCIPAL_INSTRUCTION if tier == "principal" else BACKGROUND_INSTRUCTION
    model = PRINCIPAL_MODEL if tier == "principal" else BACKGROUND_MODEL
    return LlmAgent(
        model=model,
        name=f"{tier}_npc",
        instruction=instruction,
        output_schema=Decision,
        output_key="decision",
    )


_runners: dict[str, InMemoryRunner] = {}


def _get_runner(tier: str) -> InMemoryRunner:
    if tier not in _runners:
        _runners[tier] = InMemoryRunner(agent=_build_agent(tier), app_name=APP_NAME)
    return _runners[tier]


async def _consume_run(runner, npc_id: str, session_id: str, message) -> str | None:
    final_text = None
    async for event in runner.run_async(
        user_id=npc_id, session_id=session_id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text
    return final_text


async def run_tick(npc_id: str, tier: str, context_snippet: str, goal: str) -> Decision:
    message = types.Content(
        role="user",
        parts=[types.Part(text=f"Context: {context_snippet}\nGoal: {goal}")],
    )

    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        # The principal model has a very low free-tier daily quota. Once it's
        # exhausted (for the rest of this process), degrade principal ticks
        # to the background model rather than stalling the whole simulation.
        effective_tier = "background" if (tier == "principal" and quota_state.principal_quota_exhausted) else tier
        runner = _get_runner(effective_tier)
        session_id = f"{npc_id}-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(
            app_name=APP_NAME, user_id=npc_id, session_id=session_id
        )
        try:
            final_text = await asyncio.wait_for(
                _consume_run(runner, npc_id, session_id, message),
                timeout=ATTEMPT_TIMEOUT_SECONDS,
            )
            if final_text is None:
                raise RuntimeError(f"no final response for npc {npc_id}")
            return Decision.model_validate_json(final_text)
        except Exception as exc:  # transient 503s, timeouts, quota etc. — retry with backoff
            last_error = exc
            if effective_tier == "principal" and "RESOURCE_EXHAUSTED" in str(exc):
                quota_state.principal_quota_exhausted = True
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_error

"""Read-path agent: answers natural-language questions about NPC behavior by
querying live ClickHouse data through the official mcp-clickhouse MCP server.

ADK's built-in McpToolset can't be used here: the current mcp-clickhouse
release depends on mcp>=2.0, while google-adk's McpToolset depends on
mcp<2 (verified directly — installing either version breaks the other).
So this wraps the same mcp_client.PersistentClickHouseMCP session as plain
ADK function tools. The agent still calls the real mcp-clickhouse server
over the MCP protocol on every question; it just isn't ADK's McpToolset
wrapper class.
"""

import asyncio
import json
import os
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from backend import quota_state, rate_limiter
from backend.mcp_client import PersistentClickHouseMCP

APP_NAME = "npc-neural-inspect"
PRINCIPAL_MODEL = os.environ.get("GEMINI_MODEL_PRINCIPAL", "gemini-3.5-flash")
BACKGROUND_MODEL = os.environ.get("GEMINI_MODEL_BACKGROUND", "gemini-flash-lite-latest")
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0
ATTEMPT_TIMEOUT_SECONDS = 12

INSPECT_INSTRUCTION = (
    "You are the Director's Assistant. You answer questions about what NPCs "
    "in the scene are doing and why, using the live ClickHouse tables: "
    "npcs, context_ticks, decisions, events. Always call list_tables and/or "
    "run_query to check real rows before answering a factual question — "
    "never guess or invent data. Cite the actual reasoning/action/mood or "
    "event you found. If nothing matches, say so plainly."
)


async def inspect(question: str, mcp: PersistentClickHouseMCP | None = None) -> str:
    """Answer one natural-language question about NPC behavior, backed by a
    live mcp-clickhouse session. Pass an existing session (e.g. from a
    long-running server) to skip spawning a new one for every question."""
    if mcp is not None:
        return await _inspect_with_session(question, mcp)
    async with PersistentClickHouseMCP(allow_write=False) as owned_mcp:
        return await _inspect_with_session(question, owned_mcp)


async def _consume_run(runner, session_id: str, message) -> str | None:
    final_text = None
    async for event in runner.run_async(
        user_id="director", session_id=session_id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text
    return final_text


async def _inspect_with_session(question: str, mcp: PersistentClickHouseMCP) -> str:
    async def run_query(query: str) -> str:
        """Run a read-only SQL query against ClickHouse and return rows as JSON text.

        Args:
            query: A ClickHouse SQL SELECT statement.
        """
        rows = await mcp.run_query(query)
        return json.dumps(rows, default=str)

    async def list_tables(database: str = "default") -> str:
        """List tables and their columns in a ClickHouse database.

        Args:
            database: The database name to list tables from.
        """
        result = await mcp.session.call_tool("list_tables", {"database": database})
        for block in result.content:
            if getattr(block, "type", None) == "text":
                return block.text
        return "[]"

    message = types.Content(role="user", parts=[types.Part(text=question)])

    for attempt in range(RETRY_ATTEMPTS):
        model = BACKGROUND_MODEL if quota_state.principal_quota_exhausted else PRINCIPAL_MODEL
        agent = LlmAgent(
            model=model,
            name="inspect_agent",
            instruction=INSPECT_INSTRUCTION,
            tools=[run_query, list_tables],
        )
        if model == BACKGROUND_MODEL:
            await rate_limiter.lite_model_limiter.acquire()
        runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
        session_id = f"inspect-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(
            app_name=APP_NAME, user_id="director", session_id=session_id
        )
        try:
            final_text = await asyncio.wait_for(
                _consume_run(runner, session_id, message),
                timeout=ATTEMPT_TIMEOUT_SECONDS,
            )
            return final_text or "(no response)"
        except Exception as exc:  # transient 503s, timeouts, quota etc. — retry with backoff
            if model == PRINCIPAL_MODEL and "RESOURCE_EXHAUSTED" in str(exc):
                quota_state.principal_quota_exhausted = True
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    return (
        "The scene's AI is temporarily rate-limited — please try again in "
        "a few seconds."
    )

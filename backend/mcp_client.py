"""Thin wrapper around the official mcp SDK for talking to mcp-clickhouse.

Every ClickHouse read or write in this project goes through this module, which
spawns the official mcp-clickhouse server over stdio and calls its tools
(run_query, list_tables) — never a bare ClickHouse driver.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _clickhouse_env(allow_write: bool) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()}
    env["CLICKHOUSE_ALLOW_WRITE_ACCESS"] = "true" if allow_write else "false"
    return env


@asynccontextmanager
async def clickhouse_session(allow_write: bool = False):
    """Yield a live ClientSession connected to a freshly spawned mcp-clickhouse."""
    params = StdioServerParameters(
        command="mcp-clickhouse",
        args=[],
        env=_clickhouse_env(allow_write),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _first_text(result) -> str:
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise RuntimeError(f"mcp-clickhouse returned no text content: {result}")


async def run_query(query: str, allow_write: bool = False):
    """Run one SQL statement through mcp-clickhouse's run_query tool.

    Returns the parsed JSON result (list of row dicts for SELECT-like queries).
    """
    async with clickhouse_session(allow_write=allow_write) as session:
        result = await session.call_tool("run_query", {"query": query})
        if result.is_error:
            raise RuntimeError(f"run_query failed: {_first_text(result)}")
        return json.loads(_first_text(result))


async def list_tables(database: str):
    async with clickhouse_session(allow_write=False) as session:
        result = await session.call_tool("list_tables", {"database": database})
        if result.is_error:
            raise RuntimeError(f"list_tables failed: {_first_text(result)}")
        return json.loads(_first_text(result))


class PersistentClickHouseMCP:
    """Keeps one mcp-clickhouse subprocess/session open across many calls.

    Spawning a fresh subprocess per query is too slow for frequent ingestion
    writes, so this holds a single session open for the caller's lifetime.
    """

    def __init__(self, allow_write: bool = False):
        self._allow_write = allow_write
        self._cm = None
        self.session: ClientSession | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "PersistentClickHouseMCP":
        self._cm = clickhouse_session(allow_write=self._allow_write)
        self.session = await self._cm.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        await self._cm.__aexit__(*exc_info)

    async def run_query(self, query: str):
        async with self._lock:
            result = await self.session.call_tool("run_query", {"query": query})
            if result.is_error:
                raise RuntimeError(f"run_query failed: {_first_text(result)}")
            return json.loads(_first_text(result))

"""FastAPI app: serves the frontend and exposes live scene state.

Every read here goes through the same mcp-clickhouse session (via
mcp_client.PersistentClickHouseMCP), and the simulation loop runs as a
background task for the lifetime of the server, so the scene is live for
as long as the app is running.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.inspect_agent import inspect
from backend.mcp_client import PersistentClickHouseMCP
from backend.proximity import PROXIMITY
from backend.scale_sim import ScaleSimulation
from backend.simulation import run_simulation

# The same static adjacency graph chain_reactions.propagate() reads to decide
# who can notice whom, flattened into an edge list so the frontend draws the
# real influence graph instead of a decorative recreation of it.
PROXIMITY_EDGES = sorted({tuple(sorted((a, b))) for a, neighbors in PROXIMITY.items() for b in neighbors})

LATEST_STATE_QUERY = """
SELECT n.npc_id AS npc_id, n.name, n.tier,
       d.mood, d.action, d.reasoning, d.last_ts,
       c.goal
FROM npcs n
LEFT JOIN (
    SELECT npc_id,
           argMax(mood, ts) AS mood,
           argMax(action, ts) AS action,
           argMax(reasoning, ts) AS reasoning,
           max(ts) AS last_ts
    FROM decisions
    GROUP BY npc_id
) d ON n.npc_id = d.npc_id
LEFT JOIN (
    SELECT npc_id, argMax(goal, ts) AS goal
    FROM context_ticks
    GROUP BY npc_id
) c ON n.npc_id = c.npc_id
WHERE n.npc_id NOT LIKE 'synth-%'
ORDER BY n.npc_id
"""

CHAIN_LOG_QUERY = """
SELECT npc_id, ts, event_type, payload
FROM events
WHERE event_type IN ('chain_reaction_source', 'goal_change', 'scripted_event')
ORDER BY ts DESC
LIMIT 30
"""

CONSOLE_SERVER_QUERY = """
SELECT version() AS server_version,
       currentDatabase() AS database,
       uptime() AS uptime_seconds,
       timezone() AS server_timezone
"""

CONSOLE_TABLES_QUERY = """
SELECT name, engine, sorting_key, total_rows, total_bytes
FROM system.tables
WHERE database = currentDatabase()
ORDER BY name
"""

CONSOLE_COLUMNS_QUERY = """
SELECT table, name, type
FROM system.columns
WHERE database = currentDatabase()
ORDER BY table, position
"""

CONSOLE_EVENTS_QUERY = """
SELECT event_type, count() AS n
FROM events
GROUP BY event_type
ORDER BY n DESC
"""

CONSOLE_SAMPLE_QUERY = """
SELECT d.npc_id AS npc_id, n.name AS name, d.ts AS ts, d.mood AS mood, d.action AS action
FROM decisions d
INNER JOIN npcs n ON d.npc_id = n.npc_id
WHERE d.npc_id NOT LIKE 'synth-%'
ORDER BY d.ts DESC
LIMIT 8
"""


def _as_dicts(result) -> list[dict]:
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["rows"]]


def _mask_host(host: str) -> str:
    """Show enough of the ClickHouse Cloud endpoint to prove which region and
    provider it lives on, without publishing the full service address."""
    if not host:
        return "(not set)"
    head, _, rest = host.partition(".")
    if not rest:
        return head[:3] + "…" if len(head) > 3 else head
    return f"{head[:3]}….{rest}" if len(head) > 3 else f"….{rest}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    sim_task = asyncio.create_task(run_simulation())
    async with PersistentClickHouseMCP(allow_write=False) as mcp, \
            PersistentClickHouseMCP(allow_write=True) as scale_mcp:
        app.state.mcp = mcp
        app.state.scale_sim = ScaleSimulation(scale_mcp)
        yield
        await app.state.scale_sim.stop()
    sim_task.cancel()
    try:
        await sim_task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


@app.get("/api/npcs")
async def get_npcs():
    result = await app.state.mcp.run_query(LATEST_STATE_QUERY)
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["rows"]]


class InspectRequest(BaseModel):
    question: str


@app.post("/api/inspect")
async def post_inspect(req: InspectRequest):
    answer = await inspect(req.question, mcp=app.state.mcp)
    return {"answer": answer}


class ScaleRequest(BaseModel):
    count: int


@app.post("/api/scale")
async def post_scale(req: ScaleRequest):
    """Set how many synthetic background NPCs are live right now (0-500)
    and return fresh stats, including how long the ClickHouse writes took."""
    return await app.state.scale_sim.set_count(req.count)


@app.get("/api/scale")
async def get_scale():
    """Poll the current scale-test aggregate stats (mood distribution, row
    counts, live query latency) — cheap even at 500 NPCs since ClickHouse
    only ever returns a small aggregate summary, not per-NPC rows."""
    return await app.state.scale_sim.stats()


@app.get("/api/proximity")
async def get_proximity():
    """The static who-can-notice-whom graph, as edges, so the frontend can
    draw the real influence network instead of a decorative recreation."""
    return {"edges": [list(e) for e in PROXIMITY_EDGES]}


@app.get("/api/chain-log")
async def get_chain_log():
    """Recent emergent chain-reaction events: an NPC's dramatic action
    rippling to nearby NPCs, and any goals that changed as a result — all
    decided live by each NPC's own Gemini call, never scripted here."""
    result = await app.state.mcp.run_query(CHAIN_LOG_QUERY)
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["rows"]]


@app.get("/api/console")
async def get_console():
    """Everything a judge needs to confirm the ClickHouse integration is real:
    the live connection settings, the mcp-clickhouse tools every query is
    routed through, the deployed schema with live row counts, and a sample of
    the rows being written right now. Every figure below is read at request
    time through the same MCP session the scene itself uses."""
    started = time.perf_counter()
    server = _as_dicts(await app.state.mcp.run_query(CONSOLE_SERVER_QUERY))
    tables = _as_dicts(await app.state.mcp.run_query(CONSOLE_TABLES_QUERY))
    columns = _as_dicts(await app.state.mcp.run_query(CONSOLE_COLUMNS_QUERY))
    events = _as_dicts(await app.state.mcp.run_query(CONSOLE_EVENTS_QUERY))
    sample = _as_dicts(await app.state.mcp.run_query(CONSOLE_SAMPLE_QUERY))
    tools = await app.state.mcp.list_tools()
    query_ms = round((time.perf_counter() - started) * 1000, 1)

    by_table: dict[str, list[dict]] = {}
    for col in columns:
        by_table.setdefault(col["table"], []).append({"name": col["name"], "type": col["type"]})
    for table in tables:
        table["columns"] = by_table.get(table["name"], [])

    return {
        "clickhouse": {
            "host": _mask_host(os.environ.get("CLICKHOUSE_HOST", "")),
            "port": os.environ.get("CLICKHOUSE_PORT", ""),
            "user": os.environ.get("CLICKHOUSE_USER", ""),
            "secure": os.environ.get("CLICKHOUSE_SECURE", ""),
            "verify_certs": os.environ.get("CLICKHOUSE_VERIFY", ""),
            "connect_timeout_s": os.environ.get("CLICKHOUSE_CONNECT_TIMEOUT", ""),
            "credential_configured": bool(os.environ.get("CLICKHOUSE_PASSWORD")),
            **(server[0] if server else {}),
        },
        "mcp": {
            "server": "mcp-clickhouse",
            "transport": "stdio",
            "sessions": [
                {"name": "scene reads", "write_access": False},
                {"name": "scale-test writes", "write_access": True},
            ],
            "tools": tools,
        },
        "gemini": {
            "principal_model": os.environ.get("GEMINI_MODEL_PRINCIPAL", ""),
            "background_model": os.environ.get("GEMINI_MODEL_BACKGROUND", ""),
            "use_vertex_ai": os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", ""),
            "credential_configured": bool(os.environ.get("GEMINI_API_KEY")),
        },
        "tables": tables,
        "event_types": events,
        "recent_decisions": sample,
        "query_ms": query_ms,
    }


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

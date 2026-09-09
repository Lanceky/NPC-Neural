"""FastAPI app: serves the frontend and exposes live scene state.

Every read here goes through the same mcp-clickhouse session (via
mcp_client.PersistentClickHouseMCP), and the simulation loop runs as a
background task for the lifetime of the server, so the scene is live for
as long as the app is running.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.inspect_agent import inspect
from backend.mcp_client import PersistentClickHouseMCP
from backend.scale_sim import ScaleSimulation
from backend.simulation import run_simulation

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


@app.get("/api/chain-log")
async def get_chain_log():
    """Recent emergent chain-reaction events: an NPC's dramatic action
    rippling to nearby NPCs, and any goals that changed as a result — all
    decided live by each NPC's own Gemini call, never scripted here."""
    result = await app.state.mcp.run_query(CHAIN_LOG_QUERY)
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["rows"]]


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

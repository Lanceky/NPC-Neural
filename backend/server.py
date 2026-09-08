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
from backend.simulation import run_simulation

LATEST_STATE_QUERY = """
SELECT n.npc_id, n.name, n.tier,
       argMax(d.mood, d.ts) AS mood,
       argMax(d.action, d.ts) AS action,
       argMax(d.reasoning, d.ts) AS reasoning,
       max(d.ts) AS last_ts
FROM npcs n
LEFT JOIN decisions d ON n.npc_id = d.npc_id
GROUP BY n.npc_id, n.name, n.tier
ORDER BY n.npc_id
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    sim_task = asyncio.create_task(run_simulation())
    async with PersistentClickHouseMCP(allow_write=False) as mcp:
        app.state.mcp = mcp
        yield
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


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

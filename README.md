# NPC-Neural

Built for **Agentic Cinema: The Blockbuster Hackathon** (Google Cloud), submitted
to the **ClickHouse** partner track.

**Live demo:** https://scanners-reunion-novel-robots.trycloudflare.com
(a no-signup `cloudflared` quick tunnel — see [Exposing a public
URL](#exposing-a-public-url); if it's ever offline, run it yourself in a
couple of commands from the same section).

A live simulation of a movie scene where every character — from the two leads
down to the bartender and valet — is an independent Gemini agent deciding its
own next beat in real time. Principal characters get rich, frequent reasoning;
background extras get cheap, infrequent reasoning that escalates automatically
when something notable happens near them. Every tick's context, decision, and
event is written to ClickHouse, and a live "Director's Assistant" agent can
answer natural-language questions about any character by querying that data on
demand — proving the reasoning is real, not scripted.

## Why this exists

Today, every background character in a game or virtual production is either
hand-scripted or idle filler — nobody can afford to write bespoke logic (or
prompts) for 50 extras. This project shows the alternative: a director scripts
the 2-3 leads in detail, and everyone else in the room behaves believably on
their own, at a fraction of the cost, with full observability into *why* any
one of them did what they did.

## Architecture

```
 tiering.py (deterministic scheduler)
        |  decides who ticks this frame, no AI involved
        v
 agents.py (Google ADK LlmAgents, Gemini)
        |  principal tier: gemini-3.5-flash, rich context
        |  background tier: gemini-flash-lite-latest, terse context
        v
 ingest.py --------------> mcp-clickhouse (official MCP server) --> ClickHouse Cloud
                                     ^
 inspect_agent.py (Gemini + MCP tools) ---+
        |  answers "what is X doing and why?" via live run_query/list_tables
        v
 server.py (FastAPI) --> frontend/ (click-to-inspect scene view)
```

- **`backend/tiering.py`** — plain interval math + a notable-event escalation
  rule. No model calls here by design, so scheduling never counts against the
  hackathon's AI-usage rules.
- **`backend/agents.py`** — the actual reasoning tick, built on **Google ADK**
  (`LlmAgent` + `InMemoryRunner`, from `google-adk`/`google-genai`). Returns a
  structured `Decision` (reasoning, action, mood).
- **`backend/mcp_client.py`** / **`backend/ingest.py`** — every ClickHouse read
  or write goes through the official **`mcp-clickhouse`** MCP server, spawned
  as a subprocess and driven entirely over the MCP protocol (`ClientSession.
  call_tool("run_query"/"list_tables")`) — never a bare ClickHouse driver.
- **`backend/inspect_agent.py`** — a second Gemini agent exposing `run_query`/
  `list_tables` as plain ADK function-tools around the same MCP session (see
  *Notes on ADK's McpToolset* below), so a judge can ask "why did the bartender
  keep pouring drinks?" and get an answer grounded in live rows, not a guess.
- **`backend/simulation.py`** — the run loop tying scheduler → agents →
  ingestion together for a 14-character noir confrontation scene (2 leads, 12
  background extras).
- **`backend/server.py`** + **`frontend/`** — a FastAPI app that runs the
  simulation as a background task and serves a small web scene: click any
  character to see their live state, or ask the Director's Assistant a
  question in plain English.

### Notes on ADK's `McpToolset`

The installed `mcp-clickhouse` release requires `mcp>=2.0`, while `google-adk`'s
built-in `McpToolset` requires `mcp<2` — a verified, unresolvable version
conflict at the time of building. `inspect_agent.py` works around this by
wrapping the same `mcp` `ClientSession` as plain ADK function tools instead of
`McpToolset`. The tool calls still go through the real `mcp-clickhouse` server
over the MCP protocol either way — this is a wrapper-class swap, not a
compliance shortcut.

### Free-tier quota handling

The Gemini free tier caps `gemini-3.5-flash` at **20 requests/day** and
`gemini-flash-lite-latest` at **15 requests/minute**, per project — both
confirmed from live `429 RESOURCE_EXHAUSTED` responses. Three mitigations are
built in so a quota wall degrades the demo instead of crashing it:

- **Graceful model fallback** (`backend/quota_state.py`) — once the daily
  principal quota is exhausted, principal ticks transparently drop to the
  background model instead of failing for the rest of the process.
- **Staggered tick starts** (`backend/simulation.py`) — each tier's first tick
  is spread evenly across its interval instead of firing every character in
  the same instant, avoiding a thundering-herd burst against the per-minute cap.
- **A shared token-bucket limiter** (`backend/rate_limiter.py`) — throttles
  every lite-model call (background ticks, degraded principal ticks, and
  on-demand inspect queries) to stay under the per-minute cap proactively,
  instead of only reacting to 429s after the fact.

This uses the plain Gemini Developer API key (`google-genai`,
`GOOGLE_GENAI_USE_VERTEXAI=false`) rather than Vertex AI, so running this
project needs only a free API key from
[Google AI Studio](https://aistudio.google.com/apikey) — no GCP billing
account required.

## Running it

### 1. Prerequisites

- Python 3.12+
- A ClickHouse Cloud service (or any ClickHouse reachable over HTTPS on 8443)
- A free Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### 2. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# fill in CLICKHOUSE_HOST / CLICKHOUSE_PASSWORD and GEMINI_API_KEY
```

### 4. Create the schema (once)

```bash
python -m backend.apply_schema
```

### 5. Run

```bash
uvicorn backend.server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` — the scene populates within a few seconds as
background ticks start landing in ClickHouse. Click any character for their
live state, or ask the Director's Assistant a question at the bottom of the
page.

## Running with Docker

```bash
docker build -t npc-neural .
docker run --env-file .env -p 8000:8000 npc-neural
```

## Exposing a public URL

For a quick, no-signup public URL (e.g. for live judging), run the server as
above, then in a second terminal:

```bash
cloudflared tunnel --url http://localhost:8000
```

This prints a public `https://*.trycloudflare.com` URL that proxies straight
to your local server — no account or billing setup required. For a persistent
deployment, the included `Dockerfile` runs as-is on Cloud Run, Render,
Railway, Fly.io, or any container host.

## Tech stack

- **Google ADK** (`google-adk`) + **`google-genai`** — agent framework and
  Gemini client
- **ClickHouse Cloud** + **`mcp-clickhouse`** (official MCP server) — sole
  data store and integration point
- **FastAPI** + vanilla JS/CSS — demo server and frontend
- **Python 3.12**, `asyncio` throughout

## License

MIT — see [LICENSE](LICENSE).

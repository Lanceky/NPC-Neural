const body = document.getElementById("console-body");

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function num(n) {
  return Number(n || 0).toLocaleString("en-US");
}

function bytes(n) {
  let v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let i = 0;
  v /= 1024;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

function truncate(text, max) {
  const s = String(text ?? "");
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function kv(pairs) {
  return `<div class="kv">${pairs
    .filter(([, v]) => v !== "" && v !== null && v !== undefined)
    .map(([k, v]) => `<div><span>${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></div>`)
    .join("")}</div>`;
}

function card(title, pill, inner) {
  const badge = pill ? `<span class="pill${pill.warn ? " warn" : ""}">${escapeHtml(pill.text)}</span>` : "";
  return `<div class="card"><h2>${escapeHtml(title)}${badge}</h2>${inner}</div>`;
}

function render(data) {
  const ch = data.clickhouse || {};
  const mcp = data.mcp || {};
  const gem = data.gemini || {};

  const connection = card("ClickHouse Cloud", { text: `v${ch.server_version}` }, kv([
    ["Host", ch.host],
    ["Port", ch.port],
    ["Database", ch.database],
    ["User", ch.user],
    ["TLS", ch.secure === "true" ? "on, certs verified" : ch.secure],
    ["Password", ch.credential_configured ? "configured" : "not set"],
  ]));

  const tools = `<div class="tags">${(mcp.tools || [])
    .map((t) => `<code>${escapeHtml(t.name)}</code>`).join("")}</div>`;
  const access = card("MCP access path", { text: "stdio" }, kv([
    ["Server", mcp.server],
    ["Scene reads", "write access off"],
    ["Scale test", "write access on"],
  ]) + tools);

  const gemini = card("Gemini", { text: gem.use_vertex_ai === "true" ? "Vertex AI" : "Developer API" }, kv([
    ["Principal tier", gem.principal_model],
    ["Background tier", gem.background_model],
    ["API key", gem.credential_configured ? "configured" : "not set"],
  ]));

  const totalRows = (data.tables || []).reduce((a, t) => a + Number(t.total_rows || 0), 0);
  const tables = card("Tables", { text: `${num(totalRows)} rows` },
    `<table class="grid"><tr><th>Table</th><th>Engine</th><th>Order by</th>
      <th>Rows</th><th>Size</th><th>Columns</th></tr>${
      (data.tables || []).map((t) => `<tr>
        <td>${escapeHtml(t.name)}</td>
        <td>${escapeHtml(t.engine)}</td>
        <td>${escapeHtml(t.sorting_key || "—")}</td>
        <td class="num">${num(t.total_rows)}</td>
        <td class="num">${bytes(t.total_bytes)}</td>
        <td>${escapeHtml((t.columns || []).map((c) => c.name).join(", "))}</td>
      </tr>`).join("")
    }</table>`);

  const eventTags = `<div class="tags">${(data.event_types || [])
    .map((e) => `<code>${escapeHtml(e.event_type)} ${num(e.n)}</code>`).join("")}</div>`;
  const activity = card("Live activity", { text: "streaming" },
    eventTags + `<table class="grid" style="margin-top:0.8rem">
      <tr><th>NPC</th><th>Time</th><th>Mood</th><th>Action</th></tr>${
      (data.recent_decisions || []).slice(0, 6).map((r) => `<tr>
        <td>${escapeHtml(r.name || r.npc_id)}</td>
        <td>${escapeHtml(String(r.ts).slice(11, 19))}</td>
        <td>${escapeHtml(truncate(r.mood, 26))}</td>
        <td>${escapeHtml(truncate(r.action, 95))}</td>
      </tr>`).join("")
    }</table>`);

  body.innerHTML = connection + access + gemini + tables + activity +
    `<p class="console-foot">Read live via mcp-clickhouse <code>run_query</code> in
      ${escapeHtml(data.query_ms)}ms. Credentials stay on the server.</p>`;
}

async function load() {
  try {
    const res = await fetch("/api/console");
    if (!res.ok) throw new Error(res.status);
    render(await res.json());
  } catch (err) {
    console.error("console load failed", err);
    body.textContent = "Could not reach ClickHouse through the MCP server.";
  }
}

load();

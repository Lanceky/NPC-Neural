// Synaptic cascade view: every NPC is a soft breathing point of light on a
// canvas. Faint lines are the real proximity graph chain_reactions.py uses
// to decide who can notice whom. When a chain reaction fires, light travels
// node-to-node along those real edges at a visible speed -- nothing here
// decides the reaction itself, only how to show it.

const LAYOUT = {
  detective: [40, 55],
  suspect: [60, 55],
  bartender: [10, 30],
  "waiter-1": [30, 78],
  "waiter-2": [72, 22],
  "guest-1": [35, 38],
  "guest-2": [65, 38],
  "guest-3": [85, 62],
  "guest-4": [50, 20],
  musician: [15, 72],
  security: [90, 42],
  photographer: [25, 15],
  valet: [95, 88],
  coatcheck: [6, 88],
};

const IDLE_COLOR = [56, 205, 191];   // cool teal -- resting state
const FLARE_COLOR = [255, 106, 74];  // warm coral -- a chain reaction fired here
const SCRIPT_COLOR = [140, 190, 255]; // cool blue -- an authored beat, not a chain
const GOLD = [212, 175, 55];         // principal accent / goal-change ping
const GLOW_DECAY_MS = 1400;
const GOAL_PING_MS = 700;

const sceneWrap = document.getElementById("scene");
const canvas = document.getElementById("scene-canvas");
const ctx = canvas.getContext("2d");
const scaleLegend = document.getElementById("scale-legend");
const selectedInfo = document.getElementById("selected-info");
const askForm = document.getElementById("ask-form");
const askInput = document.getElementById("ask-input");
const askAnswer = document.getElementById("ask-answer");
const scaleSelect = document.getElementById("scale-select");
const scaleStatus = document.getElementById("scale-status");
const scaleStats = document.getElementById("scale-stats");
const chainLog = document.getElementById("chain-log");

const MOOD_COLORS = {
  neutral: "#7c8ba1", tense: "#c0554a", curious: "#4aa3c0", bored: "#6b6f76",
  alert: "#d4af37", nervous: "#b06fc9", amused: "#5fbf6a", focused: "#e0a63c",
};

let mode = "scene"; // "scene" | "scale"
let selectedId = null;
let latestById = {};
let dpr = Math.max(1, window.devicePixelRatio || 1);

const sceneNodes = new Map(); // npc_id -> node
let edges = [];               // [[aId, bId], ...] real proximity graph
let pulses = [];               // traveling light animations between two nodes
let scaleNodes = [];            // plain array for the scale-test swarm
let scaleLabels = null;         // pre-rendered offscreen canvas of the swarm's labels

// At or below this many synthetic NPCs each dot is labelled with its full
// name; above it there is no room, so initials + number are used instead.
const SCALE_NAME_LIMIT = 100;

// "background extra #7" -> "BE7". Acronym roles like "PA" are kept whole, and
// the trailing number is preserved so every label stays unique.
function initialsFor(name) {
  const text = String(name || "").trim();
  if (!text) return "";
  const num = (text.match(/#\s*(\d+)\s*$/) || [])[1] || "";
  const words = text.replace(/#\s*\d+\s*$/, "").trim().split(/\s+/).filter(Boolean);
  const letters = words
    .map((w) => (w === w.toUpperCase() ? w : w[0].toUpperCase()))
    .join("");
  return (letters || text.slice(0, 2).toUpperCase()) + num;
}

// A stable, always-positive pseudo-random number in [0,1) for a given seed --
// used for deterministic layout jitter so the swarm doesn't reshuffle itself
// on every redraw.
function pseudoRandom(seed) {
  const x = Math.sin(seed) * 43758.5453;
  return x - Math.floor(x);
}

function resizeCanvas() {
  const rect = sceneWrap.getBoundingClientRect();
  canvas.width = Math.max(1, rect.width * dpr);
  canvas.height = Math.max(1, rect.height * dpr);
  canvas.style.width = rect.width + "px";
  canvas.style.height = rect.height + "px";
  layoutSceneNodes();
  layoutScaleNodes();
}
window.addEventListener("resize", resizeCanvas);

function ensureSceneNode(npcId) {
  let n = sceneNodes.get(npcId);
  if (!n) {
    n = { id: npcId, x: 0, y: 0, glowStart: -Infinity, glowColor: FLARE_COLOR,
          goalPingStart: -Infinity, phase: Math.random() * Math.PI * 2 };
    sceneNodes.set(npcId, n);
  }
  return n;
}

function layoutSceneNodes() {
  const rect = sceneWrap.getBoundingClientRect();
  for (const [npcId, pos] of Object.entries(LAYOUT)) {
    const n = ensureSceneNode(npcId);
    n.x = (pos[0] / 100) * rect.width;
    n.y = (pos[1] / 100) * rect.height;
  }
}

// Deterministic shuffle, so the same count always produces the same scatter
// instead of reshuffling itself on every poll or resize.
function seededShuffle(arr, seedBase) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(pseudoRandom((i + 1) * seedBase) * (i + 1));
    const tmp = arr[i];
    arr[i] = arr[j];
    arr[j] = tmp;
  }
  return arr;
}

function layoutScaleNodes() {
  scaleLabels = null;
  const count = scaleNodes.length;
  if (count === 0) return;
  const rect = sceneWrap.getBoundingClientRect();
  const margin = 34;
  // The bottom needs extra room: every dot carries a name underneath it, and
  // the mood legend is pinned to the bottom-left of the same box.
  const marginBottom = 72;
  const w = Math.max(1, rect.width - margin * 2);
  const h = Math.max(1, rect.height - margin - marginBottom);
  // Scatter into randomly chosen cells of an oversized grid, jittered across
  // nearly the whole cell. The spare cells and the full-cell jitter are what
  // break up the rows and columns, so the crowd reads as an organic scatter
  // like the live scene rather than as a grid.
  const cells = Math.ceil(count * 1.7);
  const cols = Math.max(1, Math.round(Math.sqrt(cells * (w / h))));
  const rows = Math.max(1, Math.ceil(cells / cols));
  const cellW = w / cols, cellH = h / rows;
  const r = Math.min(9, Math.max(2.5, Math.min(cellW, cellH) * 0.4));
  const order = seededShuffle([...Array(cols * rows).keys()], 3.7);
  const useInitials = count > SCALE_NAME_LIMIT;
  for (let i = 0; i < count; i++) {
    const cell = order[i % order.length];
    const col = cell % cols, row = Math.floor(cell / cols);
    const jx = (pseudoRandom(i * 12.9898 + 1) - 0.5) * cellW * 0.9;
    const jy = (pseudoRandom(i * 78.233 + 1) - 0.5) * cellH * 0.9;
    const n = scaleNodes[i];
    n.x = margin + col * cellW + cellW / 2 + jx;
    n.y = margin + row * cellH + cellH / 2 + jy;
    n.r = r;
    n.label = useInitials ? initialsFor(n.name) : n.name;
  }
  const fontSize = useInitials
    ? Math.min(9, Math.max(6.5, cellH * 0.3))
    : Math.min(11, Math.max(8, cellH * 0.16));
  buildScaleLabels(rect.width, rect.height, fontSize, cellW * 1.15);
}

// The labels never animate, so they are drawn once into an offscreen canvas
// and blitted in a single call per frame -- 500 fillText calls at 60fps would
// otherwise cost far more than the breathing dots themselves.
function buildScaleLabels(cssW, cssH, fontSize, maxWidth) {
  const layer = document.createElement("canvas");
  layer.width = Math.max(1, Math.round(cssW * dpr));
  layer.height = Math.max(1, Math.round(cssH * dpr));
  const g = layer.getContext("2d");
  g.scale(dpr, dpr);
  g.font = `${fontSize.toFixed(1)}px system-ui, sans-serif`;
  g.textAlign = "center";
  g.textBaseline = "top";
  g.fillStyle = "rgba(196,204,216,0.92)";
  for (const n of scaleNodes) {
    if (!n.label) continue;
    // Nudge labels near the left/right edges inward so a long name is never
    // clipped by the canvas boundary.
    const half = Math.min(maxWidth, g.measureText(n.label).width) / 2;
    const x = Math.min(Math.max(n.x, half + 2), Math.max(half + 2, cssW - half - 2));
    g.fillText(n.label, x, n.y + n.r + 3, maxWidth);
  }
  scaleLabels = layer;
}

function ignite(npcId, now, color) {
  const n = sceneNodes.get(npcId);
  if (!n) return;
  n.glowStart = now;
  n.glowColor = color || FLARE_COLOR;
}

function currentGlow(n, now) {
  const dt = now - n.glowStart;
  if (dt < 0) return 0;
  return Math.max(0, 1 - dt / GLOW_DECAY_MS);
}

function lerpColor(a, b, t) {
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * t)}, ${Math.round(a[1] + (b[1] - a[1]) * t)}, ${Math.round(a[2] + (b[2] - a[2]) * t)})`;
}

function drawScene(now) {
  // Faint idle lines are the real proximity graph; they brighten locally as
  // a traveling pulse passes through that specific edge.
  for (const [a, b] of edges) {
    const na = sceneNodes.get(a), nb = sceneNodes.get(b);
    if (!na || !nb) continue;
    let heat = 0;
    for (const p of pulses) {
      if ((p.a === a && p.b === b) || (p.a === b && p.b === a)) {
        const t = (now - p.start) / p.duration;
        if (t >= 0 && t <= 1) heat = Math.max(heat, 1 - Math.abs(t - 0.5) * 2);
      }
    }
    ctx.beginPath();
    ctx.strokeStyle = heat > 0 ? `rgba(255,138,101,${0.2 + 0.65 * heat})` : "rgba(56,205,191,0.14)";
    ctx.lineWidth = heat > 0 ? 1.4 + 2 * heat : 1;
    ctx.moveTo(na.x, na.y);
    ctx.lineTo(nb.x, nb.y);
    ctx.stroke();
  }

  // Traveling light: a bright point moving along its edge; on arrival it
  // ignites the target node exactly once.
  for (const p of pulses) {
    if (now < p.start) continue;
    const na = sceneNodes.get(p.a), nb = sceneNodes.get(p.b);
    if (!na || !nb) continue;
    const t = Math.min(1, (now - p.start) / p.duration);
    const x = na.x + (nb.x - na.x) * t;
    const y = na.y + (nb.y - na.y) * t;
    ctx.beginPath();
    ctx.shadowColor = "rgba(255,138,101,0.9)";
    ctx.shadowBlur = 10;
    ctx.fillStyle = "rgba(255,205,170,0.95)";
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    if (t >= 1 && !p.arrived) {
      p.arrived = true;
      ignite(p.b, now, p.color || FLARE_COLOR);
    }
  }
  pulses = pulses.filter((p) => now - p.start <= p.duration * 1.05);

  for (const n of sceneNodes.values()) {
    const npc = latestById[n.id];
    const glow = currentGlow(n, now);
    const breathe = Math.sin(now / 1400 + n.phase) * 0.5 + 0.5;
    const isPrincipal = npc && npc.tier === "principal";
    const baseR = (isPrincipal ? 10 : 6.5) + breathe * 1.1;
    const r = baseR + glow * 4;
    const color = glow > 0.02 ? lerpColor(IDLE_COLOR, n.glowColor, glow) : `rgb(${IDLE_COLOR.join(",")})`;

    if (now - n.goalPingStart < GOAL_PING_MS) {
      const pt = (now - n.goalPingStart) / GOAL_PING_MS;
      ctx.beginPath();
      ctx.strokeStyle = `rgba(212,175,55,${1 - pt})`;
      ctx.lineWidth = 2;
      ctx.arc(n.x, n.y, r + pt * 16, 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.shadowColor = glow > 0.05 ? "rgba(255,106,74,0.85)" : "rgba(56,205,191,0.4)";
    ctx.shadowBlur = 6 + glow * 10;
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    if (isPrincipal) {
      ctx.beginPath();
      ctx.strokeStyle = "rgba(212,175,55,0.9)";
      ctx.lineWidth = 1.5;
      ctx.arc(n.x, n.y, r + 2.5, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (n.id === selectedId) {
      ctx.beginPath();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.fillStyle = "#cfd4dc";
    ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText((npc && npc.name) || n.id, n.x, n.y + r + 13);
  }
}

function drawScale(now) {
  for (const n of scaleNodes) {
    const breathe = Math.sin(now / 1400 + n.phase) * 0.5 + 0.5;
    ctx.beginPath();
    ctx.globalAlpha = 0.65 + 0.35 * breathe;
    ctx.fillStyle = n.color;
    ctx.shadowColor = n.color;
    ctx.shadowBlur = 5 + breathe * 5;
    ctx.arc(n.x, n.y, n.r * (0.85 + breathe * 0.3), 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  }
  if (scaleLabels) {
    ctx.drawImage(scaleLabels, 0, 0, scaleLabels.width / dpr, scaleLabels.height / dpr);
  }
}

function draw(now) {
  ctx.save();
  ctx.scale(dpr, dpr);
  const cssW = canvas.width / dpr, cssH = canvas.height / dpr;
  ctx.clearRect(0, 0, cssW, cssH);
  if (mode === "scene") drawScene(now); else drawScale(now);
  ctx.restore();
  requestAnimationFrame(draw);
}

canvas.addEventListener("click", (ev) => {
  if (mode !== "scene") return;
  const rect = canvas.getBoundingClientRect();
  const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
  let closest = null, closestDist = Infinity;
  for (const n of sceneNodes.values()) {
    const d = Math.hypot(n.x - mx, n.y - my);
    if (d < closestDist) { closestDist = d; closest = n; }
  }
  if (closest && closestDist <= 24) selectNpc(closest.id);
});

function selectNpc(npcId) {
  selectedId = npcId;
  renderSelected();
}

function renderSelected() {
  const npc = latestById[selectedId];
  if (!npc) {
    selectedInfo.textContent = "Click an NPC to inspect their latest decision.";
    return;
  }
  selectedInfo.textContent =
    `${npc.name} (${npc.tier})\n\n` +
    `Goal: ${npc.goal || "—"}\n\n` +
    `Mood: ${npc.mood || "—"}\n\n` +
    `Action: ${npc.action || "—"}\n\n` +
    `Reasoning: ${npc.reasoning || "—"}\n\n` +
    `Last update: ${npc.last_ts || "—"}`;
}

async function poll() {
  try {
    const res = await fetch("/api/npcs");
    const npcs = await res.json();
    for (const npc of npcs) {
      if (!LAYOUT[npc.npc_id]) continue;
      latestById[npc.npc_id] = npc;
    }
    if (selectedId) renderSelected();
  } catch (err) {
    console.error("poll failed", err);
  }
}

async function loadProximity() {
  try {
    const res = await fetch("/api/proximity");
    const data = await res.json();
    edges = data.edges || [];
  } catch (err) {
    console.error("proximity load failed", err);
  }
}

// Minimal, safe markdown: escapes HTML first, then only turns **bold** and
// newlines into tags -- the model's answers use just enough markdown for
// this to matter, and nothing more.
function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderMarkdownLite(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

askForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = askInput.value.trim();
  if (!question) return;
  askAnswer.textContent = "Thinking…";
  try {
    const res = await fetch("/api/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    askAnswer.innerHTML = renderMarkdownLite(data.answer);
  } catch (err) {
    askAnswer.textContent = "Error asking the director's assistant.";
  }
});

// Renders the scale-test swarm as breathing dots, one per synthetic NPC,
// each carrying that NPC's own name from the npcs table and coloured by its
// own latest mood -- both read back out of ClickHouse, not invented here.
function renderScale(data) {
  const active = data.active_count || 0;
  mode = active > 0 ? "scale" : "scene";
  scaleLegend.hidden = active === 0;

  if (active === 0) {
    scaleStatus.textContent = "";
    scaleStats.innerHTML = "";
    scaleNodes = [];
    scaleLabels = null;
    return;
  }

  scaleStatus.textContent =
    `${active} synthetic NPCs · ${data.total_rows ?? 0} ClickHouse rows written · ` +
    `aggregate query answered in ${data.query_ms ?? "—"}ms`;

  // Ordered by npc_id server-side, so a given NPC keeps the same dot -- and
  // therefore the same label and position -- across polls.
  const roster = data.roster || [];
  scaleNodes = [];
  for (let i = 0; i < active; i++) {
    const npc = roster[i];
    scaleNodes.push({
      npcId: npc ? npc.npc_id : null,
      name: npc ? (npc.name || npc.npc_id) : "",
      label: "",
      color: npc ? (MOOD_COLORS[npc.mood] || "#7c8ba1") : "#3a4150",
      x: 0, y: 0, r: 5, phase: pseudoRandom(i * 31.7) * Math.PI * 2,
    });
  }
  layoutScaleNodes();

  scaleStats.innerHTML =
    `<strong>Scale test</strong><br>` +
    `Active synthetic NPCs: ${active}<br>` +
    `Total ClickHouse rows (this set): ${data.total_rows ?? 0}<br>` +
    `Ticks in the last 10s: ${data.recent_rows ?? 0}<br>` +
    (data.insert_ms !== undefined
      ? `Burst insert of ${active} rows took: ${data.insert_ms}ms<br>` : "") +
    `Live aggregate query took: ${data.query_ms ?? "—"}ms`;
}

async function setScale(count) {
  scaleSelect.disabled = true;
  scaleStatus.textContent = count > 0 ? `starting ${count} synthetic NPCs…` : "";
  try {
    const res = await fetch("/api/scale", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: Number(count) }),
    });
    renderScale(await res.json());
  } catch (err) {
    scaleStatus.textContent = "Scale test request failed.";
  } finally {
    scaleSelect.disabled = false;
  }
}

async function pollScale() {
  if (Number(scaleSelect.value) === 0) return;
  try {
    const res = await fetch("/api/scale");
    renderScale(await res.json());
  } catch (err) {
    console.error("scale poll failed", err);
  }
}

// Chain-reaction feed: a domino-effect log built entirely from ClickHouse
// events that the simulation writes as a side effect of each NPC's own
// Gemini decision -- nothing here decides what happened, only how to
// describe and animate it.
const CHAIN_ICONS = {
  chain_reaction_source: "🔥",
  goal_change: "🎯",
  scripted_event: "🎬",
};
const seenChainKeys = new Set();
let chainLogLoaded = false;

function npcName(npcId) {
  return (latestById[npcId] && latestById[npcId].name) || npcId;
}

function parseNoticedBy(payload) {
  const match = payload.match(/^(.*) \(noticed by: (.*)\)$/);
  if (!match) return null;
  return { action: match[1], ids: match[2].split(",").map((s) => s.trim()) };
}

function renderChainEntry(row) {
  const icon = CHAIN_ICONS[row.event_type] || "•";
  const name = npcName(row.npc_id);
  let detail;

  if (row.event_type === "chain_reaction_source") {
    const parsed = parseNoticedBy(row.payload);
    if (parsed) {
      const noticedNames = parsed.ids.map(npcName).join(", ");
      detail = `<strong>${escapeHtml(name)}</strong> ${escapeHtml(parsed.action)} — noticed by ${escapeHtml(noticedNames)}`;
    } else {
      detail = `<strong>${escapeHtml(name)}</strong> ${escapeHtml(row.payload)}`;
    }
  } else if (row.event_type === "goal_change") {
    const [oldGoal, newGoal] = row.payload.split(" -> ");
    detail = `<strong>${escapeHtml(name)}</strong> changed goal: “${escapeHtml(oldGoal || "")}” → “${escapeHtml(newGoal || row.payload)}”`;
  } else {
    detail = `<strong>${escapeHtml(name)}</strong> ${escapeHtml(row.payload)}`;
  }
  return `<div class="chain-entry">${icon} ${detail}</div>`;
}

// Ignites the real canvas nodes for a chain-log row: the source flares
// immediately, then a traveling pulse carries the same flare to each
// neighbor along its real proximity edge, arriving (and igniting that node)
// only once it visibly reaches it.
function triggerCascade(row) {
  const now = performance.now();
  if (row.event_type === "scripted_event") {
    ignite(row.npc_id, now, SCRIPT_COLOR);
    return;
  }
  if (row.event_type === "goal_change") {
    const n = sceneNodes.get(row.npc_id);
    if (n) n.goalPingStart = now;
    return;
  }
  if (row.event_type !== "chain_reaction_source") return;

  ignite(row.npc_id, now, FLARE_COLOR);
  const parsed = parseNoticedBy(row.payload);
  if (!parsed) return;
  parsed.ids.forEach((targetId, i) => {
    const na = sceneNodes.get(row.npc_id), nb = sceneNodes.get(targetId);
    if (!na || !nb) return;
    const dist = Math.hypot(na.x - nb.x, na.y - nb.y);
    const duration = Math.min(900, Math.max(300, dist / 0.6));
    pulses.push({ a: row.npc_id, b: targetId, start: now + i * 110, duration, color: FLARE_COLOR, arrived: false });
  });
}

async function pollChainLog() {
  try {
    const res = await fetch("/api/chain-log");
    const rows = await res.json();
    if (!rows.length) {
      chainLog.innerHTML = '<p class="chain-empty">Watching for ripple effects…</p>';
      return;
    }
    chainLog.innerHTML = rows.map(renderChainEntry).join("");
    // Only animate events that appeared since the last poll -- on first
    // load this would otherwise flash the whole history at once.
    for (const row of rows) {
      const key = `${row.ts}|${row.npc_id}|${row.event_type}`;
      if (seenChainKeys.has(key)) continue;
      seenChainKeys.add(key);
      if (chainLogLoaded) triggerCascade(row);
    }
    chainLogLoaded = true;
  } catch (err) {
    console.error("chain log poll failed", err);
  }
}

scaleSelect.addEventListener("change", () => setScale(scaleSelect.value));
setInterval(pollScale, 3000);

resizeCanvas();
requestAnimationFrame(draw);
loadProximity();
poll();
setInterval(poll, 3000);
pollChainLog();
setInterval(pollChainLog, 4000);

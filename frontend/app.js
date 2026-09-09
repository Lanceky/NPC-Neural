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

const scene = document.getElementById("scene");
const selectedInfo = document.getElementById("selected-info");
const askForm = document.getElementById("ask-form");
const askInput = document.getElementById("ask-input");
const askAnswer = document.getElementById("ask-answer");
const scaleSelect = document.getElementById("scale-select");
const scaleStatus = document.getElementById("scale-status");
const scaleView = document.getElementById("scale-view");
const scaleSwarm = document.getElementById("scale-swarm");
const scaleStats = document.getElementById("scale-stats");

const MOOD_COLORS = {
  neutral: "#7c8ba1", tense: "#c0554a", curious: "#4aa3c0", bored: "#6b6f76",
  alert: "#d4af37", nervous: "#b06fc9", amused: "#5fbf6a", focused: "#e0a63c",
};

let selectedId = null;
let latestById = {};
const elements = {};

function ensureElement(npcId) {
  if (elements[npcId]) return elements[npcId];
  const el = document.createElement("div");
  el.className = "npc";
  el.innerHTML = '<div class="dot"></div><div class="label"></div><div class="mood"></div>';
  el.addEventListener("click", () => selectNpc(npcId));
  scene.appendChild(el);
  elements[npcId] = el;
  return el;
}

function selectNpc(npcId) {
  selectedId = npcId;
  for (const [id, el] of Object.entries(elements)) {
    el.classList.toggle("selected", id === npcId);
  }
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
      const pos = LAYOUT[npc.npc_id];
      if (!pos) continue;
      latestById[npc.npc_id] = npc;
      const el = ensureElement(npc.npc_id);
      el.classList.toggle("principal", npc.tier === "principal");
      el.style.left = pos[0] + "%";
      el.style.top = pos[1] + "%";
      el.querySelector(".label").textContent = npc.name;
      el.querySelector(".mood").textContent = npc.mood || "";
    }
    if (selectedId) renderSelected();
  } catch (err) {
    console.error("poll failed", err);
  }
}

// Minimal, safe markdown: escapes HTML first, then only turns **bold** and
// newlines into tags -- the model's answers use just enough markdown for
// this to matter, and nothing more.
function renderMarkdownLite(text) {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
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

// Renders a swarm of dots colored by the live ClickHouse mood distribution —
// an aggregate summary, not per-NPC data, so this stays cheap at any scale.
function renderScale(data) {
  const active = data.active_count || 0;
  scene.hidden = active > 0;
  scaleView.hidden = active === 0;

  if (active === 0) {
    scaleStatus.textContent = "";
    scaleStats.innerHTML = "";
    return;
  }

  scaleStatus.textContent =
    `${active} synthetic NPCs · ${data.total_rows ?? 0} ClickHouse rows written · ` +
    `aggregate query answered in ${data.query_ms ?? "—"}ms`;

  const frag = document.createDocumentFragment();
  const moodCounts = Object.entries(data.mood_counts || {}).sort((a, b) => b[1] - a[1]);
  let placed = 0;
  for (const [mood, count] of moodCounts) {
    for (let i = 0; i < count; i++) {
      const dot = document.createElement("div");
      dot.className = "pixel";
      dot.style.background = MOOD_COLORS[mood] || "#7c8ba1";
      dot.title = mood;
      frag.appendChild(dot);
      placed++;
    }
  }
  for (; placed < active; placed++) {
    const dot = document.createElement("div");
    dot.className = "pixel";
    frag.appendChild(dot);
  }
  scaleSwarm.replaceChildren(frag);

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

scaleSelect.addEventListener("change", () => setScale(scaleSelect.value));
setInterval(pollScale, 3000);

poll();
setInterval(poll, 3000);

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
    askAnswer.textContent = data.answer;
  } catch (err) {
    askAnswer.textContent = "Error asking the director's assistant.";
  }
});

poll();
setInterval(poll, 3000);

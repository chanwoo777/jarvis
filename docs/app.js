// Jarvis's face: connects to Jarvis running on this computer and shows what it hears,
// thinks and does. Nothing here talks to any server except Jarvis on 127.0.0.1.
"use strict";

const LOCAL = ["localhost", "127.0.0.1"].includes(location.hostname);
const WS_URL = LOCAL ? `ws://${location.host}/ws` : "ws://127.0.0.1:8765/ws";
const STATE_LABELS = {
  starting: "Starting up", idle: "Standing by", listening: "Listening", thinking: "Thinking",
  speaking: "Speaking", asking: "Waiting for your answer",
};
const STATUS_LABELS = {
  queued: "Queued", thinking: "Thinking", ready: "Answer ready", held: "Held for later",
  told: "Told you", declined: "Kept in memory", failed: "Failed",
};
const TOOL_LABELS = {
  open_app: "open app", open_website: "browser", web_search: "web search", get_weather: "weather",
  set_volume: "volume", media_control: "media", system_status: "PC status", set_timer: "timer",
  lock_computer: "lock", think_deeply: "deep thinking", remember: "memory", recall: "memory",
};

const $ = (id) => document.getElementById(id);
const els = {
  messages: $("messages"), actions: $("actions"), tasks: $("tasks"), memory: $("memory"),
  state: $("state"), status: $("status"), statusText: $("status-text"), model: $("chip-model"),
  memoryChip: $("chip-memory"), composer: $("composer"), input: $("input"), mic: $("mic"),
  pairing: $("pairing"), pairTitle: $("pair-title"), pairText: $("pair-text"), pairForm: $("pair-form"), pairCode: $("pair-code"),
};

let ws = null;
let retryTimer = null;
let state = "idle";
let level = 0;
let tasks = new Map();
let failures = 0;

// ---------- pairing code (kept in this browser only) ----------

function store(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (e) { /* storage blocked */ }
}
function load(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
let pairCode = load("jarvis-pair");

function takeCodeFromLink() {
  const fromLink = new URLSearchParams(location.hash.slice(1)).get("pair");
  if (!fromLink) return false;
  pairCode = fromLink;
  store("jarvis-pair", fromLink);
  history.replaceState(null, "", location.pathname + location.search); // hide the code from the address bar
  return true;
}
takeCodeFromLink();
// Jarvis opened this page again with a new code (after a restart): use it right away.
addEventListener("hashchange", () => {
  if (takeCodeFromLink()) {
    els.pairing.hidden = true;
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    failures = 0;
    connect();
  }
});

function showPairing(title, text) {
  els.pairTitle.textContent = title;
  els.pairText.textContent = text;
  els.pairing.hidden = false;
  els.pairCode.focus();
}
els.pairForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const code = els.pairCode.value.trim();
  if (!code) return;
  pairCode = code;
  store("jarvis-pair", code);
  els.pairing.hidden = true;
  connect();
});

// ---------- connection ----------

function setStatus(kind, text) {
  els.status.className = `chip status ${kind}`;
  els.statusText.textContent = text;
  const online = kind === "online";
  els.mic.disabled = !online;
  els.input.disabled = !online;
}

function connect() {
  clearTimeout(retryTimer);
  if (ws && ws.readyState <= WebSocket.OPEN) return; // already connecting or connected: never open two
  pairCode = load("jarvis-pair") || pairCode; // another tab may have received a newer code
  if (!pairCode) {
    setStatus("offline", "Not paired");
    showPairing("Connect to Jarvis", "Start Jarvis on your laptop. It opens this page with a pairing code automatically. Or type the code shown in the Jarvis window:");
    return;
  }
  setStatus("", "Connecting…");
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    return retry();
  }
  ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: pairCode }));
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => retry();
}

function retry() {
  ws = null;
  failures += 1;
  setStatus("offline", failures > 2 ? "Jarvis is not running. Start run_jarvis.bat" : "Reconnecting…");
  if (!LOCAL && failures >= 2) {
    // The browser may be blocking this public page from reaching the PC: offer Jarvis's own copy of the page.
    $("local-link").href = `http://localhost:8765/${pairCode ? "#pair=" + encodeURIComponent(pairCode) : ""}`;
    $("blocked").hidden = false;
  }
  setState("idle");
  clearTimeout(retryTimer);
  retryTimer = setTimeout(connect, Math.min(10000, 1500 * failures));
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

// ---------- events from Jarvis ----------

function handle(ev) {
  switch (ev.type) {
    case "auth_failed":
      if (load("jarvis-pair") && load("jarvis-pair") !== pairCode) break; // a newer code arrived; retry uses it
      store("jarvis-pair", null);
      pairCode = null;
      ws.onclose = null;
      setStatus("offline", "Pairing code expired");
      showPairing("New pairing code needed", "Jarvis makes a new code each time it starts. Restart Jarvis to open this page with the new code, or type the code from the Jarvis window:");
      // Keep checking in case another tab gets the new code.
      setTimeout(function check() { load("jarvis-pair") ? (els.pairing.hidden = true, connect()) : setTimeout(check, 2000); }, 2000);
      break;
    case "snapshot":
      failures = 0;
      els.pairing.hidden = true;
      $("blocked").hidden = true;
      setStatus("online", "Connected");
      showInfo(ev.info);
      setState(ev.state);
      els.messages.replaceChildren();
      els.actions.replaceChildren();
      ev.history.forEach((item) => (item.type === "message" ? addMessage(item) : addAction(item)));
      if (!els.actions.children.length) els.actions.append(empty("Things Jarvis does on your PC appear here."));
      tasks = new Map();
      ev.tasks.forEach((t) => tasks.set(t.id, t));
      renderTasks();
      renderMemory(ev.memory);
      break;
    case "info": showInfo(ev.info); break;
    case "state": setState(ev.state); break;
    case "level": level = ev.value; break;
    case "message": addMessage(ev); break;
    case "action": addAction(ev); break;
    case "task": tasks.set(ev.task.id, ev.task); renderTasks(); break;
    case "memory": renderMemory(ev.items); break;
  }
}

function showInfo(info) {
  if (!info || !info.model) return;
  els.model.hidden = false;
  els.model.textContent = `quick ${info.model} · deep ${info.deep_model}`;
  els.memoryChip.hidden = !info.memory;
  els.memoryChip.textContent = `memory: ${info.memory}`;
  els.mic.hidden = info.mode === "text";
}

function setState(s) {
  state = s || "idle";
  els.state.textContent = STATE_LABELS[state] || state;
  els.state.className = `state ${state}`;
  els.mic.classList.toggle("live", state === "listening");
}

// ---------- rendering ----------

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function empty(text) { return el("li", "empty", text); }
function clock(t) {
  return new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function scrollDown(list) { list.scrollTop = list.scrollHeight; }

function addMessage(m) {
  const li = el("li", `msg ${m.role}`);
  li.append(el("span", "who", m.role === "user" ? (m.via === "voice" ? "You (voice)" : "You") : "Jarvis"));
  li.append(document.createTextNode(m.text));
  els.messages.append(li);
  scrollDown(els.messages);
}

function addAction(a) {
  els.actions.querySelector(".empty")?.remove();
  const li = el("li", "action");
  li.append(el("span", "tool", TOOL_LABELS[a.tool] || a.tool));
  li.append(el("span", "result", a.result.length > 160 ? a.result.slice(0, 160) + "…" : a.result));
  const time = el("time", "", clock(a.time));
  li.append(time);
  els.actions.append(li);
  scrollDown(els.actions);
}

function renderTasks() {
  const list = [...tasks.values()].sort((a, b) => b.created - a.created);
  if (!list.length) {
    els.tasks.replaceChildren(empty("Ask something detailed (“think about…”) and Jarvis works on it here while you keep talking."));
    return;
  }
  els.tasks.replaceChildren(...list.map(renderTask));
}

function renderTask(t) {
  const li = el("li", `task${t.asking ? " asking" : ""}`);
  li.append(el("div", "q", t.question));
  li.append(el("span", `badge ${t.status}`, t.asking ? "Asking you now" : STATUS_LABELS[t.status] || t.status));
  if (t.status === "thinking" || t.status === "queued") {
    if (t.thinking) {
      const box = el("div", "thoughts");
      box.append(el("span", "", t.thinking.slice(-600)));
      li.append(box);
    }
  } else if (t.answer) {
    // Answers you haven't chosen to hear stay hidden until you do.
    const shown = t.status === "told" || t.status === "failed";
    li.append(el("div", shown ? "answer" : "answer hidden-answer", shown ? t.answer : "Answer ready. Jarvis will ask before telling you."));
    const row = el("div", "decide");
    if (t.status === "ready" || t.status === "held" || t.asking) {
      row.append(button("yes", "Yes, tell me", () => send({ type: "decide", id: t.id, choice: "yes" })));
      row.append(button("wait", "Wait", () => send({ type: "decide", id: t.id, choice: "wait" })));
      row.append(button("no", "No", () => send({ type: "decide", id: t.id, choice: "no" })));
    } else if (t.status === "declined") {
      row.append(button("yes", "Tell me now", () => send({ type: "decide", id: t.id, choice: "yes" })));
    }
    if (row.children.length) li.append(row);
  }
  return li;
}

function button(cls, label, onClick) {
  const b = el("button", cls, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function renderMemory(items) {
  if (!items || !items.length) {
    els.memory.replaceChildren(empty("Nothing remembered yet. Try “Remember that…”."));
    return;
  }
  els.memory.replaceChildren(...items.slice().reverse().map((m) => {
    const li = el("li", "mem");
    li.append(el("span", "kind", m.kind === "answer" ? "answer" : "fact"));
    li.append(el("span", "", m.kind === "answer" ? m.question : m.text));
    li.append(el("time", "", (m.time || "").slice(5)));
    return li;
  }));
}

// ---------- input ----------

els.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.input.value.trim();
  if (!text) return;
  send({ type: "say", text });
  els.input.value = "";
});
els.mic.addEventListener("click", () => send({ type: "listen" }));

// ---------- the orb ----------

const canvas = $("orb");
const ctx = canvas.getContext("2d");
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
let shown = 0;
let spin = 0;

function drawOrb(now) {
  const size = canvas.width;
  const c = size / 2;
  const t = now / 1000;
  const asking = state === "asking";
  const color = asking ? "255,181,71" : "79,209,255";
  let target = 0.15;
  if (state === "listening") target = 0.2 + level * 1.6;
  else if (state === "speaking") target = 0.45 + 0.25 * Math.sin(t * 9) * Math.sin(t * 3.1);
  else if (state === "thinking") target = 0.35;
  else if (asking) target = 0.35 + 0.15 * Math.sin(t * 3);
  shown += (Math.min(target, 1) - shown) * 0.18;
  spin += state === "thinking" ? 0.06 : 0.008;

  ctx.clearRect(0, 0, size, size);
  const glow = ctx.createRadialGradient(c, c, 10, c, c, c * (0.55 + shown * 0.4));
  glow.addColorStop(0, `rgba(${color},${0.55 + shown * 0.4})`);
  glow.addColorStop(0.45, `rgba(${color},${0.18 + shown * 0.2})`);
  glow.addColorStop(1, `rgba(${color},0)`);
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(c, c, c, 0, Math.PI * 2); ctx.fill();

  ctx.lineCap = "round";
  const rings = [
    { r: 0.86, w: 2, segs: 3, speed: 1 },
    { r: 0.74, w: 6, segs: 8, speed: -1.6 },
    { r: 0.62, w: 2, segs: 1, speed: 0.5 },
    { r: 0.5, w: 10, segs: 10, speed: 2.2 },
  ];
  rings.forEach((ring, i) => {
    const radius = c * ring.r * (0.96 + shown * 0.06);
    ctx.strokeStyle = `rgba(${color},${0.35 + 0.15 * i + shown * 0.2})`;
    ctx.lineWidth = ring.w;
    const gap = ring.segs > 1 ? 0.35 : 0;
    for (let s = 0; s < ring.segs; s++) {
      const start = spin * ring.speed + (s / ring.segs) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(c, c, radius, start, start + (Math.PI * 2) / ring.segs - gap);
      ctx.stroke();
    }
  });

  ctx.fillStyle = `rgba(${color},0.95)`;
  ctx.shadowColor = `rgba(${color},1)`;
  ctx.shadowBlur = 30 + shown * 40;
  ctx.beginPath(); ctx.arc(c, c, c * (0.16 + shown * 0.1), 0, Math.PI * 2); ctx.fill();
  ctx.shadowBlur = 0;

  if (!reduceMotion) requestAnimationFrame(drawOrb);
}
requestAnimationFrame(drawOrb);

connect();

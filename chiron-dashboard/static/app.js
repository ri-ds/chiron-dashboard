/* Chiron Dashboard — tabbed control layer.
   Polls /api/state, renders one tab per tool + a Chiron tab, and surfaces the
   REAL run status (idle/running/finished/failed) plus, on failure, the actual
   error + log. All dynamic text is written with textContent (never innerHTML). */

"use strict";

const POLL_MS = 2000;
const TABS = [
  { key: "chiron", label: "Chiron", kind: "chiron" },
  { key: "validator", label: "Validator", kind: "tool" },
  { key: "dataquality", label: "Data quality", kind: "tool" },
  { key: "vulnscan", label: "Vulnerability scan", kind: "tool" },
  { key: "ineffscan", label: "Inefficiency scan", kind: "tool" },
  { key: "benchmark", label: "Benchmark suite", kind: "tool" },
];
let active = "chiron";
let lastState = null;
const ui = {};                 // per-key DOM references
const resultSig = {};          // per-tool: last rendered job signature
const openChironLogs = new Set();

// ---------- safe DOM helper ----------
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids) { if (kid == null || kid === false) continue; n.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return n;
}
function fmtDur(s) {
  if (s == null) return "";
  s = Math.round(s);
  return s < 60 ? s + "s" : Math.floor(s / 60) + "m " + String(s % 60).padStart(2, "0") + "s";
}
function fmtStamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function toast(msg, isErr) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast"), 3400);
}
async function getState() { return (await fetch("/api/state")).json(); }
async function getJSON(p) { return (await fetch(p)).json(); }
async function post(p) {
  const r = await fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  return { status: r.status, body: await r.json() };
}

/* ---------- status vocabulary ----------
   There are NO status dots on the tabs (a green tab dot was read as "no problems
   found" when it only meant "the run finished"). The status is stated in WORDS in
   one place — the badge at the top of each tab — and the colour now matches those
   words: green only ever means "no issues found", amber means issues were found. */
const CHIRON_STATE = {
  running:  { cls: "good", label: "Running" },
  starting: { cls: "warn busy", label: "Starting…" },
  stopped:  { cls: "bad",  label: "Stopped" },
  crashed:  { cls: "bad",  label: "Crashed" },
};
function chironOverall(chiron) {
  const states = Object.values(chiron).map((c) => c.state);
  if (states.every((s) => s === "running")) return { cls: "good", label: "All services running" };
  if (states.some((s) => s === "starting")) return { cls: "warn busy", label: "Starting…" };
  if (states.some((s) => s === "crashed")) return { cls: "bad", label: "Crashed" };
  if (states.some((s) => s === "running")) return { cls: "warn", label: "Partly running" };
  return { cls: "bad", label: "Stopped" };
}
/* What the tool's headline status SAYS. Findings first — that is the question
   people are actually asking when they glance at this. "Finished" on its own is
   never shown, because it doesn't answer it. */
function toolHero(t) {
  const job = t.last_job;
  if (t.busy || (job && job.status === "running")) return { cls: "warn busy", label: "Running…" };
  if (!job) return { cls: "idle", label: "Not run yet" };
  if (job.status === "failed") return { cls: "bad", label: "Run failed" };
  if (job.findings_outcome === "issues") return { cls: "warn", label: "Issues found" };
  if (job.findings_outcome === "clean") return { cls: "good", label: "No issues found" };
  return { cls: "idle", label: "Finished" };
}
function heroBadge() { return el("span", { class: "status-hero" }, el("span", { class: "dot" }), ""); }
function setHero(node, cls, label) { node.className = "status-hero " + cls; node.lastChild.textContent = label; }

// ---------- build tabs + panels ----------
function build() {
  const tabbar = document.getElementById("tabs");
  const panels = document.getElementById("panels");
  TABS.forEach((tab) => {
    // label only — no status dot (see the status vocabulary note above)
    const btn = el("button", { class: "tab", onclick: () => setActive(tab.key) }, tab.label);
    tabbar.append(btn);
    const panel = el("div", { class: "panel" });
    panels.append(panel);
    ui[tab.key] = { tab, btn, panel };
    if (tab.kind === "chiron") buildChironPanel(panel);
    else buildToolPanel(tab, panel);
  });
  setActive(active);
}

function buildChironPanel(panel) {
  const hero = heroBadge();
  panel.append(el("div", { class: "hero" },
    el("div", { class: "title-wrap" },
      el("h2", { text: "Chiron" }),
      el("p", { class: "desc", text: "Start, stop and restart Chiron, and watch its logs." })),
    hero));
  const grid = el("div", { class: "grid2" });
  panel.append(grid);
  ui.chiron.hero = hero;
  ui.chiron.grid = grid;
  ui.chiron.components = {};
  // Cards are created lazily from the live state (api/ui host-local; db/api/ui in
  // the docker-compose stack), so whatever components the backend reports each
  // get a card — no hardcoded component list.
}

function buildComponentCard(key) {
  const badge = el("span", { class: "badge" }, el("span", { class: "dot" }), "");
  const meta = el("div", { class: "card-meta" });
  const startBtn = el("button", { class: "btn primary sm", onclick: () => chiron(key, "start") }, "Start");
  const stopBtn = el("button", { class: "btn danger sm", onclick: () => chiron(key, "stop") }, "Stop");
  const restartBtn = el("button", { class: "btn sm", onclick: () => chiron(key, "restart") }, "Restart");
  const logsBtn = el("button", { class: "btn ghost sm", onclick: () => toggleChironLogs(key) }, "Logs");
  // "Open" link to the running service (api/ui). Hidden until running; also hidden
  // for non-http components (e.g. the db's postgresql:// url).
  const openLink = el("a", { class: "btn ghost sm", target: "_blank", rel: "noopener" }, "Open ↗");
  openLink.style.display = "none";
  const logBox = el("pre", { class: "logbox" }, "");
  const logDrawer = el("div", { style: "display:none;border-top:1px solid var(--border)" }, logBox);
  const titleEl = el("h3", { text: "" });
  const card = el("div", { class: "card" },
    el("div", { class: "card-top" },
      el("div", { class: "titles" }, titleEl, el("div", { class: "sub", text: "" })),
      badge),
    meta,
    el("div", { class: "card-actions" }, startBtn, stopBtn, restartBtn, el("span", { class: "spacer" }), openLink, logsBtn),
    logDrawer);
  ui.chiron.components[key] = { card, badge, meta, startBtn, stopBtn, restartBtn, openLink, logBox, logDrawer, titleEl, sub: card.querySelector(".sub") };
  return card;
}

function buildToolPanel(tab, panel) {
  const hero = heroBadge();
  const infoBtn = el("button", { class: "info-btn", title: "What does this do?", onclick: () => toggleInfo(tab.key) }, "i");
  const title = el("h2", {}, tab.label + " ", infoBtn);
  const desc = el("p", { class: "desc", text: "" });
  panel.append(el("div", { class: "hero" },
    el("div", { class: "title-wrap" }, title, desc), hero));
  const infoPop = el("div", { class: "info-pop" }, "");
  panel.append(infoPop);

  const runBtn = el("button", { class: "btn primary", onclick: () => runTool(tab.key) }, "Run");
  const summary = el("span", { class: "muted" }, "");
  panel.append(el("div", { class: "actionbar" }, runBtn, summary));

  // error block (shown on failure)
  const errBox = el("pre", { class: "errbox" }, "");
  const errBlock = el("div", { class: "block bad", style: "display:none" },
    el("div", { class: "block-head" }, "What went wrong"),
    el("div", { class: "block-body", style: "display:block" }, errBox));

  // run log block (collapsible)
  const logBox = el("pre", { class: "logbox" }, "");
  const logHead = el("div", { class: "block-head", onclick: () => { logBlock.classList.toggle("open"); refreshActive(); } },
    "Run log", el("span", { class: "chev", text: "›" }));
  const logBlock = el("div", { class: "block" }, logHead, el("div", { class: "block-body" }, logBox));

  // results block
  const resultBox = el("div", { class: "result" }, "");
  const resultBlock = el("div", { class: "block open" },
    el("div", { class: "block-head", onclick: () => resultBlock.classList.toggle("open") }, "Results", el("span", { class: "chev", text: "›" })),
    el("div", { class: "block-body" }, resultBox));

  // NOTE: the "Rules — edit & save" editor panel is removed for now (data quality
  // runs with the default rule settings). The backend rules API + loadRules()/
  // renderRulesEditor() below remain in place so it can be re-enabled later.
  const rulesBox = null;

  panel.append(errBlock, resultBlock, logBlock);
  ui[tab.key] = Object.assign(ui[tab.key], {
    hero, infoBtn, infoPop, desc, runBtn, summary, errBox, errBlock, logBox, logBlock, resultBox, rulesBox,
  });
}

// ---------- tab switching ----------
function setActive(key) {
  active = key;
  TABS.forEach((t) => {
    ui[t.key].btn.classList.toggle("active", t.key === key);
    ui[t.key].panel.classList.toggle("active", t.key === key);
  });
  refreshActive(true);
}
function toggleInfo(key) { ui[key].infoPop.classList.toggle("open"); }

// ---------- actions ----------
async function chiron(key, action) {
  const { body } = await post(`/api/chiron/${key}/${action}`);
  toast(body.ok === false ? (body.message || "action failed") : `${action}: ${body.message || "ok"}`, body.ok === false);
  refresh();
}
function toggleChironLogs(key) {
  if (openChironLogs.has(key)) openChironLogs.delete(key); else openChironLogs.add(key);
  refresh();
}
async function runTool(key) {
  const { body } = await post(`/api/tools/${key}/run`);
  if (body.ok === false) toast(body.message || "could not start", true);
  else toast(`${ui[key].tab.label} started`);
  refresh();
}

// ---------- updates ----------
function updateChiron(chiron) {
  const ov = chironOverall(chiron);
  setHero(ui.chiron.hero, ov.cls, ov.label);
  for (const [key, d] of Object.entries(chiron)) {
    let c = ui.chiron.components[key];
    if (!c) { ui.chiron.grid.append(buildComponentCard(key)); c = ui.chiron.components[key]; }
    const st = CHIRON_STATE[d.state] || CHIRON_STATE.stopped;
    c.badge.className = "badge " + st.cls; c.badge.lastChild.textContent = st.label;
    c.titleEl.textContent = d.label; c.sub.textContent = d.detail;
    c.meta.textContent = "";
    c.meta.append(el("span", {}, el("span", { class: "k", text: "Port " }), String(d.port)));
    if ((d.state === "running" || d.state === "starting") && d.uptime_s != null)
      c.meta.append(el("span", {}, el("span", { class: "k", text: "Uptime " }), fmtDur(d.uptime_s)));
    c.startBtn.disabled = d.state === "running" || d.state === "starting";
    c.stopBtn.disabled = d.state === "stopped";
    c.restartBtn.disabled = d.state === "starting";
    if (d.url && /^https?:/.test(d.url) && d.state === "running") {
      c.openLink.href = d.url; c.openLink.style.display = "";
    } else {
      c.openLink.style.display = "none";
    }
    const show = openChironLogs.has(key);
    c.logDrawer.style.display = show ? "block" : "none";
    if (show) refreshChironLog(key, c);
  }
}
async function refreshChironLog(key, c) {
  const j = await getJSON(`/api/chiron/${key}/logs?lines=200`);
  const atBottom = c.logBox.scrollHeight - c.logBox.scrollTop - c.logBox.clientHeight < 40;
  c.logBox.textContent = j.log || "(no log yet)";
  if (atBottom) c.logBox.scrollTop = c.logBox.scrollHeight;
}

function updateTool(key, t) {
  const u = ui[key];
  u.desc.textContent = t.detail;
  if (!u.infoPop.textContent) u.infoPop.textContent = t.info || "";
  u.infoBtn.title = t.info || "";
  const st = toolHero(t);
  setHero(u.hero, st.cls, st.label);
  u.runBtn.disabled = t.busy;
  u.runBtn.textContent = t.busy ? "Running…" : (t.kind === "report" ? "Load latest" : "Run");

  const job = t.last_job;
  u.summary.className = "muted";
  if (t.busy && job) u.summary.textContent = `Running (${fmtDur(job.elapsed_s)})…`;
  else if (job && job.status === "finished")
    // job.summary is the result headline (e.g. "63 of 65 endpoints passed · 2 failed"),
    // so the count of what was found is stated plainly right next to the button.
    u.summary.textContent = (job.summary ? job.summary + " · " : "") +
      `ran in ${fmtDur(job.elapsed_s)}`;
  else if (job && job.status === "failed")
    u.summary.textContent = `The run itself failed after ${fmtDur(job.elapsed_s)} — see “What went wrong” below`;
  else u.summary.textContent = "";

  // failure → surface the real error + log
  if (job && job.status === "failed") {
    u.errBlock.style.display = "";
    u.errBox.textContent = job.error || job.summary || "The run failed (no error text captured).";
    u.logBlock.classList.add("open");
  } else {
    u.errBlock.style.display = "none";
  }
}

async function refreshToolResult(key, t) {
  const j = await getJSON(`/api/tools/${key}/result`);
  renderResult(ui[key].resultBox, j.result || {});
}
async function refreshToolLog(key, t) {
  const job = t && t.last_job;
  if (!job) { ui[key].logBox.textContent = "No run in this session yet."; return; }
  const j = await getJSON(`/api/jobs/${job.id}/logs?lines=400`);
  ui[key].logBox.textContent = j.log || "No log output.";
}

function renderResult(box, res) {
  if (res && res.kind === "dataquality") { renderDataQuality(box, res); return; }
  box.textContent = "";
  if (res.headline) box.append(el("div", { class: "headline", text: res.headline }));
  if (res.generated)
    box.append(el("div", { class: "stamp", text: (res.static ? "Audit generated " : "Data from ") + fmtStamp(res.generated) }));
  if (res.note) box.append(el("div", { class: "note", text: res.note }));
  if (res.stats && res.stats.length) box.append(tilesEl(res.stats));
  if (res.rows && res.rows.length) {
    const cols = res.columns || [];
    const thead = el("tr");
    cols.forEach((c) => thead.append(el("th", { text: c })));
    const tbody = el("tbody");
    res.rows.forEach((row) => {
      const tr = el("tr");
      row.forEach((cell, ci) => {
        const name = cols[ci] || "";
        if (name === "Status") {
          const v = String(cell || "").toLowerCase().replace("/", "");
          tr.append(el("td", {}, el("span", { class: "sev " + v, text: String(cell) })));
        } else if (name === "Severity") {
          const v = String(cell || "").toLowerCase();
          tr.append(el("td", {}, el("span", { class: "sev " + v, text: String(cell) })));
        } else if (name.includes("Location") || name.includes("Endpoint") || name.includes("path") || name.includes("Actual")) {
          tr.append(el("td", { class: "mono", text: cell == null ? "" : String(cell) }));
        } else {
          tr.append(el("td", { text: cell == null ? "" : String(cell) }));
        }
      });
      tbody.append(tr);
    });
    box.append(el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, thead), tbody)));
  } else if (res.headline) {
    box.append(el("div", { class: "emptyok", text: res.empty_ok || "No results." }));
  } else {
    box.append(el("div", { class: "muted", text: "Press Run to produce results." }));
  }
}

// ---------- Data quality: custom rich renderer ----------
function tilesEl(stats) {
  const t = el("div", { class: "tiles" });
  (stats || []).forEach((s) => t.append(el("div", { class: "tile " + (s.tone || "idle") },
    el("div", { class: "v", text: String(s.value) }), el("div", { class: "l", text: s.label }))));
  return t;
}
function tableEl(columns, rows, cellRender) {
  const thead = el("tr");
  columns.forEach((c) => thead.append(el("th", { text: c })));
  const tbody = el("tbody");
  rows.forEach((r) => {
    const tr = el("tr");
    r.forEach((cell, ci) => tr.append(cellRender ? cellRender(columns[ci], cell)
      : el("td", { text: cell == null ? "" : String(cell) })));
    tbody.append(tr);
  });
  return el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, thead), tbody));
}
const _DQ_STATUS = { ok: ["pass", "Clean"], issues: ["medium", "Issues"], skipped: ["na", "Skipped"] };
function statusPill(status) {
  const [cls, label] = _DQ_STATUS[status] || ["na", status || "?"];
  return el("span", { class: "sev " + cls, text: label });
}

function renderDataQuality(box, res) {
  box.textContent = "";
  box.append(el("div", { class: "headline", text: res.headline || "" }));
  if (res.generated) box.append(el("div", { class: "stamp", text: "Data from " + fmtStamp(res.generated) }));
  if (res.note) box.append(el("div", { class: "note", text: res.note }));
  box.append(tilesEl(res.stats));

  // per-dataset summary
  box.append(el("div", { class: "section-label", text: "Per-dataset summary" }));
  box.append(tableEl(
    ["Dataset", "Subjects", "Concepts scanned", "Clean", "Flagged", "Skipped", "Issues"],
    (res.datasets || []).map((d) => [d.dataset, d.subjects, d.scanned, d.ok, d.with_issues, d.skipped, d.issues]),
    (col, cell) => col === "Dataset" ? el("td", { class: "mono", text: String(cell) })
      : el("td", { text: cell == null ? "" : String(cell) })));

  // by rule
  box.append(el("div", { class: "section-label", text: "Issues by rule" }));
  box.append((res.by_rule && res.by_rule.length)
    ? tableEl(["Rule", "Issues"], res.by_rule.map((r) => [r.kind, r.count]))
    : el("div", { class: "emptyok", text: "No issues from any rule." }));

  // every concept (client-side filter)
  const concepts = res.concepts || [];
  box.append(el("div", { class: "section-label", text: `Every concept (${concepts.length})` }));
  const counts = { all: concepts.length, issues: 0, ok: 0, skipped: 0 };
  concepts.forEach((c) => (counts[c.status] = (counts[c.status] || 0) + 1));
  const filterBar = el("div", { class: "filterbar" });
  const wrap = el("div");
  function draw(filter) {
    wrap.textContent = "";
    const rows = concepts.filter((c) => filter === "all" || c.status === filter)
      .map((c) => [c.status, c.dataset, c.concept, c.type, c.detail]);
    wrap.append(tableEl(["Status", "Dataset", "Concept", "Type", "Detail"], rows,
      (col, cell) => col === "Status" ? el("td", {}, statusPill(cell))
        : (col === "Dataset" || col === "Concept") ? el("td", { class: "mono", text: cell == null ? "" : String(cell) })
          : el("td", { text: cell == null ? "" : String(cell) })));
  }
  [["all", "All"], ["issues", "Flagged"], ["ok", "Clean"], ["skipped", "Skipped"]].forEach(([k, lbl]) => {
    const b = el("button", { class: "btn ghost sm", onclick: () => {
      Array.from(filterBar.children).forEach((x) => x.classList.remove("primary"));
      b.classList.add("primary"); draw(k);
    } }, `${lbl} (${counts[k] || 0})`);
    if (k === "all") b.classList.add("primary");
    filterBar.append(b);
  });
  box.append(filterBar, wrap);
  draw("all");

  // issue detail
  box.append(el("div", { class: "section-label", text: `Issue detail (${(res.issues || []).length})` }));
  box.append((res.issues && res.issues.length)
    ? tableEl(["Severity", "Dataset", "Concept", "Issue"],
        res.issues.map((i) => [i.severity, i.dataset, i.concept, i.message]),
        (col, cell) => col === "Severity" ? el("td", {}, el("span", { class: "sev " + String(cell).toLowerCase(), text: String(cell) }))
          : (col === "Dataset" || col === "Concept") ? el("td", { class: "mono", text: cell == null ? "" : String(cell) })
            : el("td", { text: cell == null ? "" : String(cell) }))
    : el("div", { class: "emptyok", text: "No issues." }));
}

// ---------- Data quality: rules editor ----------
let dqRulesLoaded = false;
async function loadRules() {
  const box = ui.dataquality && ui.dataquality.rulesBox;
  if (!box) return;
  try {
    const data = await getJSON("/api/tools/dataquality/rules");
    renderRulesEditor(box, data);
  } catch (e) {
    box.textContent = "Could not load rules.";
  }
}
function renderRulesEditor(box, data) {
  box.textContent = "";
  const catalog = data.catalog || [];
  const values = { ...(data.values || {}) };
  const defaults = data.defaults || {};
  box.append(el("div", { class: "note", text: "Edit the rules, click Save, then press Run to apply. Settings persist for future runs." }));
  const getters = {};
  catalog.forEach((rule) => {
    const row = el("div", { class: "rule-row" });
    const en = el("input", { type: "checkbox" });
    en.checked = !!values[rule.enabled_key];
    getters[rule.enabled_key] = () => en.checked;
    row.append(el("label", { class: "rule-head" }, en, el("b", { text: rule.label })));
    row.append(el("div", { class: "rule-desc muted", text: rule.description }));
    (rule.params || []).forEach((p) => {
      const pr = el("label", { class: "rule-param" });
      pr.append(el("span", { text: p.label }));
      if (p.type === "bool") {
        const c = el("input", { type: "checkbox" }); c.checked = !!values[p.key];
        getters[p.key] = () => c.checked; pr.append(c);
      } else {
        const inp = el("input", { type: "number", step: String(p.step || 1), value: String(values[p.key]) });
        if (p.min != null) inp.min = String(p.min);
        if (p.max != null) inp.max = String(p.max);
        getters[p.key] = () => { const n = parseFloat(inp.value); return isNaN(n) ? values[p.key] : n; };
        pr.append(inp);
      }
      row.append(pr);
    });
    box.append(row);
  });
  const save = el("button", { class: "btn primary sm", onclick: async () => {
    const newVals = {}; Object.keys(getters).forEach((k) => (newVals[k] = getters[k]()));
    try {
      await fetch("/api/tools/dataquality/rules", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: newVals }),
      });
      toast("Rules saved — press Run to apply"); dqRulesLoaded = false;
    } catch (e) { toast("Could not save rules", true); }
  } }, "Save rules");
  const reset = el("button", { class: "btn ghost sm", onclick: () => {
    renderRulesEditor(box, { catalog, values: { ...defaults }, defaults });
    toast("Reset to defaults (not saved yet — click Save)");
  } }, "Reset to defaults");
  box.append(el("div", { class: "rule-actions" }, save, reset));
}

// refresh the heavy content (result/log) of the ACTIVE tool tab
async function refreshActive(force) {
  if (!lastState) return;
  const key = active;
  if (key === "chiron") return;
  const t = lastState.tools[key];
  if (!t) return;
  const sig = (t.last_job ? t.last_job.id + ":" + t.last_job.status : "none");
  if (force || resultSig[key] !== sig) {
    resultSig[key] = sig;
    refreshToolResult(key, t);
  }
  if (ui[key].logBlock.classList.contains("open")) refreshToolLog(key, t);
}

// ---------- poll ----------
async function refresh() {
  let s;
  try { s = await getState(); } catch (e) { return; }
  lastState = s;
  updateChiron(s.chiron);
  for (const [key, t] of Object.entries(s.tools)) if (ui[key]) updateTool(key, t);
  refreshActive(false);
}

build();
refresh();
setInterval(refresh, POLL_MS);

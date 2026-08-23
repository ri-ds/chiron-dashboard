/* Chiron Dashboard — tabbed control layer.
   Polls /api/state, renders one tab per tool + a Chiron tab, and surfaces the
   REAL run status (idle/running/finished/failed) plus, on failure, the actual
   error + log. All dynamic text is written with textContent (never innerHTML). */

"use strict";

const POLL_MS = 2000;
const TABS = [
  // First, because it is the gate: signing in here is what will let the tools
  // below run against the signed-in live site rather than the local stack. Which
  // site that is comes from what is typed here -- it is not fixed anywhere.
  { key: "login", label: "Login", kind: "login" },
  { key: "chiron", label: "Chiron", kind: "chiron" },
  { key: "import", label: "Import", kind: "import" },
  { key: "validator", label: "Validator", kind: "tool" },
  { key: "dataquality", label: "Data quality", kind: "tool" },
  { key: "vulnscan", label: "Vulnerability scan", kind: "tool" },
  { key: "ineffscan", label: "Inefficiency scan", kind: "tool" },
  { key: "benchmark", label: "Benchmark suite", kind: "tool" },
];
let active = "login";

// Tools that can also run against the signed-in live site with the Login session.
// One tab each: two Run buttons, and the panel shows whichever ran last.
const LIVE_OF = { validator: "validator_live", dataquality: "dataquality_live" };

// Mirrors the sign-on sequence the helper reports, in order.
const LOGIN_STEPS = [
  ["open", "Opening the site"],
  ["idp", "Choosing Cincinnati Children's"],
  ["credentials", "Signing in"],
  ["duo", "Approving with Duo"],
  ["saml", "Completing sign-on"],
  ["done", "Signed in"],
];
let lastState = null;
const ui = {};                 // per-key DOM references
const resultSig = {};          // per-tool: last rendered job signature
const openChironLogs = new Set();

// ---------- safe DOM helper ----------
/* Host the live tools will actually hit, from the saved session. Naming a fixed
   deployment in the UI was actively misleading: the badge read "live RDCRN" while
   the run was going to HeartsMart. */
function liveHost() {
  const s = (lastState && lastState.session && lastState.session.site) || "";
  return s.replace(/^https?:\/\//, "");
}

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
  stopping: { cls: "warn busy", label: "Stopping…" },
  stopped:  { cls: "idle", label: "Stopped" },
  crashed:  { cls: "bad",  label: "Crashed" },
};
// Deliberately stopped is not a fault, so it reads grey. Red is reserved for
// "crashed", which now only happens on a genuinely unexpected exit.
function chironOverall(chiron) {
  const states = Object.values(chiron).map((c) => c.state);
  if (states.every((s) => s === "running")) return { cls: "good", label: "All services running" };
  if (states.some((s) => s === "stopping")) return { cls: "warn busy", label: "Stopping…" };
  if (states.some((s) => s === "starting")) return { cls: "warn busy", label: "Starting…" };
  if (states.some((s) => s === "crashed")) return { cls: "bad", label: "Crashed" };
  if (states.some((s) => s === "running")) return { cls: "warn", label: "Partly running" };
  return { cls: "idle", label: "All stopped" };
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
    else if (tab.kind === "login") buildLoginPanel(panel);
    else if (tab.kind === "import") buildImportPanel(panel);
    else buildToolPanel(tab, panel);
  });
  setActive(active);
}

function buildChironPanel(panel) {
  const hero = heroBadge();
  // Whole-stack controls. The backend orders them (db -> api -> ui on the way up,
  // reverse on the way down) so nothing comes up before what it depends on.
  const startAll = el("button", { class: "btn primary", onclick: () => chironAll("start") }, "Start all");
  const stopAll = el("button", { class: "btn danger", onclick: () => chironAll("stop") }, "Stop all");
  panel.append(el("div", { class: "toolbar" },
    startAll, stopAll, el("span", { class: "spacer" }), hero));

  const grid = el("div", { class: "grid2" });
  panel.append(grid);
  ui.chiron.hero = hero;
  ui.chiron.grid = grid;
  ui.chiron.startAll = startAll;
  ui.chiron.stopAll = stopAll;
  ui.chiron.components = {};
  // Cards are created lazily from the live state (api/ui host-local; db/api/ui in
  // the docker-compose stack), so whatever components the backend reports each
  // get a card — no hardcoded component list.
}

/* ---------- Import ----------
   Its own tab because it is a workflow, not a control: a folder to pick, a name
   to type, a plan to read, and a load that runs for minutes. Everything lands in
   one shared folder (~/chiron-imports) that both this dashboard and Chiron can
   see, so a dataset can arrive by Finder, by repo clone, or from the generator
   and be treated identically. */
function buildImportPanel(panel) {
  // --- bring data in -------------------------------------------------------
  const repoUrl = el("input", { class: "imp-input wide", type: "url",
    spellcheck: "false", placeholder: "https://github.com/org/synthea-data.git" });
  const cloneBtn = el("button", { class: "btn", onclick: doClone }, "Clone");
  const cloneMsg = el("span", { class: "muted" }, "");
  panel.append(el("div", { class: "imp-card" },
    el("div", { class: "imp-title", text: "Add data" }),
    el("div", { class: "imp-row" },
      el("label", { class: "imp-label", text: "Repo URL" }), repoUrl,
      cloneBtn, cloneMsg),
    el("div", { class: "imp-note", text:
      "Or copy a folder into chiron-imports/ in Finder. Either way it appears below." })));

  // --- create a project from a folder --------------------------------------
  const folderSel = el("select", { class: "imp-select", onchange: () => {
    ui.import.plan.style.display = "none";
    const opt = folderSel.selectedOptions[0];
    if (opt && opt.dataset.name) ui.import.nameInput.value = opt.dataset.name;
  } });
  const nameInput = el("input", { class: "imp-input", type: "text",
    spellcheck: "false", placeholder: "project name" });
  const refreshBtn = el("button", { class: "btn ghost", onclick: loadImportSources }, "Rescan");
  const previewBtn = el("button", { class: "btn", onclick: doImportPreview }, "Preview");
  const importBtn = el("button", { class: "btn primary", onclick: doImport },
    "Create project + import");
  const importMsg = el("span", { class: "muted" }, "");
  const plan = el("div", { class: "imp-plan", style: "display:none" });
  panel.append(el("div", { class: "imp-card" },
    el("div", { class: "imp-title", text: "Import into a new project" }),
    el("div", { class: "imp-row" },
      el("label", { class: "imp-label", text: "Data" }), folderSel, refreshBtn),
    el("div", { class: "imp-row" },
      el("label", { class: "imp-label", text: "Project" }), nameInput,
      previewBtn, importBtn, importMsg),
    plan));

  // --- what already exists -------------------------------------------------
  const projects = el("div", { class: "imp-projects" });
  panel.append(el("div", { class: "imp-card" },
    el("div", { class: "imp-title", text: "Projects in Chiron" }), projects));

  ui.import = Object.assign(ui.import, {
    repoUrl, cloneBtn, cloneMsg, folderSel, nameInput, refreshBtn,
    previewBtn, importBtn, importMsg, plan, projects,
  });
  loadImportSources();
  loadProjects();
}

async function doClone() {
  const u = ui.import;
  const url = u.repoUrl.value.trim();
  if (!url) { u.cloneMsg.textContent = "Paste a repository URL."; return; }
  u.cloneBtn.disabled = true;
  u.cloneMsg.textContent = "Cloning…";
  let body;
  try {
    const r = await fetch("/api/import/clone", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    body = await r.json();
  } catch (e) { body = { ok: false, message: "Could not reach the dashboard." }; }
  u.cloneBtn.disabled = false;
  if (body.ok) {
    u.cloneMsg.textContent = `Cloned ${body.folder} (${body.csv_files} CSV files).`;
    u.repoUrl.value = "";
    loadImportSources();
  } else {
    u.cloneMsg.textContent = body.message || "Clone failed.";
  }
}

async function loadImportSources() {
  const u = ui.import;
  if (!u || !u.folderSel) return;
  let d;
  try { d = await getJSON("/api/import/sources"); } catch (e) { return; }
  u.folderSel.textContent = "";
  const list = d.sources || [];
  if (!list.length) {
    u.folderSel.append(el("option", {}, "nothing in chiron-imports yet"));
    u.importBtn.disabled = u.previewBtn.disabled = true;
    return;
  }
  u.importBtn.disabled = u.previewBtn.disabled = false;
  list.forEach((sc) => {
    const o = el("option", { value: sc.folder },
      `${sc.name} — ${sc.patients.toLocaleString()} patients, ${sc.recognised} files`);
    o.dataset.name = sc.name;
    u.folderSel.append(o);
  });
  if (!u.nameInput.value) u.nameInput.value = list[0].name;
}

async function loadProjects() {
  const u = ui.import;
  if (!u || !u.projects) return;
  let d;
  try { d = await getJSON("/api/import/projects"); } catch (e) { return; }
  u.projects.textContent = "";
  (d.projects || []).forEach((p) => {
    const row = el("div", { class: "imp-projrow" },
      el("span", { class: "mono strong", text: p.unique_id }),
      el("span", { class: "imp-detail", text:
        `${p.sources} source(s)${p.folder ? " · " + p.folder : ""}` }));
    if (p.deletable) {
      row.append(el("button", { class: "btn danger sm imp-del",
        onclick: () => doDrop(p.unique_id) }, "Delete"));
    } else {
      row.append(el("span", { class: "imp-builtin", text: "built-in" }));
    }
    u.projects.append(row);
  });
}

async function doDrop(id) {
  // Deleting a project throws away its loaded data, so make the intent explicit.
  const typed = window.prompt(`Delete project "${id}" and all its loaded data?\n` +
                              `Type the project name to confirm.`);
  if (typed !== id) return;
  const { body } = await post(`/api/import/drop`);
  // post() sends an empty body; send the id properly instead.
  try {
    const r = await fetch("/api/import/drop", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unique_id: id }),
    });
    const b = await r.json();
    toast(b.ok ? `Deleted ${id}` : (b.error || "Delete failed"), !b.ok);
  } catch (e) { toast("Delete failed", true); }
  loadProjects();
}

function renderImportPlan(res) {
  const box = ui.import.plan;
  box.textContent = "";
  box.style.display = "";
  if (!res || res.ok === false) {
    box.append(el("div", { class: "imp-err", text: (res && res.error) || "Preview failed." }));
    return;
  }
  box.append(el("div", { class: "imp-head", text:
    `${res.loadable} file(s) · ${(res.total_rows || 0).toLocaleString()} rows` }));
  (res.plan || []).forEach((p) => box.append(el("div", { class: "imp-line" },
    el("span", { class: "sev " + (p.status === "ok" ? "pass" : "na"),
                 text: p.status === "ok" ? "load" : p.status }),
    el("span", { class: "mono", text: p.file }),
    el("span", { class: "imp-detail", text: `${p.collection} · ${p.detail}` }))));
  box.append(el("div", { class: "imp-note", text:
    "Creates a new project. Existing projects are never modified." }));
}

async function doImportPreview() {
  const u = ui.import;
  u.importMsg.textContent = "Reading files…";
  try {
    const f = encodeURIComponent(u.folderSel.value || "");
    renderImportPlan(await getJSON(`/api/import/preview?folder=${f}`));
    u.importMsg.textContent = "";
  } catch (e) { u.importMsg.textContent = "Preview failed."; }
}

async function doImport() {
  const u = ui.import;
  const name = (u.nameInput.value || "").trim();
  if (!name) { u.importMsg.textContent = "Give the project a name."; return; }
  u.importBtn.disabled = u.previewBtn.disabled = true;
  u.importMsg.textContent = "Starting…";
  try {
    const r = await fetch("/api/import/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unique_id: name, folder: u.folderSel.value,
                             display_name: name }),
    });
    const body = await r.json();
    if (body.ok === false) {
      u.importMsg.textContent = body.message || "Could not start.";
      u.importBtn.disabled = u.previewBtn.disabled = false;
      return;
    }
  } catch (e) {
    u.importMsg.textContent = "Could not reach the dashboard.";
    u.importBtn.disabled = u.previewBtn.disabled = false;
    return;
  }
  pollImport();
}

async function pollImport() {
  const u = ui.import;
  let st;
  try { st = (await getJSON("/api/import/status")).status; } catch (e) { return; }
  if (st.busy || st.phase === "running") {
    const secs = st.started ? Math.round((Date.now() - new Date(st.started)) / 1000) : 0;
    u.importMsg.textContent = `Loading… ${secs}s elapsed`;
    setTimeout(pollImport, 2000);
    return;
  }
  u.importBtn.disabled = u.previewBtn.disabled = false;
  if (st.phase === "done") {
    const c = (st.result || {}).created || {};
    u.importMsg.textContent =
      `Done. ${c.collections} collections, ${c.concepts} concepts.`;
    toast("Import finished");
    loadProjects();
  } else if (st.phase === "error") {
    u.importMsg.textContent = st.error || "Import failed.";
  }
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

/* ---------- Login panel ----------
   Deliberately styled apart from every other tab (see .loginwrap in styles.css).
   The other tabs are readouts you scan; this one is a credential screen you fill
   in, and it should not be mistaken for either at a glance. */
function buildLoginPanel(panel) {
  // Two columns. The form on the left, the guidance on the right. A full-width
  // card holding only three fields was mostly empty space, and hiding the help
  // behind a disclosure made the layout jump every time it opened.
  // The placeholder is an EXAMPLE and nothing more. It used to be a real
  // deployment URL that doLogin()/doUseCookie() fell back to when the field was
  // empty -- so leaving the box blank silently signed in to that site. A hint is
  // not a default.
  const urlInput = el("input", {
    class: "lg-input", type: "url", id: "lg-url", autocomplete: "off",
    placeholder: "https://chiron.example.org/  (paste your site URL)",
  });
  const openLink = el("a", { class: "lg-open", target: "_blank", rel: "noopener" },
                      "Open ↗");
  const syncOpen = () => {
    const v = urlInput.value.trim();
    openLink.href = v || "#";
    openLink.style.visibility = v ? "" : "hidden";
  };
  urlInput.addEventListener("input", syncOpen);
  syncOpen();
  const siteRow = el("div", { class: "lg-siterow" },
    el("label", { class: "lg-field lg-site" },
      el("span", { class: "lg-label", text: "Site" }), urlInput),
    openLink);

  const userInput = el("input", {
    class: "lg-input", type: "text", id: "lg-user", autocomplete: "username",
    placeholder: "you@cchmc.org",
  });
  const passInput = el("input", {
    class: "lg-input", type: "password", id: "lg-pass",
    autocomplete: "current-password", placeholder: "••••••••••",
  });
  const submit = el("button", { class: "lg-btn", type: "submit" }, "Sign in");
  const form = el("form", { class: "lg-form lg-pwform",
    onsubmit: (e) => { e.preventDefault(); doLogin(); } },
    el("label", { class: "lg-field" },
      el("span", { class: "lg-label", text: "Username" }), userInput),
    el("label", { class: "lg-field" },
      el("span", { class: "lg-label", text: "Password" }), passInput),
    submit);

  const cookieInput = el("textarea", {
    class: "lg-input lg-textarea", id: "lg-cookie", rows: "5", spellcheck: "false",
    // Deliberately obvious dummies. The previous placeholder carried strings shaped
    // exactly like a real Shibboleth SP cookie and a 32-char Django sessionid, which
    // is indistinguishable from a captured session committed to the repo.
    placeholder: "_shibsession_<hex>=<value>; sessionid=<value>; csrftoken=<value>",
  });
  const cookieBtn = el("button", { class: "lg-btn", type: "submit" }, "Use cookie");
  const cookieForm = el("form", { class: "lg-cookieform", style: "display:none",
    onsubmit: (e) => { e.preventDefault(); doUseCookie(); } },
    el("label", { class: "lg-field" },
      el("span", { class: "lg-label", text: "Cookie header" }), cookieInput),
    cookieBtn);

  const msg = el("p", { class: "lg-msg" }, "");

  // Right column, one panel per mode. Always visible, so nothing expands.
  const pwGuide = el("div", { class: "lg-guide" },
    el("h3", { class: "lg-guidetitle", text: "What happens when you sign in" }),
    el("ol", { class: "lg-steps-help" },
      hstep("The site opens and picks your institution",
            [txt("Cincinnati Children's.")]),
      hstep("Your username and password go into their form",
            [txt("Never stored, written to disk, or logged.")]),
      hstep("Duo sends a push to your phone", [txt("Approve it.")]),
      hstep("The session is saved",
            [txt("The other tabs can then run against that site.")])));

  const cookieGuide = el("div", { class: "lg-guide" },
    el("h3", { class: "lg-guidetitle", text: "Where to find the cookie" }),
    el("ol", { class: "lg-steps-help" },
      hstep("Sign in to the site",
            [txt("Use "), kbd("Open ↗"), txt(" and log in normally. The cookie does not exist until you are signed in.")]),
      hstep("Open your browser's developer tools",
            [kbd("F12"), txt(" on Windows or Linux, "), kbd("⌥ ⌘ I"), txt(" on a Mac.")]),
      hstep("Go to the Network tab, then reload",
            [txt("The list stays empty until the page loads again.")]),
      hstep("Click a request to the site itself",
            [txt("Pick a row whose domain matches the site. Analytics and other third parties never carry your session.")]),
      hstep("Copy the whole Cookie value",
            [txt("Scroll to "), mono("Request Headers"), txt(" and copy everything after "), mono("Cookie:"),
             txt(". It runs to several hundred characters and you need all of it.")]),
      hstep("Paste it into the box", [txt("It is checked straight away.")])),
    el("div", { class: "lg-warn" },
      el("b", { text: "Watch out. " }),
      txt("Copy from "), mono("Request Headers → Cookie"), txt(", not "),
      mono("Response Headers → Set-Cookie"), txt(". That one is the server talking back, and it will not work.")),
    el("div", { class: "lg-tip" },
      txt("Sessions expire after a few hours. When checks stop authenticating, paste a fresh one.")));

  const steps = el("ol", { class: "lg-steps" });
  const stepNodes = {};
  LOGIN_STEPS.forEach(([key, label]) => {
    const dot = el("span", { class: "lg-dot" });
    const text = el("span", { class: "lg-steptext", text: label });
    const li = el("li", { class: "lg-step" }, dot, text);
    steps.append(li);
    stepNodes[key] = { li, text, label };
  });
  const stepsWrap = el("div", { class: "lg-progress", style: "display:none" }, steps);
  const sessionBox = el("div", { class: "lg-session", style: "display:none" });

  const modeBar = el("div", { class: "lg-modes" },
    el("button", { class: "lg-mode active", type: "button",
      onclick: () => setLoginMode("password") }, "Sign in"),
    el("button", { class: "lg-mode", type: "button",
      onclick: () => setLoginMode("cookie") }, "Paste cookie"));

  panel.append(el("div", { class: "loginwrap" },
    el("div", { class: "lg-card" },
      modeBar,
      el("div", { class: "lg-grid" },
        el("div", { class: "lg-left" }, siteRow, form, cookieForm, msg, stepsWrap),
        el("div", { class: "lg-right" }, pwGuide, cookieGuide)),
      sessionBox)));

  ui.login = Object.assign(ui.login, {
    urlInput, openLink, userInput, passInput, submit, msg, stepsWrap, stepNodes,
    sessionBox, form, cookieForm, cookieInput, cookieBtn, modeBar,
    pwGuide, cookieGuide,
    mode: "password", started: false, ownMsgUntil: 0, sessionSig: null,
  });
  setLoginMode("password");
}

/* Bits used by the cookie help text. */
function txt(t) { return document.createTextNode(t); }
function kbd(t) { return el("kbd", { class: "lg-kbd", text: t }); }
function mono(t) { return el("code", { class: "lg-code", text: t }); }
function hstep(title, parts) {
  const li = el("li", {}, el("span", { class: "lg-stepname", text: title }));
  const d = el("span", { class: "lg-stepdetail" });
  parts.forEach((x) => d.append(x));
  li.append(d);
  return li;
}

/* Show a message the poll will leave alone for a few seconds. */
function loginSay(text, cls) {
  const u = ui.login;
  u.msg.className = "lg-msg" + (cls ? " " + cls : "");
  u.msg.textContent = text;
  u.ownMsgUntil = Date.now() + 6000;
}

function setLoginMode(mode) {
  const u = ui.login;
  u.mode = mode;
  u.form.style.display = mode === "password" ? "" : "none";
  u.cookieForm.style.display = mode === "cookie" ? "" : "none";
  // The stepper describes the password sign-on. It has nothing to say about a
  // pasted cookie, and leaving it up was one of the confusing bits.
  if (mode === "cookie") u.stepsWrap.style.display = "none";
  if (u.pwGuide) u.pwGuide.style.display = mode === "password" ? "" : "none";
  if (u.cookieGuide) u.cookieGuide.style.display = mode === "cookie" ? "" : "none";
  Array.from(u.modeBar.children).forEach((b, i) =>
    b.classList.toggle("active", (i === 0) === (mode === "password")));
  u.msg.className = "lg-msg";
  u.msg.textContent = "";
  u.ownMsgUntil = 0;
}

async function doUseCookie() {
  const u = ui.login;
  const url = u.urlInput.value.trim();
  const cookie = u.cookieInput.value.trim();
  if (!url) {
    loginSay("Enter the site URL first.", "err");
    return;
  }
  if (!cookie) {
    loginSay("Paste the Cookie header from your browser.", "err");
    return;
  }
  u.cookieBtn.disabled = true;
  u.cookieBtn.textContent = "Checking…";
  let body;
  try {
    const r = await fetch("/api/login/cookie", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookie }),
    });
    body = await r.json();
  } catch (e) {
    body = { ok: false, message: "Could not reach the dashboard." };
  }
  u.cookieBtn.disabled = false;
  u.cookieBtn.textContent = "Use cookie";
  if (body.ok) {
    u.cookieInput.value = "";   // treat it like a credential once accepted
    loginSay(`Cookie accepted — signed in as ${body.user || "you"}.`, "ok");
  } else {
    loginSay(body.message || "That cookie was not accepted.", "err");
  }
  refreshLogin();
}

async function doLogin() {
  const u = ui.login;
  const url = u.urlInput.value.trim();
  const username = u.userInput.value.trim();
  const password = u.passInput.value;
  if (!url) {
    loginSay("Enter the site URL you want to sign in to.", "err");
    return;
  }
  if (!username || !password) {
    loginSay("Enter your username and password.", "err");
    return;
  }
  u.msg.className = "lg-msg";
  u.msg.textContent = "";
  u.ownMsgUntil = 0;
  u.submit.disabled = true;
  u.submit.textContent = "Signing in…";
  u.stepsWrap.style.display = "";
  u.started = true;

  let body;
  try {
    const r = await fetch("/api/login/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, username, password }),
    });
    body = await r.json();
  } catch (e) {
    body = { ok: false, message: "Could not reach the dashboard." };
  }
  // Clear the password from the DOM the moment it has been sent.
  u.passInput.value = "";
  if (body.ok === false) {
    loginSay(body.message || "Could not start the sign-in.", "err");
    u.submit.disabled = false;
    u.submit.textContent = "Sign in";
  }
  refreshLogin();
}

async function doSignOut() {
  await post("/api/login/signout");
  toast("Saved session cleared from this machine");
  ui.login.started = false;
  refreshLogin();
}

function updateLoginSteps(st) {
  const u = ui.login;
  const idx = LOGIN_STEPS.findIndex(([k]) => k === st.step);
  const done = st.state === "done";
  LOGIN_STEPS.forEach(([key], i) => {
    const node = u.stepNodes[key];
    let cls = "lg-step";
    if (done || (idx > -1 && i < idx)) cls += " done";
    else if (idx === i) cls += (st.state === "error" ? " failed" : " active");
    node.li.className = cls;
    // The Duo step is the only one that asks something of the person, so it says so.
    node.text.textContent = (key === "duo" && idx === i && st.state !== "error")
      ? "Duo push sent — approve it on your phone" : node.label;
  });
}

async function refreshLogin() {
  const u = ui.login;
  if (!u || !u.urlInput) return;
  let st;
  try { st = (await getJSON("/api/login/status")).status; } catch (e) { return; }

  if (!u.urlInput.value && st.default_url) {
    u.urlInput.value = st.default_url;
    u.openLink.href = st.default_url;
  }

  const busy = !!st.busy;
  const pwMode = u.mode === "password";

  // Password-flow chrome only belongs to the password flow.
  if (pwMode) {
    if (u.started || busy || st.state === "running") u.stepsWrap.style.display = "";
    if (st.step) updateLoginSteps(st);
    u.submit.disabled = busy;
    u.submit.textContent = busy ? "Signing in…" : "Sign in";
  } else {
    u.stepsWrap.style.display = "none";
  }

  // Never overwrite a message the person just caused. The poll reads a status
  // file that outlives the action which wrote it, so without this a stale error
  // from an earlier password attempt would replace "Cookie accepted" 2s later.
  if (Date.now() >= (u.ownMsgUntil || 0) && pwMode) {
    if (st.state === "error" && st.error) {
      u.msg.className = "lg-msg err";
      u.msg.textContent = st.error;
    } else if (st.state === "done") {
      u.msg.className = "lg-msg ok";
      u.msg.textContent = st.message || "Signed in.";
    } else if (busy && st.message) {
      u.msg.className = "lg-msg";
      u.msg.textContent = st.message;
    }
  }

  // Rebuild the session box only when it actually changed — it was being torn
  // down and recreated every 2s, which flickered and dropped focus.
  const s2 = st.session || {};
  const sig = [s2.state, s2.cookies, s2.saved, st.user].join("|");
  if (sig === u.sessionSig) return;
  u.sessionSig = sig;

  const box = u.sessionBox;
  box.textContent = "";
  if (s2.state === "saved") {
    box.style.display = "";
    box.append(el("div", { class: "lg-sesstop" },
      el("span", { class: "lg-pill ok", text: "Session saved" }),
      st.user ? el("span", { class: "lg-who", text: st.user }) : null));
    box.append(el("div", { class: "lg-sessmeta", text:
      `${s2.cookies} cookies · saved ${fmtStamp(s2.saved)}` }));
    box.append(el("button", { class: "lg-linkbtn", onclick: doSignOut }, "Clear session"));
    // What this session can actually reach. Signing in is only a means to these
    // datasets, so name them right here rather than making someone start a run and
    // read the output to find out what was available.
    const dsBox = el("div", { class: "lg-sessds", text: "Datasets: checking..." });
    box.append(dsBox);
    fillLiveDatasetList(dsBox);
  } else {
    box.style.display = "none";
  }
}

/* Name the datasets the saved session can see, on the Login tab. */
async function fillLiveDatasetList(node) {
  let d;
  try { d = await getJSON("/api/live/datasets"); }
  catch (e) { node.textContent = "Datasets: could not check"; return; }
  node.textContent = "";
  if (!d.ok) { node.textContent = `Datasets: ${d.message || "none visible"}`; return; }
  if (!(d.datasets || []).length) {
    node.textContent = "Datasets: none visible to this account"; return;
  }
  node.append(el("div", { class: "lg-dshead",
    text: `Datasets on ${(d.site || "").replace(/^https?:\/\//, "")}` }));
  d.datasets.forEach((x) => node.append(el("div", { class: "lg-ds",
    text: `\u2022 ${x.name}  \u2014  ${x.unique_id}` })));
  node.append(el("div", { class: "lg-dsnote",
    text: "Pick one in the dropdown on the Validator / Data quality tabs." }));
}

function buildToolPanel(tab, panel) {
  const hero = heroBadge();
  const infoBtn = el("button", { class: "info-btn", title: "What does this do?", onclick: () => toggleInfo(tab.key) }, "i");
  const runBtn = el("button", { class: "btn primary", onclick: () => runTool(tab.key, false) }, "Run");
  const liveBtn = LIVE_OF[tab.key]
    ? el("button", { class: "btn", onclick: () => runTool(tab.key, true) }, "Run live")
    : null;
  const summary = el("span", { class: "muted" }, "");
  // Which project to run against. Hidden for tools that ignore datasets
  // (the scanners read source files, so a project means nothing to them).
  const dsSel = el("select", { class: "imp-select ds-select", style: "display:none" });
  const infoPop = el("div", { class: "info-pop" }, "");
  panel.append(
    el("div", { class: "toolbar" },
      runBtn, liveBtn, dsSel, summary,
      el("span", { class: "spacer" }), hero, infoBtn),
    infoPop);

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
    hero, infoBtn, infoPop, runBtn, liveBtn, dsSel, summary, errBox, errBlock,
    logBox, logBlock, resultBox, rulesBox, mode: "local",
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
async function chironAll(action) {
  const u = ui.chiron;
  u.startAll.disabled = u.stopAll.disabled = true;
  // Same reasoning as the per-card controls: reflect the intent immediately.
  const moving = action === "stop" ? "stopping" : "starting";
  const st = CHIRON_STATE[moving];
  setHero(u.hero, st.cls, st.label);
  Object.values(u.components).forEach((c) => {
    c.badge.className = "badge " + st.cls;
    c.badge.lastChild.textContent = st.label;
    c.startBtn.disabled = c.stopBtn.disabled = c.restartBtn.disabled = true;
  });
  const { body } = await post(`/api/chiron/all/${action}`);
  toast(body.ok === false ? (body.message || "action failed") : (body.message || "ok"),
        body.ok === false);
  refresh();
}

async function chiron(key, action) {
  // Show the transition straight away. Some services stop in well under the poll
  // interval, so waiting for the next /api/state made a click look like nothing
  // happened and then a sudden jump to stopped.
  const moving = { stop: "stopping", start: "starting", restart: "starting" }[action];
  const c = ui.chiron.components[key];
  if (c && moving) {
    const st = CHIRON_STATE[moving];
    c.badge.className = "badge " + st.cls;
    c.badge.lastChild.textContent = st.label;
    c.startBtn.disabled = c.stopBtn.disabled = c.restartBtn.disabled = true;
    if (action === "stop") c.stopBtn.textContent = "Stopping…";
    if (action !== "stop") c.startBtn.textContent = "Starting…";
  }
  const { body } = await post(`/api/chiron/${key}/${action}`);
  toast(body.ok === false ? (body.message || "action failed") : `${action}: ${body.message || "ok"}`, body.ok === false);
  refresh();
}
function toggleChironLogs(key) {
  if (openChironLogs.has(key)) openChironLogs.delete(key); else openChironLogs.add(key);
  refresh();
}
/* Fill a tool's dataset picker with BOTH universes, grouped and labelled.
   Local projects are Chiron's own; live datasets belong to the signed-in remote
   site. They are shown together so it is possible to SEE what a session unlocked
   without launching anything, but each option is tagged with its scope: a live run
   will not accept a local project id, and vice versa. An earlier version swapped the
   list based on which mode the panel was in, which meant the live datasets were
   invisible until after a live run had already happened. */
async function fillDatasetPicker(sel, key, hasLive) {
  const groups = [];
  try {
    const d = await getJSON("/api/import/projects");
    groups.push(["local", "Local Chiron projects",
      (d.projects || []).map((p) => [p.unique_id, p.unique_id])]);
  } catch (e) { /* the local stack may be down; live can still be listed */ }
  if (hasLive) {
    try {
      const d = await getJSON("/api/live/datasets");
      if (d.ok && (d.datasets || []).length) {
        groups.push(["live", `Live - ${(d.site || "").replace(/^https?:\/\//, "")}`,
          d.datasets.map((x) => [x.unique_id,
            x.name && x.name !== x.unique_id ? `${x.name} (${x.unique_id})` : x.unique_id])]);
      }
    } catch (e) { /* no session yet */ }
  }

  sel.textContent = "";
  // Data quality scans every local project when none is named, which is a useful
  // default. There is deliberately no such option for live: sweeping every dataset
  // on a remote site is not something to trigger by accident.
  if (key === "dataquality") {
    const o = el("option", { value: "" }, "All local projects");
    o.dataset.scope = "local";
    sel.append(o);
  }
  groups.forEach(([scope, label, items]) => {
    if (!items.length) return;
    const g = el("optgroup", { label });
    items.forEach(([v, text]) => {
      const o = el("option", { value: v }, text);
      o.dataset.scope = scope;
      g.append(o);
    });
    sel.append(g);
  });

  // Prefer the live current dataset when there is one -- that is what a "Run live"
  // is almost always for. Chiron names it "default".
  const prefer = (scope, value) => [...sel.options].find(
    (o) => o.dataset.scope === scope && o.value === value);
  const pick = prefer("live", "default") ||
               (key !== "dataquality" ? prefer("local", "dataset1_stored") : null);
  if (pick) pick.selected = true;
}

async function runTool(key, live) {
  const target = live ? LIVE_OF[key] : key;
  if (ui[key]) { ui[key].mode = live ? "live" : "local"; ui[key].modeTouched = true; }
  // Send the picker value only when it currently holds the right universe's list.
  // `filled` says which one that is; if the panel is showing local projects and a
  // live run is started, send nothing and let live_runner pick from the site itself
  // rather than handing it a local project id it cannot resolve.
  // Send the picked dataset only when it belongs to the universe being run. A local
  // project id handed to a live run 404s every dataset-scoped endpoint and gets
  // scored "unreached" rather than failed -- a silently wrong answer.
  const sel = ui[key] && ui[key].dsSel;
  const opt = sel && sel.selectedOptions ? sel.selectedOptions[0] : null;
  const scope = opt && opt.dataset ? opt.dataset.scope : "";
  const ds = (sel && scope === (live ? "live" : "local")) ? sel.value : "";
  const r = await fetch(`/api/tools/${target}/run`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset: ds }),
  });
  const body = await r.json();
  if (body.ok === false) toast(body.message || "could not start", true);
  else toast(`${ui[key].tab.label}${live ? " (live)" : ""} started`);
  refreshActive(true);
  refresh();
}

/* Which tool's state this tab is currently showing. A tab with a live counterpart
   shows whichever was run last, so pressing either button just works. */
function sourceKey(key) {
  const u = ui[key];
  return (u && u.mode === "live" && LIVE_OF[key]) ? LIVE_OF[key] : key;
}
function sourceTool(key) {
  return (lastState && lastState.tools[sourceKey(key)]) || null;
}

// ---------- updates ----------
function updateChiron(chiron) {
  const ov = chironOverall(chiron);
  setHero(ui.chiron.hero, ov.cls, ov.label);
  const all = Object.values(chiron);
  const anyMoving = all.some((c) => c.state === "starting" || c.state === "stopping");
  if (ui.chiron.startAll) {
    ui.chiron.startAll.disabled = anyMoving || all.every((c) => c.state === "running");
    ui.chiron.stopAll.disabled = anyMoving || all.every((c) => c.state === "stopped");
    ui.chiron.startAll.textContent = anyMoving ? "Working…" : "Start all";
  }
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
    const moving = d.state === "starting" || d.state === "stopping";
    c.startBtn.disabled = moving || d.state === "running";
    c.stopBtn.disabled = moving || d.state === "stopped";
    c.restartBtn.disabled = moving;
    c.stopBtn.textContent = d.state === "stopping" ? "Stopping…" : "Stop";
    c.startBtn.textContent = d.state === "starting" ? "Starting…" : "Start";
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
  // Until someone picks a target, show whichever ran most recently — so a reload
  // does not silently swap the results out from under you.
  if (!u.modeTouched && LIVE_OF[key] && lastState) {
    const lt = lastState.tools[LIVE_OF[key]];
    const at = (x) => (x && x.last_job && x.last_job.finished_at) || "";
    if (at(lt) > at(t)) u.mode = "live";
  }
  // `t` is always the LOCAL tool (the tab's own key). When the panel is showing
  // the live counterpart, everything below reads from that one instead.
  const src = sourceTool(key) || t;
  const isLive = sourceKey(key) !== key;
  if (u.dsSel && (t.selectable_dataset || (src && src.selectable_dataset))) {
    u.dsSel.style.display = "";
    // Refill when the panel flips between local and live: `filled` records which
    // list is currently in the dropdown, not merely that it was filled once.
    // Refill when the session appears or disappears, since that is what adds or
    // removes the live group. Not on mode flips: both groups are always present.
    const sess = (lastState && lastState.session && lastState.session.state) || "none";
    const want = `${!!LIVE_OF[key]}:${sess}`;
    if (u.dsSel.dataset.filled !== want) {
      u.dsSel.dataset.filled = want;
      fillDatasetPicker(u.dsSel, key, !!LIVE_OF[key]);
    }
  }
  if (u.liveBtn) {
    const lt = lastState && lastState.tools[LIVE_OF[key]];
    // A live run needs a session. Without one it can only fail, so the button is
    // disabled and says why, rather than starting a job that dies immediately.
    const signedIn = !!(lastState && lastState.session &&
                        lastState.session.state === "saved");
    const busyEither = !!(lt && lt.busy) || !!t.busy;
    u.liveBtn.disabled = busyEither || !signedIn;
    u.liveBtn.title = signedIn ? `Run against ${liveHost() || "the signed-in site"}`
                              : "Sign in on the Login tab first";
    u.liveBtn.className = "btn" + (isLive ? " primary" : "");
    u.runBtn.className = "btn" + (isLive ? "" : " primary");
  }
  t = src;
  if (!u.infoPop.textContent) u.infoPop.textContent = t.info || "";
  u.infoBtn.title = t.info || "";
  const st = toolHero(t);
  setHero(u.hero, st.cls, st.label);
  const anyBusy = t.busy || !!(lastState && LIVE_OF[key] &&
                               lastState.tools[LIVE_OF[key]] &&
                               lastState.tools[LIVE_OF[key]].busy);
  u.runBtn.disabled = anyBusy;
  u.runBtn.textContent = t.kind === "report" ? "Load latest" : "Run";

  const job = t.last_job;
  u.summary.className = "muted";
  // Deliberately silent while running: the badge above already says so.
  if (t.busy) u.summary.textContent = "";
  else if (job && job.status === "finished")
    // job.summary is the result headline (e.g. "63 of 65 endpoints passed · 2 failed"),
    // so the count of what was found is stated plainly right next to the button.
    u.summary.textContent = (job.summary ? job.summary + " · " : "") +
      `ran in ${fmtDur(job.elapsed_s)}` +
      (sourceKey(key) !== key ? ` · live ${liveHost() || "site"}`
                              : (LIVE_OF[key] ? " · local" : ""));
  else if (job && job.status === "failed")
    u.summary.textContent = "The run failed. See “What went wrong” below.";
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
  const j = await getJSON(`/api/tools/${sourceKey(key)}/result`);
  renderResult(ui[key].resultBox, j.result || {});
}
async function refreshToolLog(key, t) {
  const job = (sourceTool(key) || t || {}).last_job;
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

  // by rule — each row expands into the rule's own definition, so "what does
  // possible_typo_or_rare_value actually mean" is answerable without leaving here.
  box.append(el("div", { class: "section-label", text: "Issues by rule" }));
  if (res.by_rule && res.by_rule.length) {
    const list = el("div", { class: "expandlist" });
    res.by_rule.forEach((r) => {
      const detail = el("div", { class: "expandbody" });
      detail.append(el("div", { class: "kv" },
        el("span", { class: "k", text: "Rule" }),
        el("span", { text: r.label || r.kind })));
      detail.append(el("div", { class: "kv" },
        el("span", { class: "k", text: "Issue kind" }),
        el("span", { class: "mono", text: r.kind })));
      if (r.description)
        detail.append(el("p", { class: "expanddesc", text: r.description }));
      (r.params || []).forEach((p) =>
        detail.append(el("div", { class: "kv" },
          el("span", { class: "k", text: p.label || p.key }),
          el("span", { class: "mono", text: String(p.default != null ? p.default : "") }))));
      const row = el("button", { class: "expandhead", onclick: () => {
        const open = wrap.classList.toggle("open");
        chev.textContent = open ? "▾" : "▸";
      } },
        el("span", { class: "chevmark", text: "▸" }),
        el("span", { class: "expandtitle", text: r.label || r.kind }),
        el("span", { class: "expandcount", text: String(r.count) }));
      const chev = row.firstChild;
      const wrap = el("div", { class: "expandrow" }, row, detail);
      list.append(wrap);
    });
    box.append(list);
  } else {
    box.append(el("div", { class: "emptyok", text: "No issues from any rule." }));
  }

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

  // issue detail — filterable by project, each row expanding to its evidence
  const allIssues = res.issues || [];
  box.append(el("div", { class: "section-label", text: `Issue detail (${allIssues.length})` }));
  if (!allIssues.length) {
    box.append(el("div", { class: "emptyok", text: "No issues." }));
    return;
  }

  const projects = res.projects || [];
  let project = "all";
  const projBar = el("div", { class: "filterbar" });
  const issueWrap = el("div");

  function drawIssues() {
    issueWrap.textContent = "";
    const shown = allIssues.filter((i) => project === "all" || i.dataset === project);
    if (!shown.length) {
      issueWrap.append(el("div", { class: "emptyok", text: "No issues in this project." }));
      return;
    }
    const list = el("div", { class: "expandlist" });
    shown.forEach((i) => {
      const body = el("div", { class: "expandbody" });
      body.append(el("p", { class: "expanddesc", text: i.message || "" }));
      [["Project", i.dataset], ["Concept", i.concept], ["Concept id", i.concept_id],
       ["Type", i.concept_type], ["Rule", i.kind]].forEach(([k, v]) => {
        if (v) body.append(el("div", { class: "kv" },
          el("span", { class: "k", text: k }), el("span", { class: "mono", text: String(v) })));
      });
      // The evidence the check recorded — the numbers behind the claim.
      const det = i.details || {};
      const keys = Object.keys(det);
      if (keys.length) {
        body.append(el("div", { class: "section-label sub", text: "Evidence" }));
        keys.forEach((k) => body.append(el("div", { class: "kv" },
          el("span", { class: "k", text: k }),
          el("span", { class: "mono", text: typeof det[k] === "object"
            ? JSON.stringify(det[k]) : String(det[k]) }))));
      } else {
        body.append(el("div", { class: "muted", text: "This check recorded no extra evidence." }));
      }
      const head = el("button", { class: "expandhead", onclick: () => {
        const open = wrap.classList.toggle("open");
        head.firstChild.textContent = open ? "▾" : "▸";
      } },
        el("span", { class: "chevmark", text: "▸" }),
        el("span", { class: "sev " + String(i.severity).toLowerCase(), text: String(i.severity) }),
        el("span", { class: "expandtitle mono", text: i.concept || "" }),
        el("span", { class: "expandmsg", text: (i.message || "").slice(0, 90) }));
      const wrap = el("div", { class: "expandrow" }, head, body);
      list.append(wrap);
    });
    issueWrap.append(list);
  }

  [["all", `All (${allIssues.length})`]].concat(
    projects.map((p) => [p, `${p} (${allIssues.filter((i) => i.dataset === p).length})`])
  ).forEach(([key, label]) => {
    const b = el("button", { class: "btn ghost sm", onclick: () => {
      project = key;
      Array.from(projBar.children).forEach((x) => x.classList.remove("primary"));
      b.classList.add("primary");
      drawIssues();
    } }, label);
    if (key === "all") b.classList.add("primary");
    projBar.append(b);
  });
  box.append(projBar, issueWrap);
  drawIssues();
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
  if (key === "login") { refreshLogin(); return; }
  if (key === "import") return;   // refreshed by its own actions
  const t = lastState.tools[key];
  if (!t) return;
  const src = sourceTool(key) || t;
  const sig = sourceKey(key) + ":" +
    (src.last_job ? src.last_job.id + ":" + src.last_job.status : "none");
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

// KGWeave AST demo — SA5 guided tour stepper.
//
// Hand-rolled, dependency-free. The tour spec lives in
// ../data/tour.json; this module renders a popover card, advances steps
// in response to Next/Back/End, drives the file-rail + query panel via
// the public API exposed on `state` by app.js, and persists the current
// step index in localStorage so a reload resumes where the user left off.
//
// Public exports (consumed by app.js):
//   loadTour(url)             — fetch the spec; resolves to the tour object
//   startTour(host, opts)     — begin (or resume) the tour
//   nextStep()                — advance by one
//   prevStep()                — back up by one
//   endTour()                 — close the popover, keep progress in storage
//   restartTour()             — clear storage, jump to step 0, open the popover
//   currentStep()             — return the current spec step (or null)
//   tourState                 — module-level state (steps, index, mounted DOM)
//
// host is the app.js "state-bridge" object — it must expose:
//   - selectFile(fileId)
//   - runCannedQuery(canned)
//   - runFreeform(text)
//   - clearQuery()
//
// The tour never touches Cytoscape / CodeMirror directly — it stays on
// the public API surface so a future redesign of those panes doesn't
// break the tutorial.

const STORAGE_KEY = "kgweave.tour.step";

export const tourState = {
  spec: null,         // parsed tour.json
  steps: [],          // alias of spec.steps
  index: 0,           // current step index
  host: null,         // host bridge (see startTour)
  rootEl: null,       // popover DOM
  overlayEl: null,    // backdrop
  active: false,
};

// -------------------------------------------------------------------------
// Persistence
// -------------------------------------------------------------------------

function loadIndex() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return 0;
    const n = Number.parseInt(raw, 10);
    return Number.isNaN(n) ? 0 : n;
  } catch (_) {
    return 0;
  }
}

function saveIndex(i) {
  try {
    localStorage.setItem(STORAGE_KEY, String(i));
  } catch (_) {
    /* ignore quota / disabled storage */
  }
}

function clearIndex() {
  try { localStorage.removeItem(STORAGE_KEY); } catch (_) { /* */ }
}

// -------------------------------------------------------------------------
// Loading the spec
// -------------------------------------------------------------------------

export async function loadTour(url = "../data/tour.json") {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`failed to fetch tour.json: ${r.status}`);
  const spec = await r.json();
  tourState.spec = spec;
  tourState.steps = spec.steps || [];
  return spec;
}

// -------------------------------------------------------------------------
// DOM building
// -------------------------------------------------------------------------

function ensureCard() {
  if (tourState.rootEl) return tourState.rootEl;
  const overlay = document.createElement("div");
  overlay.className = "tour-overlay";
  overlay.id = "tour-overlay";
  // Only dismiss on backdrop click when the backdrop is actually present
  // (cookbook mode). Tour mode is click-transparent, so this listener
  // never fires from the user clicking through to the graph.
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay && overlay.classList.contains("cookbook-mode")) endTour();
  });

  const card = document.createElement("div");
  card.className = "tour-card";
  card.id = "tour-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");
  card.setAttribute("aria-labelledby", "tour-card-title");

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "tour-close";
  closeBtn.setAttribute("aria-label", "Close tour");
  closeBtn.textContent = "x";
  closeBtn.addEventListener("click", () => endTour());

  const title = document.createElement("h2");
  title.className = "tour-title";
  title.id = "tour-card-title";

  const body = document.createElement("p");
  body.className = "tour-body";

  const meta = document.createElement("div");
  meta.className = "tour-meta";

  const footer = document.createElement("div");
  footer.className = "tour-footer";

  const prevBtn = document.createElement("button");
  prevBtn.type = "button";
  prevBtn.className = "tour-prev";
  prevBtn.textContent = "Back";
  prevBtn.addEventListener("click", () => prevStep());

  const nextBtn = document.createElement("button");
  nextBtn.type = "button";
  nextBtn.className = "tour-next";
  nextBtn.textContent = "Next";
  nextBtn.addEventListener("click", () => nextStep());

  const skipBtn = document.createElement("button");
  skipBtn.type = "button";
  skipBtn.className = "tour-skip";
  skipBtn.textContent = "Skip tour";
  skipBtn.addEventListener("click", () => endTour());

  footer.append(prevBtn, nextBtn, skipBtn);
  card.append(closeBtn, title, body, meta, footer);
  overlay.appendChild(card);
  document.body.appendChild(overlay);

  tourState.rootEl = card;
  tourState.overlayEl = overlay;
  return card;
}

function renderCurrent() {
  const card = ensureCard();
  const step = tourState.steps[tourState.index];
  if (!step) { endTour(); return; }
  card.querySelector(".tour-title").textContent = step.title || step.id;
  card.querySelector(".tour-body").textContent = step.body || "";
  const meta = card.querySelector(".tour-meta");
  const total = tourState.steps.length;
  meta.textContent = `Step ${tourState.index + 1} of ${total}` +
    (step.family ? ` — family: ${step.family}` : "");

  // Toggle Back/Next labels at boundaries.
  const prevBtn = card.querySelector(".tour-prev");
  const nextBtn = card.querySelector(".tour-next");
  prevBtn.disabled = tourState.index === 0;
  nextBtn.textContent = tourState.index === total - 1 ? "Finish" : "Next";

  // Run the step's side effects via the host bridge.
  runStepEffects(step);
}

function runStepEffects(step) {
  const host = tourState.host;
  if (!host) return;
  // Always clear the previous query before running a new one — SA4 lesson #3.
  try { host.clearQuery && host.clearQuery(); } catch (_) { /* */ }
  if (step.run) {
    if (step.run.file && host.selectFile) {
      try { host.selectFile(step.run.file); } catch (_) { /* */ }
    }
    if (step.run.canned && host.runCannedQuery) {
      try { host.runCannedQuery(step.run.canned); } catch (_) { /* */ }
    } else if (step.run.freeform && host.runFreeform) {
      try { host.runFreeform(step.run.freeform); } catch (_) { /* */ }
    }
  }
}

// -------------------------------------------------------------------------
// Public navigation API
// -------------------------------------------------------------------------

export async function startTour(host, opts = {}) {
  tourState.host = host || tourState.host;
  if (!tourState.spec) {
    try { await loadTour(opts.url); } catch (e) {
      console.error("tour: failed to load spec", e);
      return;
    }
  }
  if (!tourState.steps.length) return;
  // Resume from storage unless the caller forced a restart.
  if (opts.restart) {
    clearIndex();
    tourState.index = 0;
  } else {
    const stored = loadIndex();
    tourState.index = Math.max(0, Math.min(stored, tourState.steps.length - 1));
  }
  tourState.active = true;
  ensureCard();
  tourState.overlayEl.classList.add("visible");
  renderCurrent();
}

export function nextStep() {
  if (!tourState.active) return;
  if (tourState.index >= tourState.steps.length - 1) {
    endTour();
    return;
  }
  tourState.index += 1;
  saveIndex(tourState.index);
  renderCurrent();
}

export function prevStep() {
  if (!tourState.active) return;
  if (tourState.index <= 0) return;
  tourState.index -= 1;
  saveIndex(tourState.index);
  renderCurrent();
}

export function endTour() {
  if (!tourState.overlayEl) return;
  tourState.overlayEl.classList.remove("visible");
  tourState.overlayEl.classList.remove("cookbook-mode");
  tourState.active = false;
}

export function restartTour() {
  clearIndex();
  tourState.index = 0;
  startTour(tourState.host, { restart: true });
}

export function currentStep() {
  return tourState.steps[tourState.index] || null;
}

// -------------------------------------------------------------------------
// Cookbook — renders a one-shot reference card listing every canned query
// + the free-form DSL grammar. Lives next to the tour because it shares
// the same overlay machinery.
// -------------------------------------------------------------------------

export function openCookbook(queries, host) {
  ensureCard();
  if (host) tourState.host = host;
  const card = tourState.rootEl;
  card.querySelector(".tour-title").textContent = "Query cookbook";
  const body = card.querySelector(".tour-body");
  body.textContent = "";
  const intro = document.createElement("p");
  intro.textContent =
    "Click any query below to run it. These are the same canned queries available as chips in the top toolbar.";
  body.appendChild(intro);
  const list = document.createElement("ul");
  list.className = "tour-cookbook";
  for (const q of (queries && queries.queries) || []) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cookbook-run";
    btn.title = `Run ${q.id}`;
    const code = document.createElement("code");
    code.textContent = q.id;
    const label = document.createElement("strong");
    label.textContent = q.label;
    const blurb = document.createElement("span");
    blurb.textContent = q.blurb || "";
    blurb.className = "muted";
    btn.append(code, document.createTextNode(" — "), label,
               document.createElement("br"), blurb);
    btn.addEventListener("click", () => {
      endTour();
      const h = tourState.host;
      if (h && h.runCannedQuery) {
        try { h.runCannedQuery(q.id); } catch (_) { /* */ }
      }
    });
    li.appendChild(btn);
    list.appendChild(li);
  }
  body.appendChild(list);
  const note = document.createElement("p");
  note.className = "muted";
  note.innerHTML =
    "To write your own query, expand <em>advanced query (DSL)</em> in the right-hand panel.";
  body.appendChild(note);
  card.querySelector(".tour-meta").textContent = "Cookbook — close to return.";
  card.querySelector(".tour-prev").disabled = true;
  const nextBtn = card.querySelector(".tour-next");
  nextBtn.textContent = "Close";
  nextBtn.onclick = () => { endTour(); nextBtn.onclick = null; };
  tourState.overlayEl.classList.add("visible");
  tourState.overlayEl.classList.add("cookbook-mode");
  tourState.active = false; // not a "real" tour step
}

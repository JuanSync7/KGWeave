// KGWeave AST demo — SA3 static FE skeleton.
//
// Loads ../data/graph.json, renders:
//   - left rail: file list
//   - centre:    CodeMirror 6 read-only pane (one document per file)
//   - right:     Cytoscape.js graph in #graph-pane (mount point #cy)
//   - bottom:    inspector showing the selected node/edge's fields
//
// Bidirectional click flow (the acceptance contract):
//   (a) click node n -> populate #inspector with id/type/category/payload/span
//   (b) if n.span is non-null, switch CodeMirror to span.file
//   (c) scroll CodeMirror to the start line of span
//   (d) decorate [span.startOffset, span.endOffset) with .cm-span-highlight
//
// Span offsets are CHARACTER offsets (SA2 already did the byte->char map),
// so we can pass them directly to CodeMirror.

import cytoscape from "https://esm.sh/cytoscape@3.30.4";
import { EditorState, StateField, StateEffect, RangeSetBuilder } from "https://esm.sh/@codemirror/state@6.4.1";
import {
  EditorView,
  Decoration,
  lineNumbers,
  highlightActiveLine,
} from "https://esm.sh/@codemirror/view@6.26.3";
import {
  runCannedQuery,
  parseAndRunFreeform,
  runAndAnimate,
  clearQueryViz,
} from "./query.js";

// -------------------------------------------------------------------------
// Category + edge-type style maps
// -------------------------------------------------------------------------

const CATEGORY_COLORS = {
  semantic: "#2c6cf2",   // blue
  structural: "#888888", // gray
  blob: "#f2d765",       // light yellow
  token: "#c8c8c8",      // gray (default-hidden)
};

// Edge styling. Anything not listed falls back to the "default" colour.
const EDGE_COLORS = {
  drives: "#2aa84a",        // green
  reads: "#3a8ad9",         // blue
  sensitive_to: "#8a4ad9",  // purple
  instantiates: "#d94a3a",  // red
  of_module: "#d94a3a",     // red
  connects: "#e0852a",      // orange
  child: "#3a3f48",         // muted (default-hidden)
};
function edgeColor(type) {
  if (EDGE_COLORS[type]) return EDGE_COLORS[type];
  if (type && type.startsWith("has_")) return "#a0a0a0"; // light gray
  return "#444444"; // default black-ish
}

// -------------------------------------------------------------------------
// CodeMirror span-highlight decoration field
// -------------------------------------------------------------------------

const setHighlight = StateEffect.define(); // payload: { from, to } | null
const highlightField = StateField.define({
  create() {
    return Decoration.none;
  },
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (e.is(setHighlight)) {
        if (!e.value) {
          deco = Decoration.none;
        } else {
          const { from, to } = e.value;
          const b = new RangeSetBuilder();
          b.add(from, to, Decoration.mark({ class: "cm-span-highlight" }));
          deco = b.finish();
        }
      }
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

// -------------------------------------------------------------------------
// State
// -------------------------------------------------------------------------

const state = {
  graph: null,                 // raw graph.json
  filesById: new Map(),        // FileEntry by id
  nodesById: new Map(),        // NodeEntry by id
  edgesById: new Map(),        // EdgeEntry by id
  view: null,                  // CodeMirror EditorView
  currentFile: null,           // current FileEntry.id
  cy: null,                    // Cytoscape instance
  queries: null,               // raw queries.json
  queriesById: new Map(),      // canned query spec by id
  filters: {
    categoryVisible: { semantic: true, structural: true, blob: true, token: false },
    edgeChildVisible: false,
    edgeSemanticVisible: true,
    showTokens: false, // alias for backward search; mirrors categoryVisible.token
    hideTokens: true,  // ditto, inverse
  },
};

// -------------------------------------------------------------------------
// Boot
// -------------------------------------------------------------------------

async function boot() {
  const r = await fetch("../data/graph.json", { cache: "no-cache" });
  if (!r.ok) throw new Error(`failed to fetch graph.json: ${r.status}`);
  const g = await r.json();
  state.graph = g;
  for (const f of g.files) state.filesById.set(f.id, f);
  for (const n of g.nodes) state.nodesById.set(n.id, n);
  for (const e of g.edges) state.edgesById.set(e.id, e);

  document.getElementById("stats").textContent =
    `${g.stats.nodeCount} nodes · ${g.stats.edgeCount} edges · ${g.files.length} files`;

  // Load canned-query registry (non-fatal if missing).
  try {
    const qr = await fetch("../data/queries.json", { cache: "no-cache" });
    if (qr.ok) {
      const qj = await qr.json();
      state.queries = qj;
      for (const q of qj.queries) state.queriesById.set(q.id, q);
    }
  } catch (e) {
    console.warn("queries.json not loaded:", e);
  }

  buildFileRail();
  mountCodeMirror();
  mountCytoscape();
  wireFilters();
  wireQueryPanel();

  // Open the first file
  if (g.files.length) selectFile(g.files[0].id);
}

// -------------------------------------------------------------------------
// File rail
// -------------------------------------------------------------------------

function buildFileRail() {
  const rail = document.getElementById("file-rail");
  rail.innerHTML = "";
  for (const f of state.graph.files) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.fileId = f.id;
    b.textContent = `${f.id}  (${f.lineCount}L)`;
    b.addEventListener("click", () => selectFile(f.id));
    rail.appendChild(b);
  }
}

function markActiveFile(fileId) {
  for (const b of document.querySelectorAll("#file-rail button")) {
    b.classList.toggle("active", b.dataset.fileId === fileId);
  }
}

// -------------------------------------------------------------------------
// CodeMirror pane
// -------------------------------------------------------------------------

function mountCodeMirror() {
  const parent = document.getElementById("code-pane");
  const startState = EditorState.create({
    doc: "",
    extensions: [
      lineNumbers(),
      highlightActiveLine(),
      EditorView.editable.of(false),
      EditorView.theme({
        "&": { backgroundColor: "#11141a", color: "#e3e6eb" },
        ".cm-gutters": { backgroundColor: "#181b22", color: "#8b94a3", border: "none" },
      }, { dark: true }),
      highlightField,
    ],
  });
  state.view = new EditorView({ state: startState, parent });

  // Reverse lookup: click in code -> highlight every node whose span covers
  // the offset. SA3 acceptance §6.3.
  state.view.dom.addEventListener("click", (ev) => {
    if (!state.currentFile) return;
    const pos = state.view.posAtCoords({ x: ev.clientX, y: ev.clientY });
    if (pos == null) return;
    reverseLookupAtOffset(state.currentFile, pos);
  });
}

function selectFile(fileId) {
  const f = state.filesById.get(fileId);
  if (!f) return;
  state.currentFile = fileId;
  markActiveFile(fileId);
  state.view.dispatch({
    changes: { from: 0, to: state.view.state.doc.length, insert: f.source },
    effects: setHighlight.of(null),
  });
}

function highlightSpanInCode(span) {
  if (!span || span.file == null) return;
  if (span.file !== state.currentFile) selectFile(span.file);
  const doc = state.view.state.doc;
  const from = Math.max(0, Math.min(span.startOffset, doc.length));
  const to = Math.max(from, Math.min(span.endOffset, doc.length));
  // Scroll into view, then apply mark decoration over [from, to).
  state.view.dispatch({
    effects: [
      setHighlight.of({ from, to }),
      EditorView.scrollIntoView(from, { y: "center" }),
    ],
  });
}

// -------------------------------------------------------------------------
// Cytoscape graph
// -------------------------------------------------------------------------

function mountCytoscape() {
  const elements = [];
  for (const n of state.graph.nodes) {
    const role = n.semantic && n.semantic.role ? n.semantic.role : "";
    const name = n.semantic && n.semantic.name ? n.semantic.name : "";
    elements.push({
      group: "nodes",
      data: {
        id: n.id,
        category: n.category,
        type: n.type,
        kind: n.kind,
        label: name || role || shortKind(n.kind),
      },
    });
  }
  for (const e of state.graph.edges) {
    elements.push({
      group: "edges",
      data: {
        id: e.id,
        source: e.src,
        target: e.dst,
        type: e.type,
      },
    });
  }

  state.cy = cytoscape({
    container: document.getElementById("cy"),
    elements,
    wheelSensitivity: 0.25,
    style: [
      {
        selector: "node",
        style: {
          "background-color": (ele) => CATEGORY_COLORS[ele.data("category")] || "#666",
          "label": "data(label)",
          "color": "#e3e6eb",
          "font-size": 8,
          "text-valign": "center",
          "text-halign": "center",
          "text-outline-color": "#0f1115",
          "text-outline-width": 1,
          "width": 18,
          "height": 18,
        },
      },
      {
        selector: "node:selected",
        style: { "border-color": "#fff", "border-width": 2 },
      },
      {
        selector: "edge",
        style: {
          "line-color": (ele) => edgeColor(ele.data("type")),
          "target-arrow-color": (ele) => edgeColor(ele.data("type")),
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          "width": 1,
        },
      },
      {
        selector: "edge:selected",
        style: { "width": 3, "line-color": "#fff", "target-arrow-color": "#fff" },
      },
      {
        selector: ".dim",
        style: { "display": "none" },
      },
      {
        selector: "node.match",
        style: {
          "border-color": "#ffe066",
          "border-width": 3,
          "background-blacken": -0.2,
        },
      },
      {
        selector: "edge.path-active",
        style: {
          "line-color": "#ffe066",
          "target-arrow-color": "#ffe066",
          "width": 4,
          "transition-property": "line-color width",
          "transition-duration": "200ms",
        },
      },
      {
        selector: ".query-dim",
        style: { "opacity": 0.15 },
      },
    ],
    layout: { name: "concentric", concentric: () => 1, levelWidth: () => 1, animate: false },
  });

  state.cy.on("tap", "node", (ev) => onGraphSelect(ev.target, "node"));
  state.cy.on("tap", "edge", (ev) => onGraphSelect(ev.target, "edge"));
  state.cy.on("mouseover", "node", (ev) => showTooltip(ev));
  state.cy.on("mouseout", "node", () => hideTooltip());

  applyFilters();
  document.getElementById("relayout").addEventListener("click", () => {
    state.cy.layout({ name: "concentric", animate: false }).run();
  });
}

function shortKind(kindStr) {
  // "SyntaxKind.ModuleDeclaration" -> "ModuleDeclaration"
  return (kindStr || "").replace(/^SyntaxKind\.|^TokenKind\./, "");
}

// -------------------------------------------------------------------------
// Click handlers — graph -> inspector + code pane
// -------------------------------------------------------------------------

function onGraphSelect(target, kind) {
  if (kind === "node") {
    const n = state.nodesById.get(target.id());
    if (!n) return;
    renderInspector(n, "node");
    if (n.span) highlightSpanInCode(n.span);
  } else {
    const e = state.edgesById.get(target.id());
    if (!e) return;
    renderInspector(e, "edge");
    if (e.span) highlightSpanInCode(e.span);
  }
}

function renderInspector(entry, kind) {
  const ins = document.getElementById("inspector");
  ins.innerHTML = "";
  const row = (k, v, cls = "") => {
    const r = document.createElement("div");
    r.className = "insp-row";
    const ke = document.createElement("span"); ke.className = "insp-key"; ke.textContent = k;
    const ve = document.createElement("span"); ve.className = "insp-val " + cls;
    if (typeof v === "object") {
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(v, null, 2);
      ve.appendChild(pre);
    } else {
      ve.textContent = String(v);
    }
    r.append(ke, ve); ins.appendChild(r);
  };
  if (kind === "node") {
    row("kind", "node");
    row("id", entry.id);
    row("type", entry.type);
    row("syntaxKind", shortKind(entry.kind));
    row("category", entry.category, "insp-cat-" + entry.category);
    if (entry.span) row("span", entry.span);
    if (entry.semantic) row("semantic", entry.semantic, "insp-cat-semantic");
    if (entry.payload && Object.keys(entry.payload).length) {
      // payload can include rawText/trivia (token) or blob detail
      row("payload", entry.payload, entry.category === "blob" ? "insp-cat-blob" : "");
    }
  } else {
    row("kind", "edge");
    row("id", entry.id);
    row("type", entry.type);
    row("src", entry.src);
    row("dst", entry.dst);
    if (entry.span) row("span", entry.span);
    if (entry.payload && Object.keys(entry.payload).length) row("payload", entry.payload);
  }
}

// -------------------------------------------------------------------------
// Reverse lookup — code -> graph
// -------------------------------------------------------------------------

function reverseLookupAtOffset(fileId, offset) {
  // Find every node whose span covers (file, offset). Pick the topmost
  // (smallest-width) semantic node as the inspector focus; ring all matches.
  const matches = [];
  for (const n of state.graph.nodes) {
    if (!n.span || n.span.file !== fileId) continue;
    if (offset >= n.span.startOffset && offset < n.span.endOffset) matches.push(n);
  }
  if (!matches.length) return;
  matches.sort(
    (a, b) =>
      (a.span.endOffset - a.span.startOffset) -
      (b.span.endOffset - b.span.startOffset),
  );
  // Prefer a semantic match if one exists; else fall back to the smallest span.
  const focus = matches.find((m) => m.category === "semantic") || matches[0];
  // Select in cytoscape (if visible).
  if (state.cy) {
    state.cy.elements().unselect();
    const ele = state.cy.getElementById(focus.id);
    if (ele && ele.length) {
      ele.select();
      try { state.cy.center(ele); } catch (_) {}
    }
  }
  renderInspector(focus, "node");
  if (focus.span) highlightSpanInCode(focus.span);
}

// -------------------------------------------------------------------------
// Tooltip — hover affordance
// -------------------------------------------------------------------------

let _tooltipEl = null;
function showTooltip(ev) {
  const n = state.nodesById.get(ev.target.id());
  if (!n) return;
  hideTooltip();
  const el = document.createElement("div");
  el.className = "tooltip";
  const role = n.semantic && n.semantic.role ? n.semantic.role : shortKind(n.kind);
  const payloadStr = JSON.stringify(n.payload || {}, null, 0).slice(0, 200);
  el.textContent = `${role}\n${payloadStr}`;
  document.body.appendChild(el);
  _tooltipEl = el;
  const pos = ev.renderedPosition || ev.position;
  const rect = document.getElementById("cy").getBoundingClientRect();
  el.style.left = (rect.left + (pos.x || 0) + 12) + "px";
  el.style.top = (rect.top + (pos.y || 0) + 12) + "px";
}
function hideTooltip() {
  if (_tooltipEl) { _tooltipEl.remove(); _tooltipEl = null; }
}

// -------------------------------------------------------------------------
// Filters
// -------------------------------------------------------------------------

function wireFilters() {
  for (const cb of document.querySelectorAll('#filters input[data-category]')) {
    cb.addEventListener("change", () => {
      const cat = cb.dataset.category;
      state.filters.categoryVisible[cat] = cb.checked;
      if (cat === "token") {
        state.filters.showTokens = cb.checked;
        state.filters.hideTokens = !cb.checked;
      }
      applyFilters();
    });
  }
  for (const cb of document.querySelectorAll('#filters input[data-edge]')) {
    cb.addEventListener("change", () => {
      if (cb.dataset.edge === "child") state.filters.edgeChildVisible = cb.checked;
      if (cb.dataset.edge === "semantic") state.filters.edgeSemanticVisible = cb.checked;
      applyFilters();
    });
  }
}

function applyFilters() {
  if (!state.cy) return;
  state.cy.batch(() => {
    state.cy.nodes().forEach((n) => {
      const cat = n.data("category");
      const vis = state.filters.categoryVisible[cat];
      n.toggleClass("dim", !vis);
    });
    state.cy.edges().forEach((e) => {
      const t = e.data("type");
      const isChild = t === "child";
      const visType = isChild
        ? state.filters.edgeChildVisible
        : state.filters.edgeSemanticVisible;
      const srcVis = !e.source().hasClass("dim");
      const dstVis = !e.target().hasClass("dim");
      e.toggleClass("dim", !(visType && srcVis && dstVis));
    });
  });
}

// -------------------------------------------------------------------------
// Query panel — SA4
// -------------------------------------------------------------------------

function wireQueryPanel() {
  const sel = document.getElementById("query-select");
  const ff = document.getElementById("query-freeform");
  const runBtn = document.getElementById("query-run");
  const clearBtn = document.getElementById("query-clear");
  if (!sel || !runBtn || !clearBtn) return;

  // Populate dropdown from queries.json registry.
  if (state.queries && state.queries.queries) {
    for (const q of state.queries.queries) {
      const opt = document.createElement("option");
      opt.value = q.id;
      opt.textContent = q.label;
      opt.title = q.blurb || "";
      sel.appendChild(opt);
    }
  }

  sel.addEventListener("change", () => {
    if (sel.value) runQuery({ canned: sel.value });
  });
  runBtn.addEventListener("click", () => {
    const text = (ff && ff.value || "").trim();
    if (text) runQuery({ freeform: text });
    else if (sel.value) runQuery({ canned: sel.value });
  });
  ff.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      runBtn.click();
    }
  });
  clearBtn.addEventListener("click", () => clearQuery());
}

async function runQuery({ canned, freeform }) {
  if (!state.cy || !state.graph) return;
  hideTooltip();
  const errEl = document.getElementById("query-error");
  if (errEl) { errEl.hidden = true; errEl.textContent = ""; }

  let result;
  let label;
  if (canned) {
    result = runCannedQuery(state.graph, canned, state.queriesById);
    const spec = state.queriesById.get(canned) || {};
    label = spec.label || canned;
  } else if (freeform) {
    result = parseAndRunFreeform(state.graph, freeform);
    label = `freeform: ${freeform}`;
  } else {
    return;
  }

  if (result && result.error) {
    if (errEl) { errEl.hidden = false; errEl.textContent = "Error: " + result.error; }
    renderResultsHeader("0 results", label);
    renderResultsList([]);
    return;
  }

  renderResultsHeader(
    `${(result.nodes || []).length} nodes · ${(result.edges || []).length} edges`,
    label,
  );
  renderResultsList(result.nodes || []);
  await runAndAnimate(state.cy, state.graph, result, { dimNonMatching: true });
}

function clearQuery() {
  const sel = document.getElementById("query-select");
  const ff = document.getElementById("query-freeform");
  if (sel) sel.value = "";
  if (ff) ff.value = "";
  const errEl = document.getElementById("query-error");
  if (errEl) { errEl.hidden = true; errEl.textContent = ""; }
  renderResultsHeader("no query", "");
  renderResultsList([]);
  if (state.cy) clearQueryViz(state.cy);
  // Re-apply SA3 filters to restore default visibility.
  applyFilters();
}

function renderResultsHeader(summary, label) {
  const s = document.getElementById("results-summary");
  if (s) s.textContent = label ? `${label} — ${summary}` : summary;
}

function renderResultsList(nodeIds) {
  const list = document.getElementById("results-list");
  if (!list) return;
  list.innerHTML = "";
  const limit = 200; // perf bound — SPEC §6 SA4 requires ≤200ms result rendering
  const shown = nodeIds.slice(0, limit);
  for (const nid of shown) {
    const n = state.nodesById.get(nid);
    if (!n) continue;
    const li = document.createElement("li");
    const role = (n.semantic && n.semantic.role) || shortKind(n.kind);
    const name = (n.semantic && n.semantic.name) || "";
    const span = n.span
      ? `${n.span.file}:${n.span.startLine}-${n.span.endLine}`
      : "";
    li.textContent = `${role}${name ? " " + name : ""}  ${span}`;
    li.title = nid;
    li.addEventListener("click", () => {
      renderInspector(n, "node");
      if (n.span) highlightSpanInCode(n.span);
      if (state.cy) {
        state.cy.elements().unselect();
        const ele = state.cy.getElementById(nid);
        if (ele && ele.length) {
          ele.removeClass("dim");
          ele.select();
          try { state.cy.center(ele); } catch (_) {}
        }
      }
    });
    list.appendChild(li);
  }
  if (nodeIds.length > limit) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = `… and ${nodeIds.length - limit} more (showing first ${limit})`;
    list.appendChild(li);
  }
}

// -------------------------------------------------------------------------

boot().catch((err) => {
  console.error(err);
  const ins = document.getElementById("inspector");
  ins.textContent = "Failed to load graph.json: " + err.message;
});

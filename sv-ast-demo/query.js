// KGWeave AST demo — SA4 query engine + multi-hop traversal viz.
//
// Public exports (consumed by app.js):
//
//   runCannedQuery(graph, queryId, queriesByIdMap)
//       Look up the spec, dispatch on spec.kind, return
//       { nodes:[ids], edges:[ids], paths?: [[ids]] }.
//
//   parseAndRunFreeform(graph, queryStr)
//       Parse the one-line DSL, run it, return same shape or
//       { error: "<message>" } on a parse failure.
//
//   animatePath(cy, edgeIds, opts)
//       Highlight each edge in `edgeIds` sequentially (~300ms per edge).
//       Returns a Promise that resolves when the animation completes.
//
//   pulseNodes(cy, nodeIds, opts)
//       Un-dim the listed nodes (SA3 lesson #2 — query results should pop
//       through filter `display:none`) and brief-glow them. Non-matched
//       nodes get an extra `.dim` class to fade them out for contrast.
//
//   clearQueryViz(cy)
//       Remove every class added by the previous query run.
//
//   buildAdjacency(graph)
//       Helper — returns { inc, out } adjacency maps. Each map is
//       Map<nodeId, EdgeEntry[]>. Exposed so app.js can memoise it.
//
//   bfs / findPath
//       Lower-level traversal primitives shared with the canned-query
//       dispatcher; exported for unit-style ad-hoc queries.
//
// The Python ground-truth port lives at
// `research/ast_experiment/tests/demo/test_query_engine.py`; the spec
// schema (`demo/data/queries.json`) is shared between the two.

// -------------------------------------------------------------------------
// Filter matching — schema mirrors the Python port verbatim.
// -------------------------------------------------------------------------

function matchFilter(node, flt) {
  const sem = node.semantic || {};
  for (const [k, v] of Object.entries(flt)) {
    if (k === "role_in") {
      if (!v.includes(sem.role)) return false;
    } else if (k === "role") {
      if (sem.role !== v) return false;
    } else if (k === "name") {
      if (sem.name !== v) return false;
    } else if (k === "path") {
      if (sem.path !== v) return false;
    } else if (k === "file") {
      const sp = node.span || {};
      if (sp.file !== v) return false;
    } else if (k === "kind") {
      const kind = (node.kind || "")
        .replace(/^SyntaxKind\./, "")
        .replace(/^TokenKind\./, "");
      if (kind !== v) return false;
    } else if (k === "id") {
      if (node.id !== v) return false;
    } else {
      return false;
    }
  }
  return true;
}

function findAnchors(graph, flt) {
  return graph.nodes.filter((n) => matchFilter(n, flt));
}

// -------------------------------------------------------------------------
// Adjacency maps. O(E) build, O(degree) lookup.
// -------------------------------------------------------------------------

export function buildAdjacency(graph) {
  const inc = new Map();
  const out = new Map();
  for (const e of graph.edges) {
    if (!out.has(e.src)) out.set(e.src, []);
    out.get(e.src).push(e);
    if (!inc.has(e.dst)) inc.set(e.dst, []);
    inc.get(e.dst).push(e);
  }
  return { inc, out };
}

// -------------------------------------------------------------------------
// BFS — direction picked by passing the right adjacency map + neighbour key.
// -------------------------------------------------------------------------

export function bfs(seeds, adj, via, depth, neighbourKey) {
  const visitedN = new Set(seeds);
  const visitedE = new Set();
  const viaSet = new Set(via);
  let frontier = [...seeds];
  for (let d = 0; d < depth; d++) {
    const nxt = [];
    for (const nid of frontier) {
      const list = adj.get(nid);
      if (!list) continue;
      for (const e of list) {
        if (!viaSet.has(e.type)) continue;
        visitedE.add(e.id);
        const neigh = e[neighbourKey];
        if (!visitedN.has(neigh)) {
          visitedN.add(neigh);
          nxt.push(neigh);
        }
      }
    }
    frontier = nxt;
    if (!frontier.length) break;
  }
  return { nodes: visitedN, edges: visitedE };
}

export function findPath(srcId, dstId, outAdj, via, depth) {
  const viaSet = new Set(via);
  // queue entries: [nodeId, nodePath, edgePath]
  const queue = [[srcId, [srcId], []]];
  const seen = new Set([srcId]);
  while (queue.length) {
    const [nid, npath, epath] = queue.shift();
    if (nid === dstId) return { nodes: npath, edges: epath };
    if (npath.length - 1 >= depth) continue;
    const list = outAdj.get(nid);
    if (!list) continue;
    for (const e of list) {
      if (!viaSet.has(e.type)) continue;
      if (seen.has(e.dst)) continue;
      seen.add(e.dst);
      queue.push([e.dst, [...npath, e.dst], [...epath, e.id]]);
    }
  }
  return { nodes: null, edges: null };
}

// -------------------------------------------------------------------------
// Canned-query dispatcher.
// -------------------------------------------------------------------------

export function runCannedQuery(graph, queryId, queriesById) {
  const spec = queriesById.get(queryId) || queriesById[queryId];
  if (!spec) return { error: `unknown query id: ${queryId}` };
  const { inc, out } = buildAdjacency(graph);
  if (spec.kind === "filter") {
    const ns = graph.nodes
      .filter((n) => matchFilter(n, spec.filter))
      .map((n) => n.id);
    return { nodes: ns, edges: [] };
  }
  if (spec.kind === "reverse_traverse") {
    const anchors = findAnchors(graph, spec.anchor);
    const seeds = anchors.map((a) => a.id);
    const { nodes, edges } = bfs(seeds, inc, spec.via, spec.depth, "src");
    return { nodes: [...nodes].sort(), edges: [...edges].sort() };
  }
  if (spec.kind === "multi_anchor_traverse") {
    const anchors = findAnchors(graph, spec.anchor);
    const seeds = anchors.map((a) => a.id);
    const { nodes, edges } = bfs(seeds, out, spec.via, spec.depth, "dst");
    return { nodes: [...nodes].sort(), edges: [...edges].sort() };
  }
  if (spec.kind === "path") {
    const srcs = findAnchors(graph, spec.from);
    const dsts = findAnchors(graph, spec.to);
    if (!srcs.length || !dsts.length) {
      return { nodes: [], edges: [], paths: [] };
    }
    const { nodes, edges } = findPath(
      srcs[0].id,
      dsts[0].id,
      out,
      spec.via,
      spec.depth,
    );
    if (!nodes) return { nodes: [], edges: [], paths: [] };
    return { nodes, edges, paths: [nodes] };
  }
  return { error: `unknown query kind: ${spec.kind}` };
}

// -------------------------------------------------------------------------
// Free-form DSL parser.
//
// Grammar (one line, AND-of-terms, whitespace separated):
//   term := key=value
//   key  ∈ { role, name, path, file, kind, id, from, via, depth, direction }
//
// Two query modes:
//   filter mode      — only filter terms; returns matching nodes
//   traversal mode   — both `from=<id>` and `via=<types>` given;
//                      runs BFS in direction (fwd default | rev) up to depth
// -------------------------------------------------------------------------

export function parseFreeform(queryStr) {
  if (!queryStr || !queryStr.trim()) return { error: "empty query" };
  const filterKeys = new Set(["role", "name", "path", "file", "kind", "id"]);
  const out = {
    filters: {},
    from: null,
    via: null,
    depth: 1,
    direction: "fwd",
  };
  for (const tok of queryStr.trim().split(/\s+/)) {
    const eq = tok.indexOf("=");
    if (eq < 0) return { error: `bad token: ${tok}` };
    const k = tok.slice(0, eq);
    const v = tok.slice(eq + 1);
    if (k === "from") out.from = v;
    else if (k === "via") out.via = v.split(",").filter(Boolean);
    else if (k === "depth") {
      const n = Number.parseInt(v, 10);
      if (Number.isNaN(n)) return { error: `depth not int: ${v}` };
      out.depth = n;
    } else if (k === "direction") {
      if (v !== "fwd" && v !== "rev") {
        return { error: `direction must be fwd|rev: ${v}` };
      }
      out.direction = v;
    } else if (filterKeys.has(k)) {
      out.filters[k] = v;
    } else {
      return { error: `unknown key: ${k}` };
    }
  }
  return out;
}

export function parseAndRunFreeform(graph, queryStr) {
  const parsed = parseFreeform(queryStr);
  if (parsed.error) return parsed;
  if (parsed.from && parsed.via) {
    const { inc, out } = buildAdjacency(graph);
    const adj = parsed.direction === "fwd" ? out : inc;
    const key = parsed.direction === "fwd" ? "dst" : "src";
    const { nodes, edges } = bfs(
      [parsed.from],
      adj,
      parsed.via,
      parsed.depth,
      key,
    );
    return { nodes: [...nodes].sort(), edges: [...edges].sort() };
  }
  const ns = graph.nodes
    .filter((n) => matchFilter(n, parsed.filters))
    .map((n) => n.id);
  return { nodes: ns, edges: [] };
}

// -------------------------------------------------------------------------
// Cytoscape viz helpers.
// -------------------------------------------------------------------------

const STEP_MS = 300;

export function clearQueryViz(cy) {
  if (!cy) return;
  cy.batch(() => {
    cy.elements().removeClass("match");
    cy.elements().removeClass("path-active");
    cy.elements().removeClass("query-dim");
  });
}

export function pulseNodes(cy, nodeIds, opts = {}) {
  if (!cy) return;
  const matchSet = new Set(nodeIds);
  cy.batch(() => {
    // Pass 1: bring every matched node + its incident edges back into view.
    // SA3 lesson #2 — filtered nodes carry `.dim` (display:none); we must
    // strip it so the query result actually renders.
    for (const id of nodeIds) {
      const ele = cy.getElementById(id);
      if (ele && ele.length) {
        ele.removeClass("dim");
        ele.removeClass("query-dim");
        ele.addClass("match");
      }
    }
    // Pass 2: dim every non-matching visible node for contrast (only if the
    // caller asked for it; default off so existing SA3 filters stay sane).
    if (opts.dimNonMatching) {
      cy.nodes().forEach((n) => {
        if (!matchSet.has(n.id())) {
          n.addClass("query-dim");
        }
      });
    }
  });
}

export async function animatePath(cy, edgeIds, opts = {}) {
  if (!cy || !edgeIds || !edgeIds.length) return;
  const stepMs = opts.stepMs || STEP_MS;
  for (const eid of edgeIds) {
    const ele = cy.getElementById(eid);
    if (ele && ele.length) {
      ele.removeClass("dim");
      ele.addClass("path-active");
      // Also un-dim endpoint nodes so the path is followable.
      ele.source().removeClass("dim");
      ele.target().removeClass("dim");
      ele.source().addClass("match");
      ele.target().addClass("match");
    }
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, stepMs));
  }
}

// -------------------------------------------------------------------------
// High-level: run a query end-to-end against a Cytoscape instance.
// Used by app.js to keep the query-panel wiring tiny.
// -------------------------------------------------------------------------

export async function runAndAnimate(cy, graph, result, opts = {}) {
  clearQueryViz(cy);
  if (!result || result.error) return;
  pulseNodes(cy, result.nodes || [], { dimNonMatching: !!opts.dimNonMatching });
  if (result.paths && result.paths.length) {
    // Multi-hop: animate per-edge along the path.
    await animatePath(cy, result.edges || [], opts);
  } else if (result.edges && result.edges.length) {
    // Single-hop: highlight all edges at once.
    cy.batch(() => {
      for (const eid of result.edges) {
        const ele = cy.getElementById(eid);
        if (ele && ele.length) {
          ele.removeClass("dim");
          ele.addClass("path-active");
        }
      }
    });
  }
}

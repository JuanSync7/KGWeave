# KGWeave Kuzu Port — Plan of Record

**Branch:** `kgweave/kuzu-port`
**Worktree:** `/home/kok-shew-juan/KGWeave-kuzu`
**Parent:** `main @ c16c2b1`

## Why
Promote the working SV AST extractor in `research/ast_experiment/src/` into the
canonical `src/knowledge_graph/` package, backed by **Kuzu** (embedded graph
DB), behind a **builder-agnostic facade**. SV is the first concrete builder;
the schema, query layer, and merge semantics are general so future builders
(of any input type) can register without core changes.

## Non-goals (v1)
- Any builder other than SV. SV-only inside `builders/sv/`.
- Schema migrations. v1 schema is baked; rebuild stores on schema change.
- LLM / prompt layer. RagWeave's concern; we only expose typed intents.
- Demo migration. The current JSON-fed demo stays pinned in `research/` until
  v1 is solid; we re-point it later.

## Hard invariants (test-enforced)

| # | Invariant | Where enforced |
|---|---|---|
| I1 | **Source round-trip:** every `:Origin.content` snapshot SHA matches the file at extraction time; `source_at(span)` returns bytes that exactly match the original byte range | `tests/knowledge_graph/store/test_origin_roundtrip.py` |
| I2 | **AST completeness:** for every SV fixture, `count(:Node where source='sv', origin=X)` in DB ≥ pyslang visit count for that file (every syntax node is represented) | `tests/knowledge_graph/builders/sv/test_completeness.py` |
| I3 | **Span lossless on every node:** every lifted node carries `(start_offset, end_offset)` and the byte slice from `:Origin.content` matches the pyslang `sourceRange.text` (or for Tokens, `trivia ⧺ rawText`) | `tests/knowledge_graph/builders/sv/test_span_roundtrip.py` |
| I4 | **Token-text round-trip preserved:** legacy `unlift.emit` still produces byte-identical SV for all fixtures (the existing oracle, ported intact) | `tests/knowledge_graph/builders/sv/legacy_tests/test_roundtrip.py` |
| I5 | **Connectivity:** `port→blob→port` (and equivalent) traversal queries return the same paths as the python `semantic/queries/` helpers on the fixture corpus | `tests/knowledge_graph/query/test_connectivity.py` |
| I6 | **Idempotent merge:** re-extracting an unchanged corpus produces zero row deltas; touching one file replaces only its subtree | `tests/knowledge_graph/store/test_incremental.py` |
| I7 | **Builder isolation:** writing rows with `source='other'` survives an SV re-extract unchanged | `tests/knowledge_graph/store/test_isolation.py` |
| I8 | **Read-only role for RawCypher:** any write Cypher (CREATE/MERGE/DELETE/SET/REMOVE) emitted via the public intent path is rejected | `tests/knowledge_graph/query/test_readonly.py` |

## Target package layout

```
src/knowledge_graph/
  __init__.py            # facade: open_store, register_builder, extract,
                         #         query, cypher, source_at
  schemas.py             # cross-builder Pydantic contracts (Span, NodeRef,
                         #         Path, QueryResult, …)
  shared/                # cross-cutting helpers (id namespacing, sha utils)
  store/
    __init__.py
    kuzu.py              # KGStore — open/close, conn pool, write/read txns
    schema.py            # base DDL (Origin, Node, Edge tables + indexes)
    snapshot.py          # ingest file → :Origin row
    spans.py             # source_at(span) helper
  builders/
    sv/                  # copy of research/ast_experiment/src + span capture
      __init__.py
      build.py
      lift.py
      unlift.py
      semantic/
      writer.py          # NEW: graph-dict → Kuzu writer
  query/
    __init__.py
    intents.py           # Pydantic QueryIntent union
    compiler.py          # intent → parameterized Cypher
    results.py           # typed result models
  connectors/
    __init__.py
    protocol.py          # Connector Protocol
  examples/
    quickstart.py        # end-to-end: extract SV corpus → query

tests/knowledge_graph/
  store/                 # phase A
  builders/sv/           # phase B + legacy_tests/ (vendored from research)
  query/                 # phase D + I5/I8
  facade/                # phase F
  fixtures/sv/           # copy of research/ast_experiment/corpus
```

Per CLAUDE.md: `schemas.py` for Pydantic, `shared/` for cross-module helpers,
public surface in `__init__.py`, default to `uv`.

## Schema (Cypher DDL — Kuzu)

Node tables (one logical `Node` polymorphic via `category` + `kind` strings):

```
NODE TABLE Origin (
  id STRING,
  uri STRING,
  sha256 STRING,
  content STRING,
  source STRING,
  corpus STRING,
  lang STRING,
  extracted_at TIMESTAMP,
  PRIMARY KEY (id)
);

NODE TABLE Node (
  id STRING,
  kind STRING,             -- builder-owned class string (e.g. "Module")
  category STRING,         -- 'semantic' | 'structural' | 'blob' | 'token'
                           --   | 'directive' | 'unresolved'
  name STRING,             -- optional logical name (Module name, Port name, …)
  source STRING,           -- builder id, e.g. 'sv'
  corpus STRING,
  origin_id STRING,        -- FK → Origin.id
  start_offset INT64,      -- byte offset; -1 if not span-bearing
  end_offset INT64,
  start_line INT32,
  end_line INT32,
  start_col INT32,
  end_col INT32,
  payload STRING,          -- JSON blob — builder-specific extras
  PRIMARY KEY (id)
);

NODE TABLE BlobPayload (
  sha256 STRING,
  json STRING,
  PRIMARY KEY (sha256)
);
```

Rel tables (edge type is the table; payload is per-table):

```
REL TABLE PARENT_OF   (FROM Node TO Node, ordinal INT32);      -- structural backbone
REL TABLE CONTAINS    (FROM Node TO Node);                      -- semantic containment
REL TABLE DRIVES      (FROM Node TO Node);
REL TABLE READS       (FROM Node TO Node);
REL TABLE SENSITIVE_TO (FROM Node TO Node, edge STRING);
REL TABLE INSTANTIATES (FROM Node TO Node);
REL TABLE OF_MODULE    (FROM Node TO Node);
REL TABLE CONNECTS     (FROM Node TO Node, instance STRING, port STRING);
REL TABLE PARAM_OVERRIDE (FROM Node TO Node, name STRING, value STRING);
REL TABLE CALLS        (FROM Node TO Node);
REL TABLE HAS_PORT     (FROM Node TO Node);
REL TABLE HAS_PARAM    (FROM Node TO Node);
REL TABLE HAS_NET      (FROM Node TO Node);
REL TABLE HAS_TYPEDEF  (FROM Node TO Node);
REL TABLE HAS_ENUM_VALUE (FROM Node TO Node, name STRING, typedef STRING);
REL TABLE HAS_MODPORT  (FROM Node TO Node);
REL TABLE HAS_FUNCTION (FROM Node TO Node);
REL TABLE HAS_GENERATE (FROM Node TO Node);
REL TABLE CONTAINS_BLOCK (FROM Node TO Node);
REL TABLE IN_ORIGIN     (FROM Node TO Origin);
REL TABLE HAS_PAYLOAD   (FROM Node TO BlobPayload);
```

**Auto-derived from SV semantic emit (Phase C.5).** Discovered programmatically
from the SV builder's emitted edge types on the full fixture corpus — these
rel tables were added to close the lossless gap (originally ~184 edges of 7721
were dropped into `edges_skipped_unknown_type`). The names are `UPPER_SNAKE` of
the dict edge `type`; payload columns track the dict-edge payload keys whose
values are meaningful. Edges with no semantic payload data are FROM Node TO
Node only.

```
# class hierarchy + OOP
REL TABLE EXTENDS                  (FROM Node TO Node, name STRING, params STRING);
REL TABLE IMPLEMENTS               (FROM Node TO Node, name STRING);
REL TABLE HAS_CLASS                (FROM Node TO Node);
REL TABLE HAS_CLASS_PROPERTY       (FROM Node TO Node);
REL TABLE HAS_METHOD               (FROM Node TO Node);
REL TABLE HAS_CONSTRAINT           (FROM Node TO Node);
REL TABLE HAS_INLINE_CONSTRAINT    (FROM Node TO Node);
REL TABLE HAS_TYPE_PARAM           (FROM Node TO Node);
REL TABLE HAS_LOCAL_VAR            (FROM Node TO Node);
REL TABLE HAS_FUNCTION_PORT        (FROM Node TO Node);
REL TABLE HAS_MEMBER               (FROM Node TO Node);
REL TABLE PROTOTYPES               (FROM Node TO Node);

# checker / assertion / property / sequence
REL TABLE HAS_CHECKER_INSTANCE     (FROM Node TO Node);
REL TABLE HAS_CHECKER_DATA         (FROM Node TO Node);
REL TABLE OF_CHECKER               (FROM Node TO Node, name STRING);
REL TABLE HAS_ASSERTION            (FROM Node TO Node);
REL TABLE HAS_ASSERTION_ITEM_PORT  (FROM Node TO Node);
REL TABLE HAS_PROPERTY             (FROM Node TO Node);
REL TABLE HAS_SEQUENCE             (FROM Node TO Node);
REL TABLE HAS_LET                  (FROM Node TO Node);
REL TABLE HAS_DEFAULT_DISABLE      (FROM Node TO Node);

# clocking + interface ref
REL TABLE HAS_CLOCKING             (FROM Node TO Node);
REL TABLE HAS_CLOCKING_ITEM        (FROM Node TO Node);
REL TABLE DEFAULT_CLOCKING         (FROM Node TO Node, name STRING);
REL TABLE REFERENCES_INTERFACE     (FROM Node TO Node, modport STRING);

# coverage
REL TABLE HAS_COVERGROUP           (FROM Node TO Node);
REL TABLE HAS_COVERPOINT           (FROM Node TO Node);
REL TABLE HAS_BINS                 (FROM Node TO Node);
REL TABLE HAS_CROSS                (FROM Node TO Node);

# DPI + package import/export
REL TABLE HAS_DPI_IMPORT           (FROM Node TO Node);
REL TABLE DPI_EXPORTS              (FROM Node TO Node, spec STRING, export_kind STRING, unresolved BOOLEAN);
REL TABLE IMPORTS                  (FROM Node TO Node, package STRING, item STRING, unresolved BOOLEAN);
REL TABLE IMPORTS_ITEM             (FROM Node TO Node, package STRING, symbol STRING);
REL TABLE EXPORTS_ALL              (FROM Node TO Node, wildcard BOOLEAN);
REL TABLE DECLARES                 (FROM Node TO Node, name STRING, kind STRING);

# bind / defparam
REL TABLE BIND_TARGET              (FROM Node TO Node, target STRING, target_module STRING, ordinal INT32, unresolved BOOLEAN);
REL TABLE BOUND_INTO               (FROM Node TO Node, instance_name STRING, scope STRING);
REL TABLE DEFPARAM_OVERRIDE        (FROM Node TO Node, hier_path STRING, value STRING, unresolved BOOLEAN);

# net decl + nettype + aliases + primitive
REL TABLE HAS_NET_DECL             (FROM Node TO Node);
REL TABLE HAS_NETTYPE              (FROM Node TO Node);
REL TABLE HAS_USER_DEFINED_NET_DECL (FROM Node TO Node);
REL TABLE ALIASES                  (FROM Node TO Node);
REL TABLE GROUPS_NET               (FROM Node TO Node);
REL TABLE GROUPS_PORT_REF          (FROM Node TO Node);
REL TABLE HAS_PRIMITIVE_INSTANCE   (FROM Node TO Node);

# procedural / event / misc
REL TABLE HAS_PROCEDURAL_ASSIGN    (FROM Node TO Node);
REL TABLE HAS_PROCEDURAL_FORCE     (FROM Node TO Node);
REL TABLE HAS_EVENT_TRIGGER        (FROM Node TO Node);
REL TABLE TRIGGERS                 (FROM Node TO Node);
REL TABLE HAS_GENVAR               (FROM Node TO Node);
REL TABLE HAS_TIMEUNITS            (FROM Node TO Node);
```

Lossless gap closed in Phase C.5 — see test
`tests/knowledge_graph/builders/sv/test_writer_full_edge_coverage.py`. The
writer also materializes `_unresolved.<name>` placeholder Node rows
(`category='unresolved'`) so edges with dangling endpoints stay
graph-traversable.

Indexes Kuzu auto-creates on PKs; we add secondary indexes (or rely on
Kuzu's column-store scan + filter) on `(source, corpus)`, `(kind)`,
`(name)`, `(origin_id, start_offset)`.

## Phase plan and validation gates

Each phase is dispatched to a subagent with a **self-contained brief**:
context, deliverable, files to write, TDD obligation, Ralph loop (re-validate,
patch gaps, iterate), the e2e test it must pass, and the report format.

### Phase A — store foundation
**Deliverable:** `src/knowledge_graph/store/` + tests pass.
**Gate (I1):** open store, snapshot a file into `:Origin`, call
`source_at(Span(origin_id, 50, 80))`, assert returned bytes == file[50:80].
Span round-trip over 100 random ranges on each fixture file.
**Out of scope:** any SV-specific code.

### Phase B — SV extractor port + span capture
**Deliverable:** `src/knowledge_graph/builders/sv/` with span fields on every
node in the graph-dict output. Legacy tests pass against the copy.
**Gate (I2 + I3 + I4):** completeness + span round-trip + token-text
round-trip all green on the SV fixture corpus.
**Out of scope:** writing to Kuzu (Phase C).

### Phase C — dict→Kuzu writer
**Deliverable:** `builders/sv/writer.py` and the integration that takes the
graph-dict from B and emits rows in the schema from A.
**Gate (I5 prelim):** for the fixture corpus, `MATCH (m:Node {kind:'Module'})
RETURN count(*)` equals the count in the graph-dict; same for every edge
type; one connectivity query (port→DRIVES→port) returns identical paths to
the python `semantic/queries/` helper.

**(main agent compacts here — phases A/B/C are the bulk)**

### Phase D — intents + compiler
**Deliverable:** `query/intents.py`, `query/compiler.py`, `query/results.py`.
**Gate (I8 + golden tests):** every intent compiles to deterministic
parameterized Cypher; RawCypher rejects writes; on the fixture corpus,
each intent type returns the documented shape.

### Phase E — incremental merge — **COMPLETE**
**Deliverable:** `store/kuzu.py` extract path keyed on
`(uri, source, corpus)` (live origin) + `sha256` (change detection).
Original plan said `(source, corpus, origin_id, origin_sha256)`; the
implementation keys on `(uri, source, corpus)` because `origin_id`
embeds the sha and so cannot be a stable replacement key. Behaviour
matches the original intent.
**Gate (I6 + I7):** double-extract → zero deltas; touch-one-file → only its
subtree replaced; `source='probe'` hand-written rows survive an SV
re-extract.

### Phase F — facade + connector protocol + e2e — **COMPLETE**
**Deliverable:** `src/knowledge_graph/__init__.py` (full public API),
`connectors/protocol.py` (Connector Protocol), `connectors/__init__.py`
(trivial `SemanticSelfRefConnector` to exercise the registry),
`examples/quickstart.py` (runnable end-to-end).
**Gate:** `python -m knowledge_graph.examples.quickstart` runs end-to-end
against the fixture, exercising open_store → register SV builder → extract
→ intent query → raw Cypher query → source_at. Enforced by
`tests/knowledge_graph/facade/`.

## Subagent operating contract

Each phase subagent receives:

1. **Context** — what phases preceded it, what's already on disk.
2. **End goal** — a runnable, falsifiable validation gate (the I-numbers above).
3. **Files to write** — explicit paths.
4. **TDD obligation** — write the failing test first, drive code to green,
   refactor. No "I'll add tests after."
5. **Ralph loop** — after green, re-read the goal, scan for unhandled edge
   cases (empty input, multi-file, unicode in source, missing optional pyslang
   fields, etc.), add tests for each gap, iterate until convergence.
6. **End-to-end test obligation** — at least one test that runs the whole
   stack from public entry-point through the validation gate. No
   mocked-Kuzu tests; use a temp `.kuzu` directory.
7. **Report format** — at completion, report:
   - Files added/modified.
   - Tests added (with names and what each asserts).
   - Validation gate command(s) and their output.
   - Known gaps / things deferred.
   - Anything surprising or counter to the plan that the main agent should
     verify.

## Dependencies between phases

```
A ─┬─→ C ─→ D ─→ F
   │       ↑
B ─┴───────┘
            ↓
            E (uses A,B,C; runs before F)
```

A and B are independent (parallel-able).
C depends on A + B.
D depends on A + C (needs schema and at least one row to query).
E depends on A + B + C.
F depends on everything.

## Out-of-band

- `uv add kuzu` lands in Phase A.
- `pyproject.toml` package config may need a `knowledge_graph` entry — Phase A
  to ensure `import knowledge_graph` works inside the worktree.
- Each subagent should run `uv sync` once at the top.
- All test commands must use `uv run pytest` from the worktree root.

# Migration: RagWeave → KGWeave

The KG package currently lives in-tree at `RagWeave/src/knowledge_graph/`.
This document tracks the extraction sequence agreed with RagWeave team.

## Boundary Decision

**Option A — RagWeave owns lifecycle.**
RagWeave treats KGWeave as a black box via three Pydantic-typed clients:

- `KGAdminClient` — `count_by_source_key`, `delete_by_source_key`, `health`
- `KGIngestClient` — `extract_and_commit(source_key, clean_text, meta) -> KGIngestResult`
- `KGQueryClient` — `expand`, `get_term_index`, `get_graph_context`

## Architectural Move

KG ingestion moves out of the embedding LangGraph and becomes a sibling
Phase 2 consumer of `CleanDocumentStore`:

```
Phase 1 (parsing) ──▶ CleanDocumentStore ──┬──▶ Phase 2a: embedding pipeline (RagWeave)
                                            └──▶ Phase 2b: kg pipeline    (KGWeave)
```

## Sequence

### Prep (in-place inside RagWeave)

1. **LLMClient Protocol + DI** — remove `src.platform.llm` imports from KG;
   inject via constructor.
2. **KGConfig.from_env()** — KG owns its env schema; `config.settings` keeps
   thin re-export shims.
3. **`get_term_index()` facade** — replace `query_processor._get_kg_terms`
   direct file read.
4. **`KGAdminClient` Protocol** — formalize lifecycle contract; lifecycle
   uses Protocol, not concrete backend.
5. **`extract_and_commit` ingest entry point** — collapse the two embedding
   nodes into one call.
6. **Split embedding pipeline** — KG nodes leave embedding LangGraph; new
   parallel Phase 2b activity reads from `CleanDocumentStore`.

### Extract

7. Move `src/knowledge_graph/`, `tests/knowledge_graph/`, `evals/knowledge_graph/`,
   `docs/knowledge_graph/` into KGWeave.
8. Add as submodule under `RagWeave/submodules/kgweave/`; install with
   `uv pip install -e ./submodules/kgweave`.
9. Rewrite `from src.knowledge_graph` → `from kgweave`. Keep
   `src/knowledge_graph/__init__.py` as a re-export shim during cutover.
10. Delete `src/core/knowledge_graph.py` legacy shim.

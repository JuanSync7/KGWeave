# KGWeave

Knowledge graph subsystem extracted from RagWeave. Owns entity extraction,
graph storage, community detection, and query expansion behind a stable
public API.

Consumed by RagWeave (and other RAG projects) via the `KGAdminClient`,
`KGIngestClient`, and `KGQueryClient` Pydantic-typed contracts exported
from `kgweave` (formerly `src.knowledge_graph`).

## Status

Pre-extraction scaffold. The live KG code currently lives in
`RagWeave/src/knowledge_graph/`. This repo is the target landing zone:
the directory structure mirrors RagWeave per project convention.

## Layout

| Directory | Purpose |
| --- | --- |
| `src/knowledge_graph/` | Package source (extraction, backends, query, community, export, resolution) |
| `tests/` | Unit, integration, contract tests |
| `docs/` | Engineering guide, architecture, spec, design |
| `scripts/` | Operational scripts (benchmarks, migrations, smoke) |
| `config/` | Runtime config (kg_schema.yaml, settings) |
| `evals/` | Eval harnesses and golden sets |
| `prompts/` | LLM prompts (extraction, summarization) |
| `containers/` | Container/runtime definitions |
| `ops/` | Operational runbooks |

## Public Contract

KGWeave exposes three Pydantic-typed clients. RagWeave (Option A: lifecycle
owner) treats KGWeave as a black box via these:

- `KGAdminClient` — `count_by_source_key`, `delete_by_source_key`, `health`
- `KGIngestClient` — `extract_and_commit(source_key, clean_text, meta) -> KGIngestResult`
- `KGQueryClient` — `expand`, `get_term_index`, `get_graph_context`

## Migration Plan

See `docs/MIGRATION.md` for the in-place prep → extract sequence.

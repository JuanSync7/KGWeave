# Project Navigation Protocol

This project uses **context-agent** for hierarchical context management.
Every source file has an `@summary` block at the top, and every directory has a `README.md`.

## How to Navigate

1. Start at the root `README.md`.
2. Read the directory `README.md` for the area you're working in.
3. Read the `@summary` block at the top of source files before diving in.
4. Only then load full source.

## Public Contract

KGWeave is consumed by RagWeave (and other RAG projects) via Pydantic-typed
clients only. Never import internal modules from outside the `src/knowledge_graph/`
package — go through the facade in `src/knowledge_graph/__init__.py`.

## Implementation Conventions

Follow the same conventions as RagWeave:

- PEP 8 + module/function docstrings
- `schemas.py` for Pydantic contracts, `utils.py` for deterministic helpers,
  `common/` for cross-module shared code
- Thin public API facade module — stable import surface
- Configuration via typed `KGConfig` dataclass populated from env
- Tests co-located in `tests/<area>/`
- Update directory `README.md` and `docs/` when structure changes
- Default to `uv` for package management (Dockerfiles, CI, scripts)

## Extraction Status

This is the target directory for the KG extraction from RagWeave. Until the
extraction is complete, the live code lives at `~/RagWeave/src/knowledge_graph/`.
See `docs/MIGRATION.md`.

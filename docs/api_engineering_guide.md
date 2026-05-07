# KGWeave HTTP API — Engineering Guide

<!-- @summary
Engineering guide for the KGWeave HTTP API (Step C). Covers architecture,
endpoints, configuration, deployment, and how to extend the API.
@end-summary -->

## Overview

The HTTP API is the third KGWeave product surface (after the worker fleet
and the Python library). It exposes the **read-side** knowledge-graph
queries — expansion, term-index lookup, entity probe, path-pattern
evaluation — to non-Python consumers and external clients.

Writes are **not** exposed: ingest still flows through the Temporal worker
on `kgweave-default` for durability and retry semantics.

## Layout

```
src/kgweave/
├── contracts/
│   └── http.py                 # Pydantic v2 wire schemas
├── service/
│   └── query_service.py        # KGQueryService ABC + DefaultKGQueryService
├── api/
│   ├── app.py                  # create_app() factory
│   ├── deps.py                 # service injection + bearer-token gate
│   ├── main.py                 # uvicorn entry: kgweave.api.main:app
│   └── routes/
│       ├── health.py           # GET  /v1/health         (no auth)
│       ├── expand.py           # POST /v1/expand
│       ├── term_index.py       # POST /v1/term-index/match
│       ├── entities.py         # GET  /v1/entities/{key}
│       └── paths.py            # POST /v1/paths
└── client/
    ├── factory.py              # get_client(): in-process or HTTP
    └── http_client.py          # HTTPKGQueryService (httpx)
```

## Endpoints

| Method | Path | Auth | Body / Params | Returns |
|---|---|---|---|---|
| GET  | `/v1/health` | — | — | `HealthResponse` |
| POST | `/v1/expand` | bearer | `ExpandRequest{query, depth?}` | `ExpandResponse{terms, graph_context}` |
| POST | `/v1/term-index/match` | bearer | `TermMatchRequest{words[]}` | `TermMatchResponse{matches}` |
| GET  | `/v1/entities/{key}` | bearer | path key | `EntityResponse` (404 → `entity_not_found`) |
| POST | `/v1/paths` | bearer | `PathRequest{seed_entity, patterns}` | `PathResponse{results[]}` |

OpenAPI schema is auto-generated and served at `/openapi.json`; Swagger UI
at `/docs`. The wire models live in `kgweave.contracts.http` and are
re-exported from `kgweave.contracts`.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `KGWEAVE_API_HOST` | `0.0.0.0` | Uvicorn bind host |
| `KGWEAVE_API_PORT` | `8080` | Uvicorn bind port |
| `KGWEAVE_API_WORKERS` | `1` | Uvicorn worker count |
| `KGWEAVE_API_TOKEN` | unset | Bearer token (unset = open access) |
| `KG_GRAPH_PATH` | from `KGConfig` | Path to graph file |

## Deployment

### Container

`containers/Dockerfile.kgweave-api` (slim, two-stage, uv-based) installs
the `[api]` extra and runs `uvicorn kgweave.api.main:app`. The base image
matches the worker; only the CMD differs.

### Compose (RagWeave-side)

```yaml
kgweave-api:
  profiles: ["kgweave", "kgweave-api"]
  image: ghcr.io/juansync7/kgweave-api:${KGWEAVE_IMAGE_TAG:-latest}
  build:
    context: ${KGWEAVE_REPO_PATH:-../KGWeave}
    dockerfile: containers/Dockerfile.kgweave-api
  ports: ["${KGWEAVE_API_HOST_PORT:-8090}:8080"]
  environment:
    - KG_GRAPH_PATH=${KG_GRAPH_PATH:-/data/graph.json}
    - KGWEAVE_API_TOKEN=${KGWEAVE_API_TOKEN:-}
  volumes:
    - kgweave-graph:/data:ro
```

Read-only volume — the API never mutates the graph. Scale horizontally
by running multiple replicas; staleness is bounded by Phase 2b commit
cadence.

## Authentication

Single trust boundary. `require_auth` (in `kgweave.api.deps`) reads
`KGWEAVE_API_TOKEN`; when set, every protected route requires
`Authorization: Bearer <token>`. `/v1/health` is intentionally
unauthenticated for liveness probes.

## Extending

To add a new endpoint:

1. Add the request/response models in `kgweave/contracts/http.py` and
   re-export them in `kgweave/contracts/__init__.py`.
2. Add the abstract method on `KGQueryService` in
   `kgweave/service/query_service.py`, plus the default in-process
   implementation.
3. Add a route module under `kgweave/api/routes/`, register it in
   `routes/__init__.py`. Use `dependencies=[AuthDep]` for protected
   routes.
4. Mirror the method on `HTTPKGQueryService` so the `kgweave.client`
   facade stays in sync.
5. Add tests under `tests/api/` (contract + endpoint + http-client
   round trip).

## Client facade

`kgweave.client.get_client()` returns the right `KGQueryService` for the
process — the in-process default, or `HTTPKGQueryService` when
`KGWEAVE_API_URL` is set. Consumers (including future RagWeave callers)
can call `get_client().expand(...)` without caring about transport.

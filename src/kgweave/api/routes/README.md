<!-- @summary
HTTP route modules for the KGWeave v1 API. One module per resource;
all are registered in routes/__init__.py.
@end-summary -->

# API Routes

| File | Method + Path | Auth |
|---|---|---|
| `health.py` | `GET /v1/health` | none |
| `expand.py` | `POST /v1/expand` | bearer |
| `term_index.py` | `POST /v1/term-index/match` | bearer |
| `entities.py` | `GET /v1/entities/{key}` | bearer |
| `paths.py` | `POST /v1/paths` | bearer |

Each handler:

- Accepts the matching `kgweave.contracts.http` request model
- Resolves the active `KGQueryService` via `ServiceDep`
- Returns the matching response model (FastAPI handles serialization)

Errors raised by the service layer are translated by handlers in
`kgweave.api.app`:

- `EntityNotFound` → `404 entity_not_found`
- `ValueError` → `400 invalid_request`

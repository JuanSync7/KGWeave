"""KGWeave public facade.

This module is the **only** stable import surface for KGWeave consumers.
Internal sibling packages (``store``, ``builders``, ``query``,
``connectors``) are not part of the API contract — go through the names
re-exported here.

See ``docs/plans/KUZU_PORT_PLAN.md`` Phase F for the design contract.

Public entry points
-------------------

* :func:`open_store`         — open (or create) a Kuzu-backed store.
* :func:`register_builder`   — register an extractor under a ``source`` name.
* :func:`extract`            — dispatch extraction to a registered builder.
* :func:`query`              — typed-intent query through the runner.
* :func:`cypher`             — read-only raw Cypher escape hatch.
* :func:`source_at`          — fetch byte-slice of an origin.
* :func:`register_connector` — register a derived-edge synthesizer.
* :func:`run_connectors`     — execute registered connectors.

The SV builder is auto-registered under the source name ``'sv'`` as a
side-effect of importing this module; consumers don't need a separate
registration call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from knowledge_graph.builders.md import extract as _md_extract
from knowledge_graph.builders.py import extract as _py_extract
from knowledge_graph.builders.sv import (
    ExtractStats,
    extract as _sv_extract,
)
from knowledge_graph.connectors import (
    SemanticSelfRefConnector,
    SvMarkdownReferenceConnector,
)
from knowledge_graph.connectors.py_decorator_semantics import (
    PyDecoratorSemanticsConnector,
)
from knowledge_graph.connectors.py_scope_resolution import (
    PyScopeResolutionConnector,
)
from knowledge_graph.connectors.py_descriptor_semantics import (
    PyDescriptorSemanticsConnector,
)
from knowledge_graph.connectors.py_set_name_semantics import (
    PySetNameSemanticsConnector,
)
from knowledge_graph.connectors.py_md import PyMarkdownReferenceConnector
from knowledge_graph.connectors.protocol import Connector
from knowledge_graph.query import (
    AmbiguousAnchor,
    AnchorRef,
    EdgeType,
    FilterIntent,
    NeighborhoodIntent,
    QueryIntent,
    QueryResult,
    RawCypher,
    ReadOnlyViolation,
    TraverseIntent,
    run_intent,
)
from knowledge_graph.query.results import EdgeView, NodeView, PathView
from knowledge_graph.schemas import NodeRef, OriginRef, Span
from knowledge_graph.store import KGStore
from knowledge_graph.store.schema import (
    KGWEAVE_SCHEMA_VERSION,
    SchemaVersionMismatch,
)

__version__ = "0.1.0a2"


# --------------------------------------------------------------- errors


class UnknownBuilder(KeyError):
    """Raised by :func:`extract` when ``source`` has no registered builder."""


class BuilderConflict(ValueError):
    """Raised by :func:`register_builder` for a name collision with a
    *different* extract function."""


class ConnectorRequirementError(LookupError):
    """Raised by :func:`run_connectors` when a connector's ``requires``
    source string is not present in the store."""


# --------------------------------------------------------------- registries


_BUILDERS: dict[str, Callable[..., Any]] = {}
_CONNECTORS: dict[str, Connector] = {}


def register_builder(name: str, extract_fn: Callable[..., Any]) -> None:
    """Register ``extract_fn`` as the builder for source ``name``.

    Idempotent: registering the same ``(name, fn)`` twice is a no-op.
    Re-registering the same name with a *different* fn raises
    :class:`BuilderConflict`.
    """
    existing = _BUILDERS.get(name)
    if existing is None:
        _BUILDERS[name] = extract_fn
        return
    if existing is extract_fn:
        return
    raise BuilderConflict(
        f"builder {name!r} already registered to a different function"
    )


def register_connector(connector: Connector) -> None:
    """Register a :class:`Connector` under its ``name`` attribute.

    Re-registering an identical instance, or any other instance of the
    **same connector class** under the same name, is a no-op (v1.5-#5).
    Connectors are pure dispatch objects with no per-instance state in
    practice, so same-class equivalence is the right granularity. A
    *different* connector class under the same name still raises
    :class:`BuilderConflict` -- distinct implementations under one name
    is a real conflict the caller must resolve.
    """
    existing = _CONNECTORS.get(connector.name)
    if existing is None:
        _CONNECTORS[connector.name] = connector
        return
    if existing is connector:
        return
    if type(existing) is type(connector):
        # Same-class re-registration from a fresh fixture/instance is a
        # no-op. Keep the originally-registered object so identity-based
        # downstream caches stay stable.
        return
    raise BuilderConflict(
        f"connector {connector.name!r} already registered to a different object"
    )


# --------------------------------------------------------------- entry points


def open_store(
    path: str | Path, *, max_db_size_bytes: int | None = None
) -> KGStore:
    """Open (or create) a Kuzu-backed store at ``path``.

    ``max_db_size_bytes`` forwards to :meth:`KGStore.open`; see that
    method for the rationale (v1.5-#1, ext4 sparse-allocation cap).
    """
    return KGStore.open(path, max_db_size_bytes=max_db_size_bytes)


def extract(
    store: KGStore,
    *,
    source: str,
    corpus: str,
    paths: list[Path],
    **builder_kwargs: Any,
) -> ExtractStats:
    """Dispatch extraction to the builder registered for ``source``.

    Raises :class:`UnknownBuilder` if no builder is registered.

    The SV builder's ``extract`` returns a 3-tuple
    ``(graph, origins, ExtractStats)``; for the facade we strip the
    internal payload and return only the :class:`ExtractStats`. Other
    builders are expected to follow the same convention — return a tuple
    whose **last element** is an ``ExtractStats``, or return one
    directly.
    """
    fn = _BUILDERS.get(source)
    if fn is None:
        raise UnknownBuilder(f"no builder registered for source {source!r}")

    if not paths:
        # Per Phase F contract: empty paths is a no-op that returns
        # zeroed stats without invoking the builder.
        return ExtractStats()

    result = fn(store, list(paths), source=source, corpus=corpus, **builder_kwargs)
    if isinstance(result, ExtractStats):
        return result
    if isinstance(result, tuple) and result and isinstance(result[-1], ExtractStats):
        return result[-1]
    raise TypeError(
        f"builder {source!r} returned unsupported result type: {type(result).__name__}"
    )


def query(store: KGStore, intent: QueryIntent) -> QueryResult:
    """Run a typed :class:`QueryIntent` and return a :class:`QueryResult`."""
    return run_intent(store, intent)


def cypher(
    store: KGStore,
    cypher_text: str,
    parameters: dict[str, Any] | None = None,
) -> QueryResult:
    """Run a read-only raw Cypher query.

    Internally wraps :class:`RawCypher` and routes through
    :func:`run_intent`, so :class:`ReadOnlyViolation` enforcement applies.
    """
    intent = RawCypher(cypher=cypher_text, parameters=parameters or {})
    return run_intent(store, intent)


def source_at(
    store: KGStore, origin_id: str, start: int, end: int
) -> bytes:
    """Return ``content[start:end]`` for the named origin."""
    return store.source_at(origin_id, start, end)


def prune_orphaned_origins(
    store: KGStore,
    *,
    source: str | None = None,
    corpus: str | None = None,
) -> int:
    """Sweep ``:Origin`` rows that own zero ``:Node`` children.

    Thin facade wrapper over :meth:`KGStore.prune_orphaned_origins`.
    Returns the number of Origins deleted; idempotent on a clean store.
    See the method docstring for scoping and isolation semantics.
    """
    return store.prune_orphaned_origins(source=source, corpus=corpus)


def run_connectors(
    store: KGStore, *, only: list[str] | None = None
) -> dict[str, int]:
    """Execute registered connectors against ``store``.

    Returns a ``{connector_name: edges_written}`` map. If ``only`` is
    given, runs just those connectors (in input order). A connector
    whose ``requires`` source string is absent from the store raises
    :class:`ConnectorRequirementError`.
    """
    selected: list[Connector]
    if only is None:
        selected = list(_CONNECTORS.values())
    else:
        missing = [n for n in only if n not in _CONNECTORS]
        if missing:
            raise UnknownBuilder(
                f"connector(s) not registered: {missing!r}"
            )
        selected = [_CONNECTORS[n] for n in only]

    present_sources = _present_sources(store)
    out: dict[str, int] = {}
    for c in selected:
        missing_sources = [s for s in c.requires if s not in present_sources]
        if missing_sources:
            raise ConnectorRequirementError(
                f"connector {c.name!r} requires sources {missing_sources!r} "
                f"not present in store (present: {sorted(present_sources)!r})"
            )
        out[c.name] = c.synthesize(store)
    return out


def _present_sources(store: KGStore) -> set[str]:
    """Return the distinct ``source`` strings present on any ``:Node`` row."""
    res = store.conn.execute(
        "MATCH (n:Node) RETURN DISTINCT n.source"
    )
    out: set[str] = set()
    while res.has_next():
        row = res.get_next()
        if row and row[0]:
            out.add(row[0])
    return out


# --------------------------------------------------------------- auto-register

# Built-in SV builder under the standard source name.
register_builder("sv", _sv_extract)
# Built-in MD builder (v1.2 — minimal lift: document/heading/code-fence/inline-code).
register_builder("md", _md_extract)
# Built-in Python builder (v1.5-#3 — libcst lift: module/function/class/import).
register_builder("py", _py_extract)


__all__ = [
    "__version__",
    # entry points
    "open_store",
    "register_builder",
    "extract",
    "query",
    "cypher",
    "source_at",
    "prune_orphaned_origins",
    "register_connector",
    "run_connectors",
    # core types
    "KGStore",
    "Span",
    "OriginRef",
    "NodeRef",
    "NodeView",
    "EdgeView",
    "PathView",
    "QueryResult",
    "FilterIntent",
    "TraverseIntent",
    "NeighborhoodIntent",
    "RawCypher",
    "QueryIntent",
    "AnchorRef",
    "EdgeType",
    "ExtractStats",
    "Connector",
    "SemanticSelfRefConnector",
    "SvMarkdownReferenceConnector",
    "PyMarkdownReferenceConnector",
    "PyDecoratorSemanticsConnector",
    "PyScopeResolutionConnector",
    "PyDescriptorSemanticsConnector",
    "PySetNameSemanticsConnector",
    # errors
    "ReadOnlyViolation",
    "AmbiguousAnchor",
    "UnknownBuilder",
    "BuilderConflict",
    "ConnectorRequirementError",
    "SchemaVersionMismatch",
    # schema-version surface
    "KGWEAVE_SCHEMA_VERSION",
]

# @summary
# Cached entity-term index used by retrieval-side query reformulation.
# Walks the configured graph backend, filters noisy entries, builds a
# word -> [terms] inverted index. Facade entry point: get_term_index().
# Exports: get_term_index, clear_term_index_cache, KGTermIndex
# Deps: collections, logging, time, src.knowledge_graph.backend
# @end-summary
"""Term-index facade for query-time reformulation.

Exposes a stable API so retrieval consumers do not read the graph storage
file directly. The cached snapshot is populated on first call and survives
the lifetime of the process; ``clear_term_index_cache()`` is provided for
tests and for force-reload after re-extraction runs.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("rag.knowledge_graph.query.term_index")

__all__ = ["KGTermIndex", "get_term_index", "clear_term_index_cache"]

_MIN_TERM_LEN = 2
_MAX_TERM_LEN = 60
_MIN_WORD_LEN = 3


@dataclass
class KGTermIndex:
    """Snapshot of entity terms for query reformulation.

    Attributes:
        terms: Canonical entity names ordered by mention count (desc).
        word_index: Lowercase word → list of terms containing that word.
    """

    terms: List[str] = field(default_factory=list)
    word_index: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))


_cached: Optional[KGTermIndex] = None


def clear_term_index_cache() -> None:
    """Drop the cached term index. Next ``get_term_index()`` call rebuilds it."""
    global _cached
    _cached = None


def get_term_index() -> KGTermIndex:
    """Return the process-wide term index, building it on first call.

    The index is built by walking the configured graph backend, keeping
    entities whose canonical name is between :data:`_MIN_TERM_LEN` and
    :data:`_MAX_TERM_LEN` characters with ``mention_count >= 1``. Terms are
    ordered by descending mention count; the inverted word index lowercases
    each word and skips words shorter than :data:`_MIN_WORD_LEN`.

    Returns:
        A populated :class:`KGTermIndex`. When the backend is unavailable
        (graph file missing, init failure) the index is empty rather than
        raising.
    """
    global _cached
    if _cached is not None:
        return _cached

    t0 = time.perf_counter()
    index = KGTermIndex()

    try:
        from kgweave.knowledge_graph import get_graph_backend  # noqa: PLC0415

        backend = get_graph_backend()
        entities = backend.get_all_entities()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("get_term_index: backend unavailable (%s)", exc)
        _cached = index
        return index

    valid = [
        e for e in entities
        if _MIN_TERM_LEN <= len(e.name) <= _MAX_TERM_LEN
        and getattr(e, "mention_count", 0) >= 1
    ]
    valid.sort(key=lambda e: getattr(e, "mention_count", 0), reverse=True)
    index.terms = [e.name for e in valid]

    for term in index.terms:
        for word in term.lower().split():
            if len(word) >= _MIN_WORD_LEN:
                index.word_index[word].append(term)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Loaded %d KG terms (%d index keys) in %.1fms",
        len(index.terms),
        len(index.word_index),
        elapsed_ms,
    )
    _cached = index
    return index

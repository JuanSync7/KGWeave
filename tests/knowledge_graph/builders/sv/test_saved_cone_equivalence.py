"""Anti-circular equivalence: the store-backed ``saved_query`` cone equals
the internal dict-walk oracle on the live SV corpus.

``flow.cone_of_influence`` (dict walk over the promoted graph) is the
*oracle*. ``saved_query(store, "cone_of_influence", target=...)`` reproduces
the same backward-reachability set **independently** via an iterative Cypher
frontier over the persisted store. The two must agree node-for-node — which
is only a meaningful test because the saved query does NOT call the oracle.
"""

from __future__ import annotations

import pytest

from knowledge_graph import saved_query
from knowledge_graph.query import SavedQueryError
from knowledge_graph.builders.sv.semantic.queries.connectivity import (
    find_by_name,
)
from knowledge_graph.builders.sv.semantic.queries.flow import (
    cone_of_influence,
)

# Signal targets present in the fixture corpus (fifo.sv). Fully-qualified
# where a bare leaf would be ambiguous across modules.
CONE_TARGETS = [
    "fifo.count",
    "fifo.dout",
    "fifo.full",
    "fifo.empty",
    "fifo.wr_ptr",
    "fifo.rd_ptr",
]


@pytest.mark.parametrize("target", CONE_TARGETS)
def test_saved_cone_matches_flow_oracle(sv_corpus_store, target):
    store, graph, _origins, _stats = sv_corpus_store

    # Oracle must resolve this target, else the case is vacuous.
    assert find_by_name(graph, target) is not None, (
        f"oracle could not resolve {target!r}"
    )
    oracle_ids = cone_of_influence(graph, target)
    assert oracle_ids, f"oracle cone for {target!r} is unexpectedly empty"

    result = saved_query(store, "cone_of_influence", target=target)
    store_ids = {n.id for n in result.nodes}

    assert store_ids == oracle_ids, (
        f"cone mismatch for {target!r}\n"
        f"  only-in-store:  {sorted(store_ids - oracle_ids)}\n"
        f"  only-in-oracle: {sorted(oracle_ids - store_ids)}"
    )


def test_saved_cone_includes_target(sv_corpus_store):
    store, graph, _origins, _stats = sv_corpus_store
    target = "fifo.count"
    tid = find_by_name(graph, target)["id"]
    result = saved_query(store, "cone_of_influence", target=target)
    assert tid in {n.id for n in result.nodes}


def test_saved_cone_unresolved_target_is_empty_success(sv_corpus_store):
    store, *_ = sv_corpus_store
    result = saved_query(store, "cone_of_influence", target="no_such_signal_xyz")
    assert result.nodes == []
    assert result.intent_kind == "saved"


def test_unknown_saved_query_raises(sv_corpus_store):
    store, *_ = sv_corpus_store
    with pytest.raises(SavedQueryError) as exc:
        saved_query(store, "cone_of_influnce", target="fifo.count")  # typo
    # difflib suggestion points at the real name.
    assert exc.value.suggestion == "cone_of_influence"

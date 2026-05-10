"""Tests for transitive coverage propagation via instantiates ancestry.

A node is transitively covered if it has a direct ``tests_module`` edge
meeting the confidence floor, OR any of its ancestors via ``instantiates``
edges does.
"""

from __future__ import annotations

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity, Triple
from kgweave.knowledge_graph.queries import coverage_gaps_by_target_transitive


def _mk(name: str, type_: str, is_test: bool | None = None) -> Entity:
    return Entity(name=name, type=type_, is_test=is_test)


def _seed(backend, entities, triples):
    backend.upsert_entities(entities)
    backend.upsert_triples(triples)


def test_direct_coverage_still_no_gap():
    backend = NetworkXBackend()
    _seed(
        backend,
        [_mk("modA", "RTL_Module"), _mk("t1", "SW_Test", is_test=True)],
        [
            Triple(
                subject="t1",
                predicate="tests_module",
                object="modA",
                confidence_tier="high",
                resolved=True,
            )
        ],
    )
    assert coverage_gaps_by_target_transitive(backend, min_confidence="medium") == []


def test_one_hop_ancestor_covered_means_no_gap():
    backend = NetworkXBackend()
    _seed(
        backend,
        [
            _mk("parent", "RTL_Module"),
            _mk("child", "RTL_Module"),
            _mk("t1", "SW_Test", is_test=True),
        ],
        [
            Triple(subject="parent", predicate="instantiates", object="child"),
            Triple(
                subject="t1",
                predicate="tests_module",
                object="parent",
                confidence_tier="high",
                resolved=True,
            ),
        ],
    )
    assert coverage_gaps_by_target_transitive(backend, min_confidence="medium") == []


def test_two_hop_ancestor_covered_means_no_gap():
    backend = NetworkXBackend()
    _seed(
        backend,
        [
            _mk("gp", "RTL_Module"),
            _mk("p", "RTL_Module"),
            _mk("c", "RTL_Module"),
            _mk("t1", "SW_Test", is_test=True),
        ],
        [
            Triple(subject="gp", predicate="instantiates", object="p"),
            Triple(subject="p", predicate="instantiates", object="c"),
            Triple(
                subject="t1",
                predicate="tests_module",
                object="gp",
                confidence_tier="high",
                resolved=True,
            ),
        ],
    )
    assert coverage_gaps_by_target_transitive(backend, min_confidence="medium") == []


def test_isolated_module_with_no_ancestor_coverage_is_gap():
    backend = NetworkXBackend()
    _seed(backend, [_mk("orphan", "RTL_Module")], [])
    assert coverage_gaps_by_target_transitive(backend, min_confidence="medium") == [
        "orphan"
    ]


def test_uncovered_sibling_subtree_is_gap():
    backend = NetworkXBackend()
    _seed(
        backend,
        [
            _mk("A", "RTL_Module"),
            _mk("B", "RTL_Module"),
            _mk("a_child", "RTL_Module"),
            _mk("b_child", "RTL_Module"),
            _mk("t1", "SW_Test", is_test=True),
        ],
        [
            Triple(subject="A", predicate="instantiates", object="a_child"),
            Triple(subject="B", predicate="instantiates", object="b_child"),
            Triple(
                subject="t1",
                predicate="tests_module",
                object="A",
                confidence_tier="high",
                resolved=True,
            ),
        ],
    )
    gaps = coverage_gaps_by_target_transitive(backend, min_confidence="medium")
    assert gaps == ["B", "b_child"]


def test_min_confidence_floor_applies_at_ancestor_level():
    backend = NetworkXBackend()
    _seed(
        backend,
        [
            _mk("parent", "RTL_Module"),
            _mk("child", "RTL_Module"),
            _mk("t1", "SW_Test", is_test=True),
        ],
        [
            Triple(subject="parent", predicate="instantiates", object="child"),
            Triple(
                subject="t1",
                predicate="tests_module",
                object="parent",
                confidence_tier="low",
                resolved=True,
            ),
        ],
    )
    gaps = coverage_gaps_by_target_transitive(backend, min_confidence="medium")
    assert gaps == ["child", "parent"]
    # at low floor, both are covered
    assert coverage_gaps_by_target_transitive(backend, min_confidence="low") == []


def test_unresolved_edge_does_not_propagate_coverage():
    backend = NetworkXBackend()
    _seed(
        backend,
        [
            _mk("parent", "RTL_Module"),
            _mk("child", "RTL_Module"),
            _mk("t1", "SW_Test", is_test=True),
        ],
        [
            Triple(subject="parent", predicate="instantiates", object="child"),
            Triple(
                subject="t1",
                predicate="tests_module",
                object="parent",
                confidence_tier="high",
                resolved=False,
            ),
        ],
    )
    gaps = coverage_gaps_by_target_transitive(backend, min_confidence="medium")
    assert gaps == ["child", "parent"]


def test_cycle_in_instantiates_does_not_hang():
    backend = NetworkXBackend()
    _seed(
        backend,
        [_mk("A", "RTL_Module"), _mk("B", "RTL_Module")],
        [
            Triple(subject="A", predicate="instantiates", object="B"),
            Triple(subject="B", predicate="instantiates", object="A"),
        ],
    )
    gaps = coverage_gaps_by_target_transitive(backend, min_confidence="medium")
    assert gaps == ["A", "B"]


def test_sorted_output():
    backend = NetworkXBackend()
    _seed(
        backend,
        [_mk(n, "RTL_Module") for n in ("zeta", "alpha", "mu")],
        [],
    )
    assert coverage_gaps_by_target_transitive(backend, min_confidence="medium") == [
        "alpha",
        "mu",
        "zeta",
    ]


def test_facade_export():
    from kgweave.knowledge_graph import coverage_gaps_by_target_transitive as f

    assert callable(f)


def test_e2e_demo_dataset_aes_submodules_become_covered():
    backend = NetworkXBackend()
    _seed(
        backend,
        [
            _mk("aes", "RTL_Module"),
            _mk("aes_cipher_control", "RTL_Module"),
            _mk("aes_sbox_canright", "RTL_Module"),
            _mk("dif_aes_smoketest", "SW_Test", is_test=True),
        ],
        [
            Triple(subject="aes", predicate="instantiates", object="aes_cipher_control"),
            Triple(subject="aes", predicate="instantiates", object="aes_sbox_canright"),
            Triple(
                subject="dif_aes_smoketest",
                predicate="tests_module",
                object="aes",
                confidence_tier="high",
                resolved=True,
            ),
        ],
    )
    from kgweave.knowledge_graph.queries import coverage_gaps_by_target

    direct = coverage_gaps_by_target(backend, min_confidence="medium")
    assert direct == ["aes_cipher_control", "aes_sbox_canright"]
    transitive = coverage_gaps_by_target_transitive(backend, min_confidence="medium")
    assert transitive == []

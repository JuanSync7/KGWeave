"""Stage 4 TDD: end-to-end integration of the audit/coverage query views.

Wires the SW_Test extractor into a real :class:`NetworkXBackend` populated
with synthetic RTL_Module entities, then exercises the public facade
re-exports of the query helpers. This is the integration counterpart to
the unit-level coverage in ``test_audit_coverage_queries.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common.schemas import Entity
from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def test_facade_exports_query_helpers():
    """The public facade must re-export the Stage-3 query helpers."""
    from kgweave.knowledge_graph import (  # noqa: F401
        audit_orphan_tests,
        confidence_tier_rank,
        coverage_gaps_by_target,
    )

    # And rank semantics should round-trip via the facade import too.
    assert confidence_tier_rank("low") < confidence_tier_rank("medium")
    assert confidence_tier_rank("medium") < confidence_tier_rank("high")


def test_e2e_pipeline_produces_audit_and_coverage_reports(tmp_path):
    """End-to-end: RTL setup + SW_Test extractor -> orphan + coverage views.

    Layout under ``tmp_path``:

    * ``aes_smoketest.c`` — real test that ``#include "dif_aes.h"`` -> high
      tier resolved ``tests_module`` edge to ``aes``.
    * ``hmac_dif_test.c`` — real test calling ``dif_hmac_init`` -> high
      tier resolved ``tests_module`` edge to ``hmac``.
    * ``mystery.c`` — real test (has ``main``) but no module hit ->
      unresolved low-tier edge -> stays orphan.
    * ``crt0.c`` — not a real test (``is_test=False``) -> excluded from
      audit regardless.

    Synthetic RTL_Modules: ``aes`` (medium-covered), ``hmac`` (high-
    covered), ``otp_ctrl`` (no inbound coverage at all).
    """
    backend = NetworkXBackend()
    backend.upsert_entities(
        [
            Entity(name="aes", type="RTL_Module"),
            Entity(name="hmac", type="RTL_Module"),
            Entity(name="otp_ctrl", type="RTL_Module"),
        ]
    )

    _write(
        tmp_path,
        "aes_smoketest.c",
        '#include "dif_aes.h"\nint main(void){ return 0; }\n',
    )
    _write(
        tmp_path,
        "hmac_dif_test.c",
        "int main(void){ dif_hmac_init(&h); return 0; }\n",
    )
    _write(tmp_path, "mystery.c", "int main(void){ return 0; }\n")
    _write(tmp_path, "crt0.c", "void _start(void){}\n")

    # Constraint: SW_Test extractor MUST be constructed AFTER RTL entities
    # are present in the backend so ``known_entity_names`` is non-empty.
    known = list(backend.get_all_node_names_and_aliases().keys())
    assert known, "RTL setup must precede SW_Test extraction"
    extractor = SWTestExtractor(known_entity_names=known)
    result = extractor.extract(source=str(tmp_path))
    backend.upsert_entities(result.entities)
    backend.upsert_triples(result.triples)

    # Use the public facade — this is the consumption surface.
    from kgweave.knowledge_graph import (
        audit_orphan_tests,
        coverage_gaps_by_target,
    )

    # Audit (precision) view: only ``mystery`` should be flagged.
    # - aes_smoketest has a resolved medium edge -> not orphan.
    # - hmac_dif_test has a resolved high edge -> not orphan.
    # - crt0 has is_test=False -> excluded from the audit entirely.
    orphans = audit_orphan_tests(backend)
    assert orphans == ["mystery"], orphans

    # Coverage (recall) view at low floor: otp_ctrl is the only true gap,
    # because aes has medium and hmac has high inbound resolved coverage.
    gaps_low = coverage_gaps_by_target(backend, min_confidence="low")
    assert gaps_low == ["otp_ctrl"], gaps_low

    # At medium floor: aes (medium) still covered, hmac (high) still
    # covered, otp_ctrl still uncovered -> same answer.
    gaps_medium = coverage_gaps_by_target(backend, min_confidence="medium")
    assert gaps_medium == ["otp_ctrl"], gaps_medium

    # At high floor: aes (high via #include) and hmac (high via DIF call)
    # are both covered. Only otp_ctrl remains a gap.
    gaps_high = coverage_gaps_by_target(backend, min_confidence="high")
    assert gaps_high == ["otp_ctrl"], gaps_high


def test_e2e_empty_known_names_raises_when_dir_nonempty(tmp_path):
    """Pipeline-ordering safety net: extractor refuses to run blind.

    If the SW_Test extractor were wired BEFORE RTL extraction (so
    ``known_entity_names`` would be empty), the existing ValueError must
    fire so misconfiguration is loud rather than silent.
    """
    _write(tmp_path, "smoke.c", "int main(void){return 0;}\n")
    extractor = SWTestExtractor(known_entity_names=[])
    with pytest.raises(ValueError, match="known_entity_names"):
        extractor.extract(source=str(tmp_path))

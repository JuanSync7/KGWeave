"""Symbol-grounded SW_Test → RTL_Module resolution tests.

Replaces the brittle filename-substring heuristic with three signals
extracted from C source content: ``#include "dif_<mod>.h"`` basenames,
``dif_<mod>_*(`` calls, and ``*_<MODNAME>_BASE_ADDR`` constants.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.extraction.sw_test_extractor import (
    SWTestExtractor,
    _ModuleClaimIndex,
)


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def _tm(result, subject=None):
    out = []
    for t in result.triples:
        if t.predicate != "tests_module":
            continue
        if subject is not None and t.subject != subject:
            continue
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Single-signal high-tier matches
# ---------------------------------------------------------------------------


def test_include_only_match_emits_high_tier_edge(tmp_path):
    src = '#include "dif_aes.h"\nvoid _start(void){}\n'
    _write(tmp_path, "z.c", src)
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="z")
    resolved = [e for e in edges if e.resolved]
    assert len(resolved) == 1
    assert resolved[0].object == "aes"
    assert resolved[0].confidence_tier == "high"


def test_base_addr_only_match_emits_high_tier_edge(tmp_path):
    src = "void _start(void){ uintptr_t b = TOP_EARLGREY_AES_BASE_ADDR; (void)b; }\n"
    _write(tmp_path, "z.c", src)
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="z")
    resolved = [e for e in edges if e.resolved]
    assert len(resolved) == 1
    assert resolved[0].object == "aes"
    assert resolved[0].confidence_tier == "high"


def test_dif_only_match_emits_high_tier_edge(tmp_path):
    src = "int main(void){ dif_aes_init(&h); return 0; }\n"
    _write(tmp_path, "z.c", src)
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="z")
    resolved = [e for e in edges if e.resolved]
    assert len(resolved) == 1
    assert resolved[0].object == "aes"
    assert resolved[0].confidence_tier == "high"


# ---------------------------------------------------------------------------
# Multi-signal dedup / multi-module
# ---------------------------------------------------------------------------


def test_multi_signal_same_module_dedups_to_single_edge(tmp_path):
    src = (
        '#include "dif_aes.h"\n'
        "int main(void){\n"
        "  uintptr_t b = TOP_EARLGREY_AES_BASE_ADDR;\n"
        "  dif_aes_init(&h);\n"
        "  return (int)b;\n"
        "}\n"
    )
    _write(tmp_path, "z.c", src)
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="z")
    aes_edges = [e for e in edges if e.object == "aes"]
    assert len(aes_edges) == 1
    assert aes_edges[0].confidence_tier == "high"
    assert aes_edges[0].resolved is True


def test_multi_module_emits_multi_edges(tmp_path):
    src = (
        '#include "dif_hmac.h"\n'
        "int main(void){ dif_aes_init(&h); return 0; }\n"
    )
    _write(tmp_path, "z.c", src)
    ex = SWTestExtractor(known_entity_names=["aes", "hmac"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="z")
    objs = {e.object for e in edges if e.resolved}
    assert objs == {"aes", "hmac"}
    for e in edges:
        if e.resolved:
            assert e.confidence_tier == "high"


# ---------------------------------------------------------------------------
# Filename-substring is no longer a signal
# ---------------------------------------------------------------------------


def test_filename_substring_alone_does_not_match(tmp_path):
    # No #include, no DIF, no base addr — file just named aes_smoketest.c
    _write(tmp_path, "aes_smoketest.c", "int main(void){ return 0; }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="aes_smoketest")
    # No resolved edges to aes.
    resolved_to_aes = [e for e in edges if e.resolved and e.object == "aes"]
    assert resolved_to_aes == []
    # is_test=True, no signals, so unresolved low-tier sentinel fires.
    assert len(edges) == 1
    assert edges[0].object == "<unknown>"
    assert edges[0].confidence_tier == "low"
    assert edges[0].resolved is False


def test_unresolved_sentinel_fires_when_no_signals_match(tmp_path):
    _write(tmp_path, "mystery.c", "int main(void){ return 0; }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="mystery")
    assert len(edges) == 1
    assert edges[0].object == "<unknown>"
    assert edges[0].confidence_tier == "low"
    assert edges[0].resolved is False


# ---------------------------------------------------------------------------
# Module claim index filter & anchoring
# ---------------------------------------------------------------------------


def test_module_claim_index_filters_non_module_names():
    names = [
        "aes",                       # keep
        "hmac",                      # keep
        "AES",                       # drop (uppercase)
        "aes.ctrl_shadowed",         # drop (contains dot)
        "Some_Iface",                # drop (uppercase)
        "1bad",                      # drop (starts digit)
        "_under",                    # drop (starts with underscore)
        "mod-with-dash",             # drop (dash)
        "",                          # drop (empty)
    ]
    idx = _ModuleClaimIndex.build(names)
    assert idx.modules() == {"aes", "hmac"}


def test_base_addr_const_match_is_suffix_anchored(tmp_path):
    # AESTHETIC_BASE_ADDR must NOT match aes.
    src = "void _start(void){ uintptr_t b = AESTHETIC_BASE_ADDR; (void)b; }\n"
    _write(tmp_path, "neg.c", src)
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="neg")
    aes_edges = [e for e in edges if e.resolved and e.object == "aes"]
    assert aes_edges == []

    # TOP_FOO_AES_BASE_ADDR must match aes.
    src2 = "void _start(void){ uintptr_t b = TOP_FOO_AES_BASE_ADDR; (void)b; }\n"
    pos_dir = tmp_path / "pos"
    pos_dir.mkdir()
    _write(pos_dir, "pos.c", src2)
    res2 = ex.extract(source=str(pos_dir))
    edges2 = _tm(res2, subject="pos")
    aes_edges2 = [e for e in edges2 if e.resolved and e.object == "aes"]
    assert len(aes_edges2) == 1


def test_include_basename_strips_path(tmp_path):
    src = '#include "sw/device/lib/dif/dif_aes.h"\nvoid _start(void){}\n'
    _write(tmp_path, "z.c", src)
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _tm(res, subject="z")
    resolved = [e for e in edges if e.resolved and e.object == "aes"]
    assert len(resolved) == 1
    assert resolved[0].confidence_tier == "high"

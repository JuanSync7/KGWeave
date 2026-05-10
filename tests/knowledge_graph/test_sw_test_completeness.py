"""Stage 2 TDD: SW_Test extractor completeness/tiering tests."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from kgweave.knowledge_graph.extraction.sw_test_extractor import SWTestExtractor


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def _entity(result, name):
    for e in result.entities:
        if e.name == name:
            return e
    return None


def _triples(result, subject=None, predicate=None):
    out = []
    for t in result.triples:
        if subject is not None and t.subject != subject:
            continue
        if predicate is not None and t.predicate != predicate:
            continue
        out.append(t)
    return out


def test_crt0_emitted_with_is_test_false(tmp_path):
    _write(tmp_path, "crt0.c", "void _start(void) { }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    e = _entity(res, "crt0")
    assert e is not None
    assert e.is_test is False


def test_main_function_marks_is_test_true(tmp_path):
    _write(tmp_path, "smoke.c", "int main(void) { return 0; }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    assert _entity(res, "smoke").is_test is True


def test_ottf_macro_marks_is_test_true(tmp_path):
    _write(tmp_path, "ottf_test.c", "OTTF_DEFINE_TEST_CONFIG();\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    assert _entity(res, "ottf_test").is_test is True


def test_test_main_function_marks_is_test_true(tmp_path):
    _write(tmp_path, "tm.c", "void test_main(void) { }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    assert _entity(res, "tm").is_test is True


def test_dif_call_emits_high_tier_tests_module(tmp_path):
    _write(tmp_path, "zzz.c", "int main(void){ dif_aes_init(&h); return 0; }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _triples(res, subject="zzz", predicate="tests_module")
    high = [t for t in edges if t.object == "aes" and t.confidence_tier == "high"]
    assert len(high) == 1
    assert high[0].resolved is True


def test_include_signal_emits_high_tier_tests_module(tmp_path):
    # Reframed: filename-substring path retired. The equivalent symbol-grounded
    # signal is the DIF header #include, which yields a high-tier edge.
    _write(
        tmp_path,
        "aes_smoketest.c",
        '#include "dif_aes.h"\nvoid _start(void) {}\n',
    )
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _triples(res, subject="aes_smoketest", predicate="tests_module")
    resolved = [e for e in edges if e.resolved]
    assert len(resolved) == 1
    assert resolved[0].object == "aes"
    assert resolved[0].confidence_tier == "high"
    assert resolved[0].resolved is True


def test_unmatched_real_test_emits_unresolved_low_edge(tmp_path):
    _write(tmp_path, "mystery.c", "int main(void){ return 0; }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _triples(res, subject="mystery", predicate="tests_module")
    assert len(edges) == 1
    assert edges[0].object == "<unknown>"
    assert edges[0].confidence_tier == "low"
    assert edges[0].resolved is False


def test_non_test_file_does_not_emit_unresolved_edge(tmp_path):
    _write(tmp_path, "crt0.c", "void _start(void){}\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    edges = _triples(res, subject="crt0", predicate="tests_module")
    assert edges == []


def test_empty_known_entity_names_with_real_dir_raises(tmp_path):
    _write(tmp_path, "x.c", "int main(void){return 0;}\n")
    ex = SWTestExtractor(known_entity_names=[])
    with pytest.raises(ValueError, match="known_entity_names"):
        ex.extract(source=str(tmp_path))


def test_empty_dir_does_not_raise_even_with_empty_known_names(tmp_path):
    ex = SWTestExtractor(known_entity_names=[])
    res = ex.extract(source=str(tmp_path))
    assert res.entities == []
    assert res.triples == []


def test_unreadable_file_emits_is_test_none(tmp_path, monkeypatch):
    p = _write(tmp_path, "broken.c", "int main(void){return 0;}\n")
    real_read = Path.read_text

    def fake_read_text(self, *a, **kw):
        if self == p:
            raise OSError("simulated unreadable")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    e = _entity(res, "broken")
    assert e is not None
    assert e.is_test is None


def test_dif_call_also_emits_tests_module_not_just_accesses_csr(tmp_path):
    _write(tmp_path, "zzz.c", "int main(void){ dif_aes_init(&h); return 0; }\n")
    ex = SWTestExtractor(known_entity_names=["aes"])
    res = ex.extract(source=str(tmp_path))
    accesses = _triples(res, subject="zzz", predicate="accesses_csr")
    tm = _triples(res, subject="zzz", predicate="tests_module")
    assert len(accesses) >= 1
    assert any(t.object == "aes" and t.confidence_tier == "high" for t in tm)

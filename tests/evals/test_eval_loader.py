# @summary
# TDD: YAML loader for the Q&A golden set. Validates schema, error messages,
# and tolerance for missing optional fields.
# @end-summary
"""Eval-harness Q&A YAML loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestLoadQASet:
    def test_load_minimal(self, tmp_path: Path) -> None:
        from kgweave.evals.loader import load_qa_set
        p = tmp_path / "qa.yaml"
        p.write_text("""
questions:
  - id: q1
    question: What ports does ibex_core have?
    gold_entities:
      - ibex_core.clk_i
      - ibex_core.rst_ni
""")
        qas = load_qa_set(p)
        assert len(qas) == 1
        assert qas[0].id == "q1"
        assert qas[0].gold_entities == ["ibex_core.clk_i", "ibex_core.rst_ni"]

    def test_load_with_optional_fields(self, tmp_path: Path) -> None:
        from kgweave.evals.loader import load_qa_set
        p = tmp_path / "qa.yaml"
        p.write_text("""
questions:
  - id: q1
    question: What does ibex_core instantiate?
    gold_entities: [ibex_id_stage]
    gold_answer: It instantiates the ID stage.
    category: hierarchy
    tags: [instantiates]
""")
        qa = load_qa_set(p)[0]
        assert qa.category == "hierarchy"
        assert qa.tags == ["instantiates"]
        assert qa.gold_answer.startswith("It instantiates")

    def test_missing_id_raises(self, tmp_path: Path) -> None:
        from kgweave.evals.loader import load_qa_set
        p = tmp_path / "qa.yaml"
        p.write_text("""
questions:
  - question: What?
    gold_entities: [a]
""")
        with pytest.raises(ValueError, match="id"):
            load_qa_set(p)

    def test_missing_questions_key_raises(self, tmp_path: Path) -> None:
        from kgweave.evals.loader import load_qa_set
        p = tmp_path / "qa.yaml"
        p.write_text("foo: bar\n")
        with pytest.raises(ValueError, match="questions"):
            load_qa_set(p)


class TestGoldenIbexFile:
    """Sanity tests against the shipped golden Ibex Q&A set."""

    def _qa_path(self) -> Path:
        # Resolve to the repo's evals/ directory.
        return Path(__file__).resolve().parents[2] / "evals" / "qa_ibex.yaml"

    def test_golden_file_exists(self) -> None:
        assert self._qa_path().exists(), (
            f"Golden Ibex Q&A file missing: {self._qa_path()}"
        )

    def test_golden_file_has_50_questions(self) -> None:
        from kgweave.evals.loader import load_qa_set
        qas = load_qa_set(self._qa_path())
        assert len(qas) == 50, f"Expected 50 Q&A pairs, got {len(qas)}"

    def test_all_questions_have_gold_entities(self) -> None:
        from kgweave.evals.loader import load_qa_set
        qas = load_qa_set(self._qa_path())
        for qa in qas:
            assert qa.gold_entities, f"{qa.id} has no gold entities"

    def test_all_ids_unique(self) -> None:
        from kgweave.evals.loader import load_qa_set
        qas = load_qa_set(self._qa_path())
        ids = [qa.id for qa in qas]
        assert len(set(ids)) == len(ids), "Duplicate Q&A IDs"

    def test_categories_cover_main_topics(self) -> None:
        from kgweave.evals.loader import load_qa_set
        qas = load_qa_set(self._qa_path())
        cats = {qa.category for qa in qas}
        # Must span the four areas chip-design RAG cares about.
        for required in ("structure", "hierarchy", "connectivity", "parameters"):
            assert required in cats, f"missing category: {required}"

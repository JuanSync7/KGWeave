# @summary
# LLM-driven testplan normalizer: turns freeform markdown / wiki testplan
# text into the canonical OpenTitan-style HJSON-compatible dict that
# TestplanExtractor already consumes. Phase-1 implementation only handles
# the LLM-driven markdown path; CSV / wiki-table parsing is deferred.
# Exports: TestplanNormalizer, TESTPLAN_NORMALIZER_PROMPT
# Deps: json, logging, kgweave.knowledge_graph.common (no direct deps yet)
# @end-summary
"""Freeform-testplan → canonical-dict normalizer.

The existing :class:`TestplanExtractor` consumes a strict OpenTitan HJSON
schema (``{"name", "testpoints":[...], "covergroups":[...]}``). Real-world
testplans are written as markdown, wikis, prose, and CSVs; this normalizer is
the preprocessor that lifts those formats into the canonical shape so the
TestplanExtractor can swallow them unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "TestplanNormalizer",
    "TESTPLAN_NORMALIZER_PROMPT",
]


_logger = logging.getLogger("kgweave.knowledge_graph.testplan_normalizer")


TESTPLAN_NORMALIZER_PROMPT: str = (
    "You are a testplan normalizer. Convert the freeform testplan text below "
    "into a strict OpenTitan-style HJSON-compatible JSON object.\n\n"
    "## Output schema (strict JSON, no commentary)\n"
    "{\n"
    '  "name": "<testplan name; use the document title if present, else \'testplan\'>",\n'
    '  "testpoints": [\n'
    "    {\n"
    '      "name": "<testpoint identifier, snake_case>",\n'
    '      "desc": "<single-paragraph description from the prose>",\n'
    '      "stage": "<V1|V2|V2S|V3 or empty string>",\n'
    '      "tests": ["<test name>", ...],\n'
    '      "tags": ["<tag>", ...]\n'
    "    }\n"
    "  ],\n"
    '  "covergroups": [\n'
    '    {"name": "<covergroup name>", "desc": "<description>"}\n'
    "  ]\n"
    "}\n\n"
    "## Rules\n"
    "- Each testpoint is one verifiable feature. Every heading under a "
    "\"Testpoints\" / \"Verification\" section becomes a testpoint when it "
    "describes a feature to test.\n"
    "- `tests` is the list of test class / sequence names mentioned in the "
    "section. If none are listed, use an empty list.\n"
    "- `stage` is the verification lifecycle stage when the prose names one; "
    "otherwise the empty string.\n"
    "- `tags` carry milestone / category hints (e.g. \"smoke\", \"directed\").\n"
    "- Always emit both `testpoints` and `covergroups`, even if empty.\n"
    "- DO NOT invent entries that are not present in the prose.\n\n"
    "## Testplan text\n"
    "```\n{text}\n```\n"
)


class TestplanNormalizer:
    __test__ = False  # Tell pytest this is not a test class.

    """Convert freeform testplan input to the canonical extractor schema.

    Parameters
    ----------
    llm_provider:
        Object exposing ``.generate(prompt: str) -> str`` returning a JSON
        string per :data:`TESTPLAN_NORMALIZER_PROMPT`'s output schema.
    config:
        Accepted for symmetry with sibling extractors; unused today.

    Notes
    -----
    Only the LLM-driven markdown path is implemented. CSV and wiki-table
    parsing are deferred to a follow-up — see the module docstring.
    """

    def __init__(
        self,
        llm_provider: Any,
        config: Optional[Any] = None,
    ) -> None:
        self._llm = llm_provider
        self._config = config

    def normalize(self, text: str, source: str = "") -> Dict[str, Any]:
        """Return a canonical testplan dict for *text*.

        Always returns a dict shaped ``{"name", "testpoints", "covergroups"}``;
        an empty input yields an empty-but-well-formed structure so callers
        can json.dumps it unconditionally.
        """
        empty = self._empty_canonical(source)
        if not text or not text.strip():
            return empty

        prompt = TESTPLAN_NORMALIZER_PROMPT.replace("{text}", text.strip())
        try:
            raw = self._llm.generate(prompt)
        except Exception as exc:  # pragma: no cover - defensive
            _logger.warning("Testplan normalizer LLM call failed: %s", exc)
            return empty

        parsed = self._safe_parse(raw, source)
        if parsed is None:
            return empty

        return self._coerce_shape(parsed, source)

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _safe_parse(raw: str, source: str) -> Optional[Any]:
        if not raw or not raw.strip():
            return None
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            nl = cleaned.find("\n")
            cleaned = cleaned[nl + 1:] if nl != -1 else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            _logger.warning(
                "Testplan normalizer JSON parse failed for %s: %s",
                source or "<unknown>", exc,
            )
            return None

    @staticmethod
    def _empty_canonical(source: str) -> Dict[str, Any]:
        name = "testplan"
        if source:
            base = source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            name = base.rsplit(".", 1)[0] or name
        return {"name": name, "testpoints": [], "covergroups": []}

    def _coerce_shape(
        self, parsed: Any, source: str
    ) -> Dict[str, Any]:
        if not isinstance(parsed, dict):
            return self._empty_canonical(source)

        name = parsed.get("name")
        if not isinstance(name, str) or not name:
            name = self._empty_canonical(source)["name"]

        testpoints = parsed.get("testpoints")
        if not isinstance(testpoints, list):
            testpoints = []
        norm_tps: List[Dict[str, Any]] = []
        for tp in testpoints:
            if not isinstance(tp, dict):
                continue
            tp_name = tp.get("name")
            if not isinstance(tp_name, str) or not tp_name:
                continue
            norm_tps.append({
                "name": tp_name,
                "desc": tp.get("desc") if isinstance(tp.get("desc"), str) else "",
                "stage": tp.get("stage") if isinstance(tp.get("stage"), str) else "",
                "tests": [t for t in (tp.get("tests") or []) if isinstance(t, str)],
                "tags": [t for t in (tp.get("tags") or []) if isinstance(t, str)],
            })

        covergroups = parsed.get("covergroups")
        if not isinstance(covergroups, list):
            covergroups = []
        norm_cgs: List[Dict[str, Any]] = []
        for cg in covergroups:
            if not isinstance(cg, dict):
                continue
            cg_name = cg.get("name")
            if not isinstance(cg_name, str) or not cg_name:
                continue
            norm_cgs.append({
                "name": cg_name,
                "desc": cg.get("desc") if isinstance(cg.get("desc"), str) else "",
            })

        return {
            "name": name,
            "testpoints": norm_tps,
            "covergroups": norm_cgs,
        }

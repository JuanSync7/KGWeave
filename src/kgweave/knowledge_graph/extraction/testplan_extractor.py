# @summary
# OpenTitan-style HJSON DV testplan extractor.
# Parses a *_testplan.hjson file (testpoints + covergroups + optional
# import_testplans) and emits Testpoint / Covergroup / Stage / DVTest
# entities and tests / has_stage / covers / collected_in edges. Test names
# are fused (case-insensitive, with a suffix index) to existing entities
# via known_entity_names; otherwise a fresh DVTest entity is created.
# Exports: TestplanExtractor, TESTPLAN_SOURCE
# Deps: hjson, kgweave.knowledge_graph.common
# @end-summary
"""OpenTitan-style HJSON DV testplan extractor.

Walks the ``testpoints[]`` and ``covergroups[]`` lists in a testplan HJSON
file and emits typed nodes + edges fused to the existing KG. Testpoint
names are canonicalised as ``"{filename}.{testpoint_name}"`` so two
different testplans never collide. The extractor is conservative about
SVA fusion: a ``covers`` edge to an ``SVA_Assertion`` is only emitted
when ``known_entity_names`` already contains a matching name. Otherwise
the test name yields a ``tests --> DVTest`` edge (creating the DVTest if
no fusion match exists).

``import_testplans`` cross-file resolution is *not* performed: the import
list is recorded as ``evidence_span`` text on the testplan-level entity
only. Recursive include resolution is deferred to a follow-up.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import hjson

from kgweave.knowledge_graph.common import (
    Entity,
    EntityDescription,
    ExtractionResult,
    Triple,
)

__all__ = ["TestplanExtractor", "TESTPLAN_SOURCE"]

TESTPLAN_SOURCE = "testplan"

_logger = logging.getLogger("rag.knowledge_graph.testplan")


_SVA_PREFIXES = ("a_", "prim_")
_SVA_SUFFIXES = ("_a", "_assert", "_check")


def _normalize_sva_candidate(
    name: str,
    prefixes: tuple = _SVA_PREFIXES,
    suffixes: tuple = _SVA_SUFFIXES,
) -> str:
    """Strip SVA-style prefixes/suffixes and collapse to alnum_underscore.

    Applies repeatedly so a name like ``A_data_known_a`` collapses to
    ``data_known``. Lowercases and replaces non-alphanumeric runs with a
    single underscore before stripping. Returns the empty string for
    empty input.

    ``prefixes`` / ``suffixes`` default to the OpenTitan-flavored set;
    callers (TestplanExtractor) can override for non-OT codebases.
    """
    if not name:
        return ""
    s = name.lower()
    # Structural char scanner: collapse each run of non-alphanumeric chars to
    # a single underscore separator (equivalent to re.sub(r"[^a-z0-9]+","_",s)
    # followed by strip("_")).
    _buf: List[str] = []
    _in_sep = False
    for _ch in s:
        if _ch.isalpha() or _ch.isdigit():
            if _in_sep and _buf:
                _buf.append("_")
            _buf.append(_ch)
            _in_sep = False
        else:
            _in_sep = True
    s = "".join(_buf)
    changed = True
    while changed:
        changed = False
        for pfx in prefixes:
            if s.startswith(pfx) and len(s) > len(pfx):
                s = s[len(pfx):]
                changed = True
        for sfx in suffixes:
            if s.endswith(sfx) and len(s) > len(sfx):
                s = s[: -len(sfx)]
                changed = True
    return s


def _match_sva_for_test(
    test_name: str,
    known_sva_names: Iterable[str],
    prefixes: tuple = _SVA_PREFIXES,
    suffixes: tuple = _SVA_SUFFIXES,
) -> Optional[str]:
    """Find a unique SVA canonical name matching *test_name*.

    Resolution order:
      (a) exact case-insensitive match,
      (b) normalized exact match (single hit),
      (c) normalized substring containment (single hit either direction).

    Returns ``None`` if no candidate or if the strongest available tier
    is ambiguous (more than one hit). Conservative — false ``covers``
    edges are worse than missing ones.
    """
    if not test_name:
        return None
    candidates = [n for n in known_sva_names if n]
    if not candidates:
        return None

    test_lower = test_name.lower()
    exact = [c for c in candidates if c.lower() == test_lower]
    if exact:
        return sorted(exact)[0]

    test_norm = _normalize_sva_candidate(test_name, prefixes, suffixes)
    if not test_norm:
        return None

    norm_exact = [c for c in candidates
                  if _normalize_sva_candidate(c, prefixes, suffixes) == test_norm]
    if len(norm_exact) == 1:
        return norm_exact[0]
    if len(norm_exact) > 1:
        _logger.debug(
            "ambiguous normalized SVA match for %r: %s — skipping",
            test_name, norm_exact,
        )
        return None

    contain: List[str] = []
    for c in candidates:
        c_norm = _normalize_sva_candidate(c, prefixes, suffixes)
        if not c_norm:
            continue
        if test_norm in c_norm or c_norm in test_norm:
            contain.append(c)
    if len(contain) == 1:
        return contain[0]
    if len(contain) > 1:
        _logger.debug(
            "ambiguous containment SVA match for %r: %s — skipping",
            test_name, contain,
        )
    return None


def _basename_no_ext(source: str) -> str:
    if not source:
        return "testplan"
    base = os.path.basename(source)
    stem, _ = os.path.splitext(base)
    return stem or base


def _is_word_char(ch: str) -> bool:
    """Return True if *ch* is a word character (alphanumeric or underscore)."""
    return ch.isalnum() or ch == "_"


def _find_word_bounded(
    text: str, name: str
) -> "Optional[tuple[int, int]]":
    """Find *name* in *text* with word-boundary semantics; return (start, end).

    Both *text* and *name* must already be lowercased by the caller.
    Word boundary: the characters immediately before ``start`` and at ``end``
    must not be alphanumeric or underscore (matching ``\\b`` semantics).
    Returns ``None`` when no match exists.

    Handles names that contain non-word characters (e.g. a dot-qualified
    canonical such as ``aes.cipher_core``): the boundary check only applies
    to the first and last character of the matched span.
    """
    if not name:
        return None
    n_len = len(name)
    t_len = len(text)
    pos = 0
    while pos <= t_len - n_len:
        idx = text.find(name, pos)
        if idx == -1:
            return None
        end = idx + n_len
        left_ok = (idx == 0) or not _is_word_char(text[idx - 1])
        right_ok = (end >= t_len) or not _is_word_char(text[end])
        if left_ok and right_ok:
            return idx, end
        pos = idx + 1
    return None


class TestplanExtractor:
    __test__ = False  # Tell pytest this is not a test class.

    """Parse OpenTitan-style testplan HJSON into KG entities and triples.

    Parameters
    ----------
    known_entity_names:
        Optional iterable of canonical entity names to fuse against. The
        lookup is case-insensitive and accepts module-namespaced suffix
        matches (``aes.foo`` matched by bare ``foo``).
    schema, config:
        Accepted for symmetry with the other extractors; not required.
    """

    @property
    def name(self) -> str:
        return TESTPLAN_SOURCE

    def __init__(
        self,
        known_entity_names: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
        sva_prefixes: Optional[Iterable[str]] = None,
        sva_suffixes: Optional[Iterable[str]] = None,
    ) -> None:
        self._schema = schema
        self._config = config
        # Resolve SVA prefix/suffix lists. ``None`` means "use OT defaults",
        # which preserves backward compatibility. A KGConfig-supplied list
        # (via ``config.testplan_sva_prefixes``) is honoured below if neither
        # explicit constructor arg is given.
        cfg_prefixes = getattr(config, "testplan_sva_prefixes", None) if config else None
        if sva_prefixes is not None:
            self._sva_prefixes: tuple = tuple(sva_prefixes)
        elif cfg_prefixes:
            self._sva_prefixes = tuple(cfg_prefixes)
        else:
            self._sva_prefixes = _SVA_PREFIXES
        self._sva_suffixes: tuple = (
            tuple(sva_suffixes) if sva_suffixes is not None else _SVA_SUFFIXES
        )
        names = list(known_entity_names) if known_entity_names else []
        self._known_lower: Dict[str, str] = {}
        self._suffix_lower: Dict[str, str] = {}
        self._known_types: Dict[str, str] = {}
        seen_lower: Set[str] = set()
        self._known_names: List[str] = []
        # types stored as canonical name -> type when caller passes a dict
        # (we accept iterables of names only here, type lookup falls back).
        for n in names:
            if not n:
                continue
            self._known_lower[n.lower()] = n
            if "." in n:
                _, _, tail = n.rpartition(".")
                if tail:
                    self._suffix_lower[tail.lower()] = n
            key = n.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                self._known_names.append(n)

        self._sva_known: List[str] = [
            n for n in self._known_names
            if self._looks_like_sva(n)
        ]

    # -- Public API ---------------------------------------------------------

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Parse *text* as testplan HJSON; emit Testpoint/Covergroup/etc."""
        try:
            doc = hjson.loads(text)
        except Exception as exc:  # pragma: no cover - defensive
            _logger.warning("Testplan HJSON parse failed for %s: %s", source, exc)
            return ExtractionResult()

        if not isinstance(doc, dict):
            return ExtractionResult()

        base = _basename_no_ext(source)
        entities: List[Entity] = []
        triples: List[Triple] = []
        stage_seen: Set[str] = set()
        dvtest_seen: Set[str] = set()

        testpoints = doc.get("testpoints", []) or []
        covergroups = doc.get("covergroups", []) or []

        if isinstance(testpoints, list):
            for tp in testpoints:
                if not isinstance(tp, dict):
                    continue
                self._handle_testpoint(
                    tp, base, source, entities, triples,
                    stage_seen, dvtest_seen,
                )

        if isinstance(covergroups, list):
            for cg in covergroups:
                if not isinstance(cg, dict):
                    continue
                self._handle_covergroup(cg, base, source, entities, triples)

        return ExtractionResult(entities=entities, triples=triples)

    # -- Handlers -----------------------------------------------------------

    def _handle_testpoint(
        self,
        tp: Dict[str, Any],
        base: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
        stage_seen: Set[str],
        dvtest_seen: Set[str],
    ) -> None:
        tp_name = tp.get("name")
        if not isinstance(tp_name, str) or not tp_name:
            return
        canonical = f"{base}.{tp_name}"
        desc = tp.get("desc") if isinstance(tp.get("desc"), str) else ""
        stage = tp.get("stage") if isinstance(tp.get("stage"), str) else ""
        tags = tp.get("tags") if isinstance(tp.get("tags"), list) else []

        raw_mentions: List[EntityDescription] = []
        if desc:
            raw_mentions.append(
                EntityDescription(text=desc, source=source, chunk_id="")
            )

        entities.append(Entity(
            name=canonical,
            type="Testpoint",
            sources=[source] if source else [],
            extractor_source=[TESTPLAN_SOURCE],
            aliases=[t for t in tags if isinstance(t, str)],
            raw_mentions=raw_mentions,
        ))

        if stage:
            if stage not in stage_seen:
                entities.append(Entity(
                    name=stage,
                    type="Stage",
                    sources=[source] if source else [],
                    extractor_source=[TESTPLAN_SOURCE],
                ))
                stage_seen.add(stage)
            triples.append(Triple(
                subject=canonical,
                predicate="has_stage",
                object=stage,
                source=source,
                extractor_source=TESTPLAN_SOURCE,
                evidence_span=desc,
                layer=TESTPLAN_SOURCE,
            ))

        self._scan_desc_mentions(desc, canonical, source, triples)

        tests = tp.get("tests")
        if isinstance(tests, list):
            for t in tests:
                if not isinstance(t, str) or not t:
                    continue
                fused, fused_type = self._fuse_with_type(t)
                # If the fused entity is a known SVA assertion, emit covers.
                if fused_type == "SVA_Assertion":
                    triples.append(Triple(
                        subject=canonical,
                        predicate="covers",
                        object=fused,
                        source=source,
                        extractor_source=TESTPLAN_SOURCE,
                        evidence_span=desc,
                        layer=TESTPLAN_SOURCE,
                    ))
                    continue
                # Try SVA-name-normalized fusion against known assertion-ish
                # entities. Conservative: only emits when match is unique.
                sva_match = _match_sva_for_test(
                    t, self._sva_known, self._sva_prefixes, self._sva_suffixes,
                )
                if sva_match is not None and sva_match != t:
                    triples.append(Triple(
                        subject=canonical,
                        predicate="covers",
                        object=sva_match,
                        source=source,
                        extractor_source=TESTPLAN_SOURCE,
                        evidence_span=f"name match: {t} ~ {sva_match}",
                        layer=TESTPLAN_SOURCE,
                    ))
                    continue
                # Otherwise: tests edge to either the fused entity or a new
                # DVTest entity.
                if fused == t and fused not in dvtest_seen:
                    # No fusion match: create a DVTest entity.
                    entities.append(Entity(
                        name=t,
                        type="DVTest",
                        sources=[source] if source else [],
                        extractor_source=[TESTPLAN_SOURCE],
                    ))
                    dvtest_seen.add(t)
                triples.append(Triple(
                    subject=canonical,
                    predicate="tests",
                    object=fused,
                    source=source,
                    extractor_source=TESTPLAN_SOURCE,
                    evidence_span=desc,
                    layer=TESTPLAN_SOURCE,
                ))

    def _handle_covergroup(
        self,
        cg: Dict[str, Any],
        base: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> None:
        cg_name = cg.get("name")
        if not isinstance(cg_name, str) or not cg_name:
            return
        canonical = f"{base}.{cg_name}"
        desc = cg.get("desc") if isinstance(cg.get("desc"), str) else ""

        raw_mentions: List[EntityDescription] = []
        if desc:
            raw_mentions.append(
                EntityDescription(text=desc, source=source, chunk_id="")
            )

        entities.append(Entity(
            name=canonical,
            type="Covergroup",
            sources=[source] if source else [],
            extractor_source=[TESTPLAN_SOURCE],
            raw_mentions=raw_mentions,
        ))

        self._scan_desc_mentions(desc, canonical, source, triples)

        # Best-effort module fusion: scan desc + name tokens for known
        # RTL_Module names. Conservative — only emit if we have an exact
        # case-insensitive match against known_entity_names.
        haystack = f"{cg_name} {desc}".lower()
        emitted: Set[str] = set()
        for low, canon in self._known_lower.items():
            if not low:
                continue
            # Word-boundary-ish: match tokens of length >= 3.
            if len(low) < 3:
                continue
            if low in haystack and canon not in emitted:
                # Skip self-reference.
                if canon == canonical:
                    continue
                triples.append(Triple(
                    subject=canonical,
                    predicate="collected_in",
                    object=canon,
                    source=source,
                    extractor_source=TESTPLAN_SOURCE,
                    evidence_span=desc,
                    layer=TESTPLAN_SOURCE,
                ))
                emitted.add(canon)

    # -- Prose mention scan -------------------------------------------------

    def _looks_like_sva(self, name: str) -> bool:
        if not name:
            return False
        tail = name.rsplit(".", 1)[-1].lower()
        # Configured prefixes/suffixes; keep the universal "assert" /
        # "_a" / "_assert" tails (LRM-conventional) regardless of config.
        if any(tail.startswith(p) for p in self._sva_prefixes):
            return True
        if any(tail.endswith(s) for s in self._sva_suffixes):
            return True
        return tail.startswith("a_") or "assert" in tail

    @staticmethod
    def _strip_code_spans(text: str) -> str:
        """Blank out fenced code blocks and inline code spans.

        Preserves character positions (replaces each code-span char with a
        space) so that ``_evidence_window`` start/end indices remain valid.

        Implemented as a single-pass structural state-machine scanner:
        - Triple-backtick sequences open/close fenced blocks (multi-line OK).
        - Single-backtick sequences open/close inline spans (newline breaks).
        No regex is used.
        """
        buf = list(text)
        i = 0
        n = len(text)
        while i < n:
            if text[i] != "`":
                i += 1
                continue
            # Fenced block: triple backtick ````` ... `````
            if i + 2 < n and text[i + 1] == "`" and text[i + 2] == "`":
                start = i
                i += 3
                # Scan forward for closing triple backtick.
                while i < n:
                    if (
                        i + 2 < n
                        and text[i] == "`"
                        and text[i + 1] == "`"
                        and text[i + 2] == "`"
                    ):
                        i += 3
                        break
                    i += 1
                # Blank the entire fenced block (including delimiters).
                for k in range(start, min(i, n)):
                    buf[k] = " "
            else:
                # Inline code span: single backtick, terminated by matching
                # backtick or newline (newline cancels the span).
                start = i
                i += 1
                while i < n and text[i] != "`" and text[i] != "\n":
                    i += 1
                if i < n and text[i] == "`":
                    i += 1  # consume closing backtick
                    for k in range(start, i):
                        buf[k] = " "
                # Unclosed inline span (hit newline or EOF): leave as-is.
        return "".join(buf)

    @staticmethod
    def _evidence_window(text: str, start: int, end: int) -> str:
        # Sentence-ish window: bounded by the nearest .!? or 80-char window.
        left = max(0, start - 80)
        right = min(len(text), end + 80)
        for sep in (". ", "! ", "? ", "\n"):
            pos = text.rfind(sep, left, start)
            if pos != -1:
                left = pos + len(sep)
                break
        for sep in (". ", "! ", "? ", "\n"):
            pos = text.find(sep, end, right)
            if pos != -1:
                right = pos
                break
        return text[left:right].strip()

    def _scan_desc_mentions(
        self,
        desc: str,
        subject: str,
        source: str,
        triples: List[Triple],
    ) -> None:
        """Emit ``subject --mentions--> known_entity`` for each prose hit.

        Mirrors :class:`MarkdownDocExtractor._extract_fusion_entities_and_mentions`
        but operates on a single string (testpoint or covergroup desc) rather
        than a multi-section markdown body. Skips backtick-wrapped spans and
        self-references (subject canonical or its tail).
        """
        if not desc or not self._known_names:
            return
        stripped = self._strip_code_spans(desc)
        subject_lower = subject.lower()
        subject_tail = subject_lower.rsplit(".", 1)[-1]
        seen: Set[str] = set()
        stripped_lower = stripped.lower()
        for canonical in self._known_names:
            canon_lower = canonical.lower()
            if canon_lower == subject_lower or canon_lower == subject_tail:
                continue
            span = _find_word_bounded(stripped_lower, canon_lower)
            if span is None:
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            evidence = self._evidence_window(desc, span[0], span[1])
            triples.append(Triple(
                subject=subject,
                predicate="mentions",
                object=canonical,
                source=source,
                extractor_source=TESTPLAN_SOURCE,
                evidence_span=evidence,
                layer=TESTPLAN_SOURCE,
            ))

    # -- Fusion -------------------------------------------------------------

    def _fuse_with_type(self, bare: str) -> "tuple[str, Optional[str]]":
        """Return (canonical, type_or_None) — type is best-effort heuristic.

        Type is "SVA_Assertion" when the matched canonical name *looks*
        like an assertion (suffix ``_assert``, ``_a``, contains
        ``assert``); otherwise None. The backend's case-insensitive dedup
        will fold this onto the real entity on upsert.
        """
        if not bare:
            return bare, None
        key = bare.lower()
        canonical = self._known_lower.get(key) or self._suffix_lower.get(key)
        if canonical is None:
            return bare, None
        # Heuristic: SVA-looking suffixes / substrings.
        low = canonical.lower()
        tail = low.rsplit(".", 1)[-1]
        if (
            tail.endswith("_assert")
            or tail.endswith("_a")
            or "assert" in tail
            or tail.startswith("prim_") and "assert" in tail
        ):
            return canonical, "SVA_Assertion"
        return canonical, None

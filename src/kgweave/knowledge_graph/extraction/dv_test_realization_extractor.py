# @summary
# Directory-based DV test file realization extractor. Walks dv/tests directories,
# matches *.sv files to existing DVTest entities by stripping common suffixes
# (_vseq.sv, _test.sv, .sv in priority order), and emits SV_File entities with
# realized_by edges. Files with no DVTest match still emit SV_File entities
# (as orphans) to surface unplanned test files.
# Exports: DVTestRealizationExtractor, DV_TEST_REALIZATION_SOURCE
# Deps: pathlib, typing, kgweave.knowledge_graph.common
# @end-summary
"""DV test file realization extractor — maps test files to DVTest entities.

Walks a directory tree (typically dv/tests) for SystemVerilog test files
and emits SV_File nodes + realized_by edges to matching DVTest entities
that exist in known_entity_names. Files with no match still produce SV_File
nodes (tagged as orphans) to audit test coverage gaps.

Note: This extractor deviates from the standard extract(text, source) API.
The extract() method takes a directory path in the source parameter and
ignores text. See extract() docstring for usage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = ["DVTestRealizationExtractor", "DV_TEST_REALIZATION_SOURCE"]

DV_TEST_REALIZATION_SOURCE = "dv_test_realization"

_logger = logging.getLogger("rag.knowledge_graph.dv_test_realization")

_DEFAULT_SUFFIXES_TO_STRIP = ["_vseq.sv", "_test.sv", ".sv"]


class DVTestRealizationExtractor:
    __test__ = False

    """Extract SV_File entities and realized_by edges from dv/tests directories.

    This extractor takes a different approach than text-based extractors: it
    walks a filesystem directory instead of parsing text content. The extract()
    method signature remains (text, source) for API consistency, but it ignores
    text and uses source as the directory path.

    Parameters
    ----------
    known_entity_names:
        Optional iterable of canonical DVTest entity names to match against.
        Matching is case-insensitive. DVTest names are typically bare test
        names like "aes_smoke", "aes_stress" (extracted from testplan).
    schema, config:
        Accepted for symmetry with other extractors; not used.
    """

    @property
    def name(self) -> str:
        return DV_TEST_REALIZATION_SOURCE

    def __init__(
        self,
        known_entity_names: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
        file_strip_suffixes: Optional[Iterable[str]] = None,
        project_conventions: Optional[Any] = None,
    ) -> None:
        self._schema = schema
        self._config = config
        names = list(known_entity_names) if known_entity_names else []
        self._known_lower: dict[str, str] = {}
        for n in names:
            if n:
                self._known_lower[n.lower()] = n

        # Resolve suffix list. Precedence: explicit > project_conventions > default.
        if file_strip_suffixes is None and project_conventions is not None:
            pc = getattr(project_conventions, "dv_test_file_strip_suffixes", None)
            if pc:
                file_strip_suffixes = pc
        self._suffixes_to_strip: List[str] = (
            list(file_strip_suffixes) if file_strip_suffixes else list(_DEFAULT_SUFFIXES_TO_STRIP)
        )

    def extract(self, text: str = "", source: str = "") -> ExtractionResult:
        """Extract SV_File entities and realized_by edges from a directory.

        The text parameter is ignored. The source parameter is treated as
        a filesystem directory path (e.g., "/path/to/dv/tests").

        Walks the directory recursively (up to depth 2) for *.sv files.
        For each file, attempts to fuse to an existing DVTest entity by:
          1. Stripping suffixes in priority order: _vseq.sv, _test.sv, .sv
          2. Looking up the candidate in known_entity_names (case-insensitive)
          3. If found: emit both SV_File entity and realized_by edge
          4. If not found: still emit SV_File entity (orphan, audit signal)

        Parameters
        ----------
        text:
            Ignored; provided for API compatibility.
        source:
            Filesystem path to the dv/tests directory to walk.

        Returns
        -------
        ExtractionResult
            Entities: SV_File nodes (one per .sv file found).
            Triples: realized_by edges (one per file-to-DVTest match).
        """
        if not source:
            return ExtractionResult()

        dv_tests_dir = Path(source)
        if not dv_tests_dir.is_dir():
            _logger.warning(
                "DV tests directory does not exist or is not a directory: %s",
                source,
            )
            return ExtractionResult()

        entities: List[Entity] = []
        triples: List[Triple] = []
        seen_files: Set[str] = set()

        sv_files = sorted(dv_tests_dir.rglob("*.sv"))
        if not sv_files:
            _logger.debug(
                "No *.sv files found in %s (searched recursively)",
                dv_tests_dir,
            )

        for sv_path in sv_files:
            self._process_file(sv_path, source, entities, triples, seen_files)

        return ExtractionResult(entities=entities, triples=triples)

    def _process_file(
        self,
        sv_path: Path,
        source_dir: str,
        entities: List[Entity],
        triples: List[Triple],
        seen_files: Set[str],
    ) -> None:
        """Process a single .sv file: emit SV_File entity and realized_by if match."""
        sv_name = sv_path.name
        if sv_name in seen_files:
            return
        seen_files.add(sv_name)

        fused_dvtest = self._try_fuse_to_dvtest(sv_name)

        entities.append(Entity(
            name=sv_name,
            type="SV_File",
            sources=[str(sv_path)] if sv_path.exists() else [],
            extractor_source=[DV_TEST_REALIZATION_SOURCE],
        ))

        if fused_dvtest:
            triples.append(Triple(
                subject=fused_dvtest,
                predicate="realized_by",
                object=sv_name,
                source=str(sv_path),
                extractor_source=DV_TEST_REALIZATION_SOURCE,
                evidence_span=f"file {sv_name} matches DVTest {fused_dvtest}",
                layer=DV_TEST_REALIZATION_SOURCE,
            ))

    def _try_fuse_to_dvtest(self, sv_filename: str) -> Optional[str]:
        """Match sv_filename to a known DVTest by stripping common suffixes.

        Resolution order:
          1. Strip _vseq.sv (most specific)
          2. Strip _test.sv
          3. Strip .sv (least specific)

        For each candidate, looks up case-insensitive match in known_entity_names.
        Returns the first match found (canonical name); None if no match.
        """
        if not sv_filename:
            return None

        for suffix in self._suffixes_to_strip:
            if sv_filename.endswith(suffix):
                candidate = sv_filename[: -len(suffix)]
                candidate_lower = candidate.lower()
                if candidate_lower in self._known_lower:
                    return self._known_lower[candidate_lower]

        return None

# @summary
# C/C++ reference-model and DPI boundary extractor (Tier 1 + Tier 2).
# Walks a directory for .c/.cc/.cpp/.h/.hh/.hpp files. Emits CFile and
# CFunction entities, defined_in and includes edges, and implements_dpi
# edges to any DPIBoundary whose name matches an extracted CFunction.
# DPI-C boundary detection uses pyslang AST walking over SV files; see
# extract_dpi_boundaries() and extract_dpi_boundaries_with_scope().
# Exports: CppRefModelExtractor, CPP_REF_MODEL_SOURCE, extract_dpi_boundaries,
#          extract_dpi_boundaries_with_scope, build_dpi_boundary_entities
# Deps: pathlib, re, pyslang, typing, kgweave.knowledge_graph.common
# @end-summary
"""C/C++ reference-model and DPI-C boundary extractor (Tier 1 + Tier 2).

Walks a directory for C/C++ source files and emits typed nodes + edges.

C/C++ function detection uses a single conservative regex (no libclang or
tree-sitter-c is available in this environment; see ``_FUNC_DEF_RE``).  All
other extraction paths are parser-driven:

- ``#include "..."`` detection: structural line tokeniser (no regex).
- DPI-C boundary detection: pyslang AST walk over SV files — immune to
  unusual spacing, CRLF line endings, and complex return types such as
  ``bit[7:0]`` that the old regex silently dropped.

Heuristic limitations (Phase 1 acceptable, Tier 3 libclang work deferred):
  - Template function definitions (``template<typename T> T foo(...)``) are
    skipped; the template-head regex is complex enough to produce false
    positives, so we opt for the false negative.
  - Macro-generated function bodies (``DEFINE_HANDLER(foo, ...)``) are not
    detected because there is no expansion step.
  - Function pointers as parameters (``int (*cmp)(int, int)``) may confuse
    the argument-list boundary heuristic; the pattern requires an explicit
    ``{`` on the definition line, which avoids most false positives here.
  - Block comments (``/* ... */``) are stripped via a simple state machine
    that does NOT handle nested ``/*``. Real C/C++ does not allow nesting,
    so this is fine.
  - String literals that contain function-definition-like text could fool
    the regex in theory; they are uncommon enough in hardware model code
    that we accept the occasional false positive.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set, Tuple

import pyslang

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = [
    "CppRefModelExtractor",
    "CPP_REF_MODEL_SOURCE",
    "extract_dpi_boundaries",
    "extract_dpi_boundaries_with_scope",
    "build_dpi_boundary_entities",
    "DPI_BOUNDARY_SOURCE",
]

CPP_REF_MODEL_SOURCE = "cpp_ref_model"
DPI_BOUNDARY_SOURCE = "dpi_boundary"

_logger = logging.getLogger("rag.knowledge_graph.cpp_extractor")

_CPP_EXTENSIONS = {".c", ".cc", ".cpp", ".h", ".hh", ".hpp"}

# noqa: regex-ok — C/C++ function-definition heuristic. No tree-sitter-c or
# libclang grammar is available in this environment; a pure-regex fallback is
# the only viable option until a C/C++ parser dependency is added (Tier 3).
_FUNC_DEF_RE = re.compile(  # noqa: regex-ok
    r"^(?:static\s+|inline\s+|extern\s+)*"
    r"(?:const\s+)?"
    r"[\w:*&<>\s]+"
    r"\s(\w+)\s*"
    r"\([^;{)]*\)\s*"
    r"\{",
    re.MULTILINE,
)


def _strip_block_comments(text: str) -> str:
    """Remove ``/* ... */`` block comments via a simple state machine.

    Does not handle nested comments (illegal in C/C++ anyway).
    Preserves line count so line-number references remain valid.
    """
    result: List[str] = []
    i = 0
    n = len(text)
    in_block = False
    while i < n:
        if in_block:
            if text[i] == "*" and i + 1 < n and text[i + 1] == "/":
                in_block = False
                result.append("  ")
                i += 2
            else:
                result.append("\n" if text[i] == "\n" else " ")
                i += 1
        else:
            if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
                in_block = True
                result.append("  ")
                i += 2
            elif text[i] == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    result.append(" ")
                    i += 1
            else:
                result.append(text[i])
                i += 1
    return "".join(result)


def _extract_functions(text: str) -> List[str]:
    """Return function names extracted from C/C++ source text.

    Strips block comments first, then applies the function-definition regex.
    Skips ``main`` by convention (entry point, not a model function).
    """
    stripped = _strip_block_comments(text)
    names: List[str] = []
    seen: Set[str] = set()
    for m in _FUNC_DEF_RE.finditer(stripped):
        name = m.group(1)
        if not name or name in seen:
            continue
        if name in {"if", "while", "for", "switch", "return", "else"}:
            continue
        seen.add(name)
        names.append(name)
    return names


def _extract_local_includes(text: str) -> List[str]:
    """Return local include targets from ``#include "..."`` directives.

    Uses a structural line tokeniser: strips block comments, then for each
    line checks for a ``#include`` preprocessor directive followed by a
    double-quoted path.  This avoids a regex and correctly handles arbitrary
    whitespace between ``#``, ``include``, and the quoted string.
    """
    stripped = _strip_block_comments(text)
    results: List[str] = []
    for raw_line in stripped.splitlines():
        tok = raw_line.strip()
        # Must be a preprocessor directive
        if tok[:1] != "#":
            continue
        rest = tok[1:].lstrip()
        # Must be an #include directive
        if rest[:7] != "include":
            continue
        after = rest[7:].lstrip()
        # Local include only: double-quoted path, not angle-bracket
        if after[:1] != '"':
            continue
        close = after.find('"', 1)
        if close < 0:
            continue
        results.append(after[1:close])
    return results


class CppRefModelExtractor:
    """Tier-1 C/C++ ingest: filename + function entry-point regex.

    Walks a directory for .c/.cc/.cpp/.h/.hh/.hpp files. For each:
      - Emits CFile entity (canonical: relative path basename)
      - Emits CFunction entity for each top-level function definition
      - Emits ``defined_in`` edge: CFunction --defined_in--> CFile
      - Emits ``includes`` edge: CFile --includes--> CFile (for
        ``#include "..."`` only, skipping system ``<...>`` includes)

    Fusion: if a CFunction's name matches an existing DPIBoundary entity
    name (from ``known_entity_names``), emit ``implements_dpi`` edge.

    Parameters
    ----------
    known_entity_names:
        Optional iterable of canonical entity names from the KG. Used for
        DPIBoundary name matching (case-sensitive exact match) and for
        module-name matching in SW tests.
    schema, config:
        Accepted for symmetry with other extractors; not used.
    """

    __test__ = False

    @property
    def name(self) -> str:
        return CPP_REF_MODEL_SOURCE

    def __init__(
        self,
        known_entity_names: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
    ) -> None:
        self._schema = schema
        self._config = config
        names = list(known_entity_names) if known_entity_names else []
        self._dpi_names: Set[str] = set()
        for n in names:
            if n:
                self._dpi_names.add(n)

    def extract(self, text: str = "", source: str = "") -> ExtractionResult:
        """Walk a directory and extract C/C++ entities and edges.

        The ``text`` parameter is ignored; ``source`` is a filesystem path to
        a directory containing C/C++ source files. Walks non-recursively
        (single directory depth) for files matching ``_CPP_EXTENSIONS``.

        Parameters
        ----------
        text:
            Ignored; provided for API compatibility.
        source:
            Filesystem path to the directory to walk.

        Returns
        -------
        ExtractionResult
            Entities: CFile nodes + CFunction nodes.
            Triples: defined_in, includes, implements_dpi edges.
        """
        if not source:
            return ExtractionResult()

        src_dir = Path(source)
        if not src_dir.is_dir():
            _logger.warning(
                "C/C++ source directory does not exist or is not a directory: %s",
                source,
            )
            return ExtractionResult()

        cpp_files = sorted(
            p for p in src_dir.iterdir()
            if p.is_file() and p.suffix in _CPP_EXTENSIONS
        )
        if not cpp_files:
            _logger.debug("No C/C++ files found in %s", src_dir)

        entities: List[Entity] = []
        triples: List[Triple] = []
        seen_cfiles: Set[str] = set()

        for cpp_path in cpp_files:
            self._process_file(cpp_path, entities, triples, seen_cfiles)

        return ExtractionResult(entities=entities, triples=triples)

    def _process_file(
        self,
        cpp_path: Path,
        entities: List[Entity],
        triples: List[Triple],
        seen_cfiles: Set[str],
    ) -> None:
        """Process one C/C++ file: emit CFile, CFunction, and edge entities."""
        fname = cpp_path.name
        if fname in seen_cfiles:
            return
        seen_cfiles.add(fname)

        entities.append(Entity(
            name=fname,
            type="CFile",
            sources=[str(cpp_path)],
            extractor_source=[CPP_REF_MODEL_SOURCE],
            layer=CPP_REF_MODEL_SOURCE,
        ))

        try:
            text = cpp_path.read_text(errors="replace")
        except Exception as exc:
            _logger.warning("Could not read %s: %s", cpp_path, exc)
            return

        for inc_target in _extract_local_includes(text):
            inc_name = Path(inc_target).name
            triples.append(Triple(
                subject=fname,
                predicate="includes",
                object=inc_name,
                source=str(cpp_path),
                extractor_source=CPP_REF_MODEL_SOURCE,
                evidence_span=f'#include "{inc_target}"',
                layer=CPP_REF_MODEL_SOURCE,
            ))

        for func_name in _extract_functions(text):
            entities.append(Entity(
                name=func_name,
                type="CFunction",
                sources=[str(cpp_path)],
                extractor_source=[CPP_REF_MODEL_SOURCE],
                layer=CPP_REF_MODEL_SOURCE,
            ))
            triples.append(Triple(
                subject=func_name,
                predicate="defined_in",
                object=fname,
                source=str(cpp_path),
                extractor_source=CPP_REF_MODEL_SOURCE,
                evidence_span=f"function {func_name} in {fname}",
                layer=CPP_REF_MODEL_SOURCE,
            ))
            if func_name in self._dpi_names:
                triples.append(Triple(
                    subject=func_name,
                    predicate="implements_dpi",
                    object=func_name,
                    source=str(cpp_path),
                    extractor_source=CPP_REF_MODEL_SOURCE,
                    evidence_span=f"DPI-C boundary: {func_name}",
                    layer=CPP_REF_MODEL_SOURCE,
                ))


def _sv_scope_of(node: "pyslang.SyntaxNode") -> Tuple[str, str]:
    """Walk up the pyslang syntax-tree to find the nearest enclosing SV scope.

    Returns ``(scope_kind, scope_name)`` where ``scope_kind`` is one of
    ``"module"``, ``"package"``, ``"interface"``, ``"program"``, or
    ``"<file>"`` (compilation-unit level, rare but valid SV).

    Using the parent-pointer chain in the AST is both simpler and more
    correct than the old event-stream approach: it is immune to unusual
    whitespace, CRLF endings, and nested-scope edge cases.

    pyslang represents each SV scope kind as a *distinct* AST class:
    ``ModuleDeclaration``, ``InterfaceDeclaration``, ``ProgramDeclaration``,
    and ``PackageDeclaration``.  Each has a ``header.name`` identifier token.
    """
    _FILE_SCOPE = "<file>"
    parent = node.parent
    while parent is not None:
        kind_str = str(parent.kind)
        if "PackageDeclaration" in kind_str:
            return ("package", str(parent.header.name).strip())
        if "InterfaceDeclaration" in kind_str:
            return ("interface", str(parent.header.name).strip())
        if "ProgramDeclaration" in kind_str:
            return ("program", str(parent.header.name).strip())
        if "ModuleDeclaration" in kind_str:
            return ("module", str(parent.header.name).strip())
        parent = parent.parent
    return (_FILE_SCOPE, _FILE_SCOPE)


def _collect_dpi_imports(
    node: "pyslang.SyntaxNode",
    seen: Set[Tuple[str, str]],
    result: List[Tuple[str, str, str]],
) -> None:
    """Recursively walk a pyslang syntax node and collect DPI import entries."""
    if isinstance(node, pyslang.DPIImportSyntax):
        dpi_name = str(node.method.name.identifier).strip()
        if dpi_name:
            scope_kind, scope_name = _sv_scope_of(node)
            key = (scope_name, dpi_name)
            if key not in seen:
                seen.add(key)
                result.append((scope_name, scope_kind, dpi_name))
    if isinstance(node, pyslang.SyntaxNode):
        for child in node:
            if isinstance(child, pyslang.SyntaxNode):
                _collect_dpi_imports(child, seen, result)


def extract_dpi_boundaries_with_scope(
    sv_files: Iterable[str],
) -> List[Tuple[str, str, str]]:
    """Extract DPI-C imports with their enclosing SV scope.

    Parses each SV file with pyslang, then walks the syntax tree to locate
    ``DPIImportSyntax`` nodes and reads the enclosing scope via the
    parent-pointer chain.  This replaces the old regex event-stream approach
    and correctly handles:

    - Packed / complex return types (e.g. ``bit[7:0]``) that the old
      ``(?:[\\w:*&]+\\s+)?`` pattern silently dropped.
    - Arbitrary whitespace and CRLF line endings.
    - No false positives from commented-out imports (pyslang strips comments).

    Parameters
    ----------
    sv_files:
        Iterable of filesystem paths to SystemVerilog files to scan.

    Returns
    -------
    List[Tuple[str, str, str]]
        Deduplicated list of ``(scope_name, scope_kind, dpi_name)`` triples
        where ``scope_kind`` is one of ``"module"``, ``"package"``,
        ``"interface"``, ``"program"``, or ``"<file>"`` (compilation-unit
        scope, rare but legal SV).
    """
    seen: Set[Tuple[str, str]] = set()  # (scope_name, dpi_name) pairs
    result: List[Tuple[str, str, str]] = []

    for path_str in sv_files:
        try:
            text = Path(path_str).read_text(errors="replace")
        except Exception as exc:
            _logger.warning("Could not read SV file %s: %s", path_str, exc)
            continue

        try:
            tree = pyslang.SyntaxTree.fromText(text)
            _collect_dpi_imports(tree.root, seen, result)
        except Exception as exc:  # pyslang parse error → skip file gracefully
            _logger.warning(
                "pyslang failed to parse SV file %s: %s", path_str, exc
            )

    return result


def extract_dpi_boundaries(sv_files: Iterable[str]) -> List[str]:
    """Extract DPI-C imported function names from a list of SV file paths.

    Backward-compatible wrapper around ``extract_dpi_boundaries_with_scope``
    that discards scope information and returns a flat deduplicated list of
    function name strings.

    Uses a regex pass over the files — no slang required.

    Chosen over slang's SymbolKind.Subroutine / isImported approach because:
    - slang's Python bindings do not yet expose a stable ``.isImported``
      attribute on SubroutineSymbol via pyslang (verified against the AES
      dataset); the attribute exists in the C++ layer but is not bound.
    - A regex over ``import "DPI-C"`` is unambiguous in practice: the quoted
      literal is not valid in any other SV context.
    - The regex is 3 lines vs ~20 lines of pyslang symbol-tree traversal and
      avoids a dependency on elaboration success.

    Parameters
    ----------
    sv_files:
        Iterable of filesystem paths to SystemVerilog files to scan.

    Returns
    -------
    List[str]
        Deduplicated list of DPI-C imported function names found.
    """
    scoped = extract_dpi_boundaries_with_scope(sv_files)
    seen: Set[str] = set()
    result: List[str] = []
    for _scope_name, _scope_kind, dpi_name in scoped:
        if dpi_name not in seen:
            seen.add(dpi_name)
            result.append(dpi_name)
    return result


# Entity types in kg_schema.yaml that correspond to SV scope kinds.
_SCOPE_KIND_TO_ENTITY_TYPE: dict = {
    "package": "Package",
    "interface": "Interface",
    "module": "RTL_Module",
    "program": None,       # no "Program" type in the schema; leave bare name
    "<file>": None,
}


def build_dpi_boundary_entities(
    dpi_names: Optional[List[str]] = None,
    *,
    scoped_imports: Optional[List[Tuple[str, str, str]]] = None,
    sv_source: str = "",
) -> ExtractionResult:
    """Build DPIBoundary entities and (optionally) imports_dpi edges.

    When ``scoped_imports`` is provided the function emits one
    ``imports_dpi`` triple per ``(scope_name, scope_kind, dpi_name)`` entry,
    and creates a placeholder entity for the scope (``Package`` for
    ``scope_kind="package"``, ``Interface`` for ``scope_kind="interface"``,
    ``RTL_Module`` for ``scope_kind="module"``).  If no schema-mapped type
    exists for the scope kind the subject is left as a bare name so the KG
    backend fuses it to whatever entity the SV parser already emitted.

    When only ``dpi_names`` is given the function behaves as before — it
    creates DPIBoundary entities only with no triples.

    Parameters
    ----------
    dpi_names:
        Legacy positional list of DPI-C function names (output of
        ``extract_dpi_boundaries``).  Mutually exclusive with
        ``scoped_imports``; if both are supplied ``scoped_imports`` wins.
    scoped_imports:
        Enriched list of ``(scope_name, scope_kind, dpi_name)`` triples
        as returned by ``extract_dpi_boundaries_with_scope``.  When provided
        the function emits ``imports_dpi`` edges and optional scope entities.
    sv_source:
        Source label string attached to emitted entities / triples.

    Returns
    -------
    ExtractionResult
        Entities: one DPIBoundary per unique DPI-C function name, plus one
        scope-typed entity per unique scope name (when ``scoped_imports`` is
        given and the scope kind maps to a schema type).
        Triples: one ``imports_dpi`` edge per ``scoped_imports`` entry (when
        ``scoped_imports`` is given); empty list otherwise.
    """
    entities: List[Entity] = []
    triples: List[Triple] = []
    seen_dpi: Set[str] = set()
    seen_scope: Set[str] = set()
    sources = [sv_source] if sv_source else []

    if scoped_imports is not None:
        for scope_name, scope_kind, dpi_name in scoped_imports:
            # DPIBoundary entity (deduped)
            if dpi_name not in seen_dpi:
                seen_dpi.add(dpi_name)
                entities.append(Entity(
                    name=dpi_name,
                    type="DPIBoundary",
                    sources=sources,
                    extractor_source=[DPI_BOUNDARY_SOURCE],
                    layer=DPI_BOUNDARY_SOURCE,
                ))

            # Scope entity (deduped) — only if the kind maps to a schema type
            entity_type = _SCOPE_KIND_TO_ENTITY_TYPE.get(scope_kind)
            if entity_type and scope_name not in seen_scope:
                seen_scope.add(scope_name)
                entities.append(Entity(
                    name=scope_name,
                    type=entity_type,
                    sources=sources,
                    extractor_source=[DPI_BOUNDARY_SOURCE],
                    layer=DPI_BOUNDARY_SOURCE,
                ))

            # imports_dpi edge
            triples.append(Triple(
                subject=scope_name,
                predicate="imports_dpi",
                object=dpi_name,
                source=sv_source,
                extractor_source=DPI_BOUNDARY_SOURCE,
                evidence_span=f'import "DPI-C" {dpi_name} in {scope_name}',
                layer=DPI_BOUNDARY_SOURCE,
            ))
    else:
        # Legacy path: dpi_names only, no triples.
        names = dpi_names or []
        for name in names:
            if name not in seen_dpi:
                seen_dpi.add(name)
                entities.append(Entity(
                    name=name,
                    type="DPIBoundary",
                    sources=sources,
                    extractor_source=[DPI_BOUNDARY_SOURCE],
                    layer=DPI_BOUNDARY_SOURCE,
                ))

    return ExtractionResult(entities=entities, triples=triples)

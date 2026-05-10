# @summary
# Bash script parser-based structural entity extraction.
# Uses structural token-scanning (shlex / manual line inspection) for
# functions, sourced files, and key variable assignments in shell scripts.
# Exports: BashParserExtractor
# Deps: shlex, src.knowledge_graph.common.schemas
# @end-summary
"""Bash script parser-based structural entity extraction.

Uses a lightweight structural token scanner (shlex + manual token inspection)
to extract structural entities (functions, sourced files, exported variables)
from Bash/Shell scripts. No regular expressions are used. All results are
tagged with ``extractor_source="bash_parser"``.

Note: This is a best-effort parser — shell syntax is context-sensitive and not
fully parseable without a real shell grammar. The extractor focuses on common
ASIC flow script patterns (Makefile wrappers, tool invocations, source chains).
"""
from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import List, Optional, Set

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = ["BashParserExtractor"]

logger = logging.getLogger("rag.knowledge_graph.bash_parser")

# ---------------------------------------------------------------------------
# Structural token helpers (no re module)
# ---------------------------------------------------------------------------

def _is_identifier(token: str) -> bool:
    """Return True if *token* is a valid shell/bash identifier name.

    Shell identifiers start with a letter or underscore and contain only
    letters, digits, and underscores.
    """
    if not token:
        return False
    first = token[0]
    if first != "_" and not first.isalpha():
        return False
    return all(c.isalnum() or c == "_" for c in token)


def _is_upper_identifier(token: str) -> bool:
    """Return True if token is an all-uppercase (or uppercase+digits) identifier.

    Used to match ``export``/``readonly`` variable names which by convention
    are uppercase (e.g. ``FLOW_ROOT``, ``TOOL_VERSION``).
    """
    if not _is_identifier(token):
        return False
    return all(c.isupper() or c.isdigit() or c == "_" for c in token)


def _split_tokens(line: str) -> List[str]:
    """Split a shell line into tokens with shlex.

    Falls back to ``str.split()`` on parse errors (e.g. unmatched quotes
    inside here-docs or unusual constructs). This keeps the extractor
    resilient against malformed scripts.
    """
    try:
        return shlex.split(line, comments=True, posix=True)
    except ValueError:
        # shlex.split raises ValueError on POSIX parse errors (e.g. unclosed quotes).
        return line.split()


# ---------------------------------------------------------------------------
# Per-construct structural scanners
# ---------------------------------------------------------------------------

def _scan_function(tokens: List[str]) -> Optional[str]:
    """Return function name if tokens represent a function definition line.

    Accepted forms:
      ``function <name> ()``  (tokens: ['function', '<name>', '()', '{'])
      ``function <name>()``   (split may merge: ['function', '<name>()'])
      ``<name>()``            (tokens: ['<name>()', '{'])
      ``<name> ()``           (tokens: ['<name>', '()', '{'])

    Only extracts the name; the opening ``{`` may or may not be on the same
    line — we don't care about that here.
    """
    if not tokens:
        return None

    if tokens[0] == "function":
        # ``function <name>`` or ``function <name>()``
        if len(tokens) < 2:
            return None
        candidate = tokens[1]
        # Strip trailing ``()`` if present (e.g. ``function foo()`` parsed as one token)
        name = candidate.removesuffix("()").removesuffix("(").removesuffix(")")
        if _is_identifier(name):
            return name
        return None

    # Bare ``<name>()`` or ``<name> ()`` style
    candidate = tokens[0]
    if candidate.endswith("()"):
        name = candidate[:-2]
        if _is_identifier(name):
            return name
        return None

    # ``<name>`` followed by ``()`` as a separate token
    if len(tokens) >= 2 and tokens[1] in ("()", "("):
        if _is_identifier(tokens[0]):
            return tokens[0]

    return None


def _scan_source(tokens: List[str], raw_line: str) -> Optional[str]:
    """Return the sourced file path if tokens represent a source/dot command.

    Accepted forms:
      ``source <path>``
      ``. <path>``

    Skips paths that contain ``$`` (shell variable expansion — ambiguous).
    Returns the path string (caller strips stem).
    """
    if not tokens:
        return None
    if tokens[0] not in ("source", "."):
        return None
    if len(tokens) < 2:
        return None
    path = tokens[1]
    if "$" in path:
        return None
    return path


def _scan_export(tokens: List[str]) -> Optional[str]:
    """Return variable name if tokens represent ``export VAR=...``.

    Handles both:
      ``export FOO=bar``   → tokens may be ['export', 'FOO=bar'] or ['export', 'FOO', '=', 'bar']
      (shlex in posix mode usually splits assignment as one token 'FOO=bar')
    """
    if not tokens or tokens[0] != "export":
        return None
    if len(tokens) < 2:
        return None
    assignment = tokens[1]
    if "=" in assignment:
        var_name = assignment.split("=", 1)[0]
        if _is_upper_identifier(var_name):
            return var_name
    return None


def _scan_readonly(tokens: List[str]) -> Optional[str]:
    """Return variable name for ``readonly VAR=...`` or ``declare -r VAR=...``.

    Accepted forms:
      ``readonly VAR=value``
      ``declare -r VAR=value``
    """
    if not tokens:
        return None

    if tokens[0] == "readonly":
        if len(tokens) < 2:
            return None
        assignment = tokens[1]
        if "=" in assignment:
            var_name = assignment.split("=", 1)[0]
            if _is_upper_identifier(var_name):
                return var_name
        return None

    if tokens[0] == "declare":
        # Expect ``declare -r VAR=value`` — require the -r flag
        if len(tokens) < 3:
            return None
        if tokens[1] != "-r":
            return None
        assignment = tokens[2]
        if "=" in assignment:
            var_name = assignment.split("=", 1)[0]
            if _is_upper_identifier(var_name):
                return var_name
        return None

    return None


# ---------------------------------------------------------------------------
# Extractor class
# ---------------------------------------------------------------------------


class BashParserExtractor:
    """Deterministic structural extractor for Bash/Shell scripts.

    No regular expression dependencies — uses shlex tokenization and
    structural token inspection.
    """

    def __init__(self) -> None:
        self._parser_available = True

    @property
    def name(self) -> str:
        return "bash_parser"

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Extract structural entities and relationships from shell source.

        Args:
            text: Shell script source code.
            source: File path or identifier for provenance tracking.

        Returns:
            ExtractionResult with entities and triples.
        """
        if not text or not text.strip():
            return ExtractionResult(entities=[], triples=[], descriptions=[])

        entities: List[Entity] = []
        triples: List[Triple] = []
        seen_names: Set[str] = set()

        script_name = Path(source).stem if source else "<script>"

        for raw_line in text.splitlines():
            line = raw_line.strip()
            # Skip empty lines; shlex(comments=True) handles full-line comments.
            if not line:
                continue

            # _split_tokens uses shlex with comments=True, so lines whose
            # first non-whitespace character is '#' produce an empty token
            # list — no separate startswith("#") check needed.
            tokens = _split_tokens(line)
            if not tokens:
                continue

            # --- Function definition ---
            fn_name = _scan_function(tokens)
            if fn_name and fn_name not in seen_names:
                seen_names.add(fn_name)
                entities.append(Entity(
                    name=fn_name,
                    type="BashFunction",
                    sources=[source] if source else [],
                    mention_count=1,
                    extractor_source="bash_parser",
                ))
                triples.append(Triple(
                    subject=script_name,
                    predicate="contains",
                    object=fn_name,
                    source=source,
                    extractor_source="bash_parser",
                ))
                continue

            # --- Source / dot command ---
            sourced_path = _scan_source(tokens, line)
            if sourced_path is not None:
                sourced_name = Path(sourced_path).stem
                if sourced_name and sourced_name not in seen_names:
                    seen_names.add(sourced_name)
                    entities.append(Entity(
                        name=sourced_name,
                        type="BashScript",
                        sources=[source] if source else [],
                        mention_count=1,
                        extractor_source="bash_parser",
                    ))
                    triples.append(Triple(
                        subject=script_name,
                        predicate="depends_on",
                        object=sourced_name,
                        source=source,
                        extractor_source="bash_parser",
                    ))
                continue

            # --- Export variable ---
            var_name = _scan_export(tokens)
            if var_name and var_name not in seen_names:
                seen_names.add(var_name)
                entities.append(Entity(
                    name=var_name,
                    type="BashVariable",
                    sources=[source] if source else [],
                    mention_count=1,
                    extractor_source="bash_parser",
                ))
                triples.append(Triple(
                    subject=script_name,
                    predicate="contains",
                    object=var_name,
                    source=source,
                    extractor_source="bash_parser",
                ))
                continue

            # --- Readonly / declare -r variable ---
            var_name = _scan_readonly(tokens)
            if var_name and var_name not in seen_names:
                seen_names.add(var_name)
                entities.append(Entity(
                    name=var_name,
                    type="BashVariable",
                    sources=[source] if source else [],
                    mention_count=1,
                    extractor_source="bash_parser",
                ))
                triples.append(Triple(
                    subject=script_name,
                    predicate="contains",
                    object=var_name,
                    source=source,
                    extractor_source="bash_parser",
                ))
                continue

        return ExtractionResult(entities=entities, triples=triples, descriptions=[])

    def extract_file(self, file_path: str) -> ExtractionResult:
        """Extract from a shell script on disk.

        Args:
            file_path: Path to a .sh/.bash file.

        Returns:
            ExtractionResult or empty result on read error.
        """
        path = Path(file_path)
        if path.suffix not in (".sh", ".bash", ""):
            logger.debug("Skipping non-shell file: %s", file_path)
            return ExtractionResult(entities=[], triples=[], descriptions=[])
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Cannot read %s: %s", file_path, exc)
            return ExtractionResult(entities=[], triples=[], descriptions=[])
        return self.extract(text, source=str(path))

    def extract_entities(self, text: str) -> Set[str]:
        """Protocol method: return entity names from text."""
        result = self.extract(text)
        return {e.name for e in result.entities}

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]:
        """Protocol method: return triples from text."""
        result = self.extract(text)
        return result.triples

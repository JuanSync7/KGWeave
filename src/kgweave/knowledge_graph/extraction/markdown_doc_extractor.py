# @summary
# Markdown documentation extractor with RTL doc fusion.
# Parses headers into Section entities, emits `references` edges for in-doc
# anchor links, and fuses references to known RTL entities by emitting
# same-named/typed entities (the backend's case-insensitive dedup merges
# them, growing the original entity's ``sources`` list with the doc path).
# Exports: MarkdownDocExtractor
# Deps: mistune, os, src.knowledge_graph.common
# @end-summary
"""Markdown documentation extractor.

Walks a markdown document and emits:

* ``Section`` entities for every h1/h2/h3 header, named
  ``{source_basename}#{slugified-header}``.
* ``references`` triples for in-doc links of the form
  ``[label](#anchor)`` or ``[label](file.md#anchor)``.
* Fusion entities for case-insensitive whole-word mentions of any name in
  the supplied ``known_entity_names`` iterable. Each fusion entity has the
  same canonical name and assumes type ``RTL_Module`` by default; when the
  backend already has the entity, ``upsert_entities`` merges the new doc
  source into the existing entity's ``sources`` list and preserves the
  original type.

All emitted entities/triples are tagged ``extractor_source="markdown_doc"``
for confidence-prior routing.

Parser strategy: uses **mistune** (``create_markdown(renderer=None)``) to
produce a typed AST.  Every extraction step walks this AST instead of
applying raw-text regex patterns, making the extractor resilient to
arbitrary well-formed Markdown (ATX and setext headings, nested emphasis,
fenced code blocks, etc.).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import mistune

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = ["MarkdownDocExtractor", "MARKDOWN_DOC_SOURCE"]


MARKDOWN_DOC_SOURCE = "markdown_doc"

# Module-level parser instance (thread-safe for read-only AST generation).
_MD_PARSER = mistune.create_markdown(renderer=None)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _ast_text(node: Dict[str, Any]) -> str:
    """Recursively collect plain text from an AST node's children."""
    if node.get("type") == "text":
        return node.get("raw", "")
    parts: List[str] = []
    for child in node.get("children") or []:
        parts.append(_ast_text(child))
    return "".join(parts)


def _ast_heading_raw(node: Dict[str, Any]) -> str:
    """Reconstruct the raw inline text of a heading node.

    Mirrors what the old ATX-regex capture group(2) returned: for plain text
    nodes, yields the raw text; for link nodes, yields ``[label](url)`` so
    that slugification produces the same anchor as before (important for
    backward-compatible graph node keys when a heading contains a hyperlink).
    """
    if node.get("type") == "text":
        return node.get("raw", "")
    if node.get("type") == "link":
        label = "".join(_ast_heading_raw(c) for c in (node.get("children") or []))
        url = (node.get("attrs") or {}).get("url", "")
        return f"[{label}]({url})"
    parts: List[str] = []
    for child in node.get("children") or []:
        parts.append(_ast_heading_raw(child))
    return "".join(parts)


def _iter_nodes(ast: List[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """Depth-first yield of every node in the AST."""
    for node in ast:
        yield node
        for child in node.get("children") or []:
            yield from _iter_nodes([child])


# ---------------------------------------------------------------------------
# Slugify — pure string, no regex
# ---------------------------------------------------------------------------

def _slugify(header: str) -> str:
    """Slugify a markdown header to a GitHub-style anchor.

    Lowercases, strips non-alphanumerics (keeping ``-`` and spaces), and
    collapses whitespace/underscore runs into single hyphens.
    Uses pure string operations instead of regex.
    """
    text = header.strip().lower()
    # Keep only word chars (letters, digits, underscore), spaces, and hyphens.
    kept: List[str] = []
    for ch in text:
        if ch.isalnum() or ch == "-":
            kept.append(ch)
        elif ch in (" ", "_"):
            # Will be collapsed into a hyphen below.
            kept.append(" ")
        # All other punctuation is dropped.
    text = "".join(kept)
    # Collapse whitespace runs → single hyphen.
    parts = text.split()
    text = "-".join(parts)
    # Collapse hyphen runs → single hyphen, strip leading/trailing hyphens.
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-")


def _basename(source: str) -> str:
    """Return the basename of *source*, or the source itself if no path sep."""
    if not source:
        return ""
    return os.path.basename(source)


# ---------------------------------------------------------------------------
# Whole-word case-insensitive matching — pure string, no regex
# ---------------------------------------------------------------------------

_WORD_CHARS: frozenset = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789_"
)


def _find_whole_word(text: str, needle: str) -> List[int]:
    """Return start offsets of all case-insensitive whole-word occurrences of
    *needle* in *text* without using ``re``.

    A "word boundary" is a position where the adjacent character is not in
    ``[A-Za-z0-9_]``.
    """
    needle_lower = needle.lower()
    n = len(needle)
    result: List[int] = []
    text_lower = text.lower()
    start = 0
    while True:
        pos = text_lower.find(needle_lower, start)
        if pos == -1:
            break
        # Check left boundary.
        if pos > 0 and text[pos - 1] in _WORD_CHARS:
            start = pos + 1
            continue
        # Check right boundary.
        end = pos + n
        if end < len(text) and text[end] in _WORD_CHARS:
            start = pos + 1
            continue
        result.append(pos)
        start = pos + n
    return result


class MarkdownDocExtractor:
    """Markdown documentation extractor with RTL fusion.

    Parameters
    ----------
    known_entity_names:
        Optional iterable of canonical entity names to look for in the body.
        Each whole-word, case-insensitive occurrence outside code spans
        emits a fusion entity (same canonical name, default type
        ``RTL_Module``) so the backend's existing dedup will merge the doc
        source into the original entity.
    known_entity_types:
        Optional mapping of ``canonical_name -> entity_type`` to override
        the default fusion type per entity. When absent, ``RTL_Module`` is
        assumed (the typical use case is RTL-doc fusion). Callers wanting
        to fuse with a non-RTL_Module entity can pass an explicit map.
    """

    @property
    def name(self) -> str:
        """Extractor identifier reported on emitted entities/triples."""
        return MARKDOWN_DOC_SOURCE

    def __init__(
        self,
        known_entity_names: Optional[Iterable[str]] = None,
        known_entity_types: Optional[Dict[str, str]] = None,
    ) -> None:
        names = list(known_entity_names) if known_entity_names else []
        # Deduplicate while preserving canonical casing.
        seen_lower: Set[str] = set()
        self._known_names: List[str] = []
        for n in names:
            if not n:
                continue
            key = n.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            self._known_names.append(n)

        self._known_types: Dict[str, str] = dict(known_entity_types or {})

    # -- Public API ----------------------------------------------------------

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Extract Section entities, references edges, and fusion entities."""
        base = _basename(source)
        ast = _MD_PARSER(text)  # list of top-level AST nodes

        sections, header_to_section = self._extract_sections(ast, base, source)
        triples = self._extract_references(ast, base, source, header_to_section)
        fusion, mentions = self._extract_fusion_entities_and_mentions(
            ast, text, source, base, header_to_section
        )
        triples.extend(mentions)

        return ExtractionResult(entities=sections + fusion, triples=triples)

    def extract_entities(self, text: str) -> Set[str]:
        """Return entity name strings (EntityExtractor protocol)."""
        return {e.name for e in self.extract(text).entities}

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]:
        """Return relation triples (EntityExtractor protocol)."""
        return self.extract(text).triples

    # -- Internal helpers ----------------------------------------------------

    def _extract_sections(
        self,
        ast: List[Dict[str, Any]],
        base: str,
        source: str,
    ) -> Tuple[List[Entity], Dict[str, str]]:
        """Walk h1/h2/h3 heading nodes and emit Section entities.

        Returns the list of entities and a mapping from
        ``slug -> section_name`` to support intra-doc reference resolution.
        Handles both ATX (``# Heading``) and setext (underline) styles via
        the mistune AST ``heading`` node.
        """
        entities: List[Entity] = []
        slug_to_name: Dict[str, str] = {}

        for node in ast:
            if node.get("type") != "heading":
                continue
            level = node.get("attrs", {}).get("level", 0)
            if level < 1 or level > 3:
                continue
            # Use _ast_heading_raw so that link-in-heading nodes reproduce the
            # original [label](url) syntax, giving backward-compatible slugs.
            header = _ast_heading_raw(node).strip()
            slug = _slugify(header)
            if not slug:
                continue
            section_name = f"{base}#{slug}" if base else f"#{slug}"
            if slug in slug_to_name:
                # Duplicate header text — keep the first occurrence as canonical.
                continue
            slug_to_name[slug] = section_name
            entities.append(
                Entity(
                    name=section_name,
                    type="Section",
                    sources=[source] if source else [],
                    extractor_source=[MARKDOWN_DOC_SOURCE],
                )
            )

        return entities, slug_to_name

    def _extract_references(
        self,
        ast: List[Dict[str, Any]],
        base: str,
        source: str,
        header_to_section: Dict[str, str],
    ) -> List[Triple]:
        """Emit ``references`` triples for ``[label](target)`` links.

        For each link node, identify the section it sits inside (the most
        recent preceding top-level heading node) and emit
        ``current_section --references--> target_section``.
        """
        triples: List[Triple] = []
        current_section: Optional[str] = None

        for node in ast:
            if node.get("type") == "heading":
                level = node.get("attrs", {}).get("level", 0)
                if 1 <= level <= 3:
                    header = _ast_heading_raw(node).strip()
                    slug = _slugify(header)
                    current_section = header_to_section.get(slug) if slug else None

            # Walk all link nodes inside this top-level node.
            for child in _iter_nodes([node]):
                if child.get("type") != "link":
                    continue
                target = (child.get("attrs") or {}).get("url", "").strip()
                target_section = self._resolve_link_target(target, base)
                if target_section is None:
                    continue
                if current_section is None or current_section == target_section:
                    continue
                triples.append(
                    Triple(
                        subject=current_section,
                        predicate="references",
                        object=target_section,
                        source=source,
                        extractor_source=MARKDOWN_DOC_SOURCE,
                    )
                )

        return triples

    @staticmethod
    def _resolve_link_target(target: str, base: str) -> Optional[str]:
        """Convert a markdown link target to a Section canonical name.

        Handles:
        * ``#anchor`` — same-document anchor.
        * ``other.md#anchor`` — cross-document anchor.
        * ``other.md`` — bare doc reference (no anchor → unsupported, skip).
        """
        if not target:
            return None
        if target.startswith("#"):
            anchor = target.lstrip("#").strip()
            if not anchor or not base:
                return None
            return f"{base}#{anchor}"
        if "#" in target:
            file_part, _, anchor = target.partition("#")
            file_base = _basename(file_part)
            anchor = anchor.strip()
            if not file_base or not anchor:
                return None
            return f"{file_base}#{anchor}"
        # External URLs or bare files without anchors are not section refs.
        return None

    def _extract_fusion_entities_and_mentions(
        self,
        ast: List[Dict[str, Any]],
        raw_text: str,
        source: str,
        base: str,
        header_to_section: Dict[str, str],
    ) -> Tuple[List[Entity], List[Triple]]:
        """Emit fusion entities AND ``Section --mentions--> Module`` edges.

        Prose text is collected from the AST, skipping ``block_code`` and
        ``codespan`` nodes so that mentions inside code blocks/spans are
        excluded from entity fusion.

        Without the mentions edges, doc Sections form a disconnected component
        in the KG and ForceAtlas2 banishes them to the periphery. Anchoring
        each section to the modules it discusses ties prose into the design.
        """
        if not self._known_names:
            return [], []

        # Build a mapping: top-level heading index → section_name, and collect
        # prose segments per section, excluding code blocks/spans.
        # Structure: list of (section_name_or_None, prose_str)
        sections_prose: List[Tuple[Optional[str], str]] = []
        current_section: Optional[str] = None

        for node in ast:
            if node.get("type") == "heading":
                level = node.get("attrs", {}).get("level", 0)
                if 1 <= level <= 3:
                    header = _ast_heading_raw(node).strip()
                    slug = _slugify(header)
                    current_section = header_to_section.get(slug) if slug else None
                continue

            if node.get("type") in ("block_code", "blank_line"):
                # block_code → skip entirely (no prose here).
                continue

            if node.get("type") == "block_html":
                # HTML comments/blocks: include their raw text so that entity
                # names embedded in generator comments (e.g. ``<!-- BEGIN CMDGEN
                # ... aes.hjson -->``) are treated as prose, matching the old
                # regex-on-raw-text behaviour.
                raw = node.get("raw", "")
                if raw:
                    sections_prose.append((current_section, raw))
                continue

            # Collect prose text, skipping codespan nodes.
            prose = _collect_prose(node)
            if prose:
                sections_prose.append((current_section, prose))

        entities: List[Entity] = []
        triples: List[Triple] = []
        seen_entity: Set[str] = set()
        seen_mention: Set[Tuple[str, str]] = set()

        for canonical in self._known_names:
            for sec, prose in sections_prose:
                offsets = _find_whole_word(prose, canonical)
                if not offsets:
                    continue

                key = canonical.lower()
                if key not in seen_entity:
                    seen_entity.add(key)
                    entity_type = self._known_types.get(canonical, "RTL_Module")
                    entities.append(
                        Entity(
                            name=canonical,
                            type=entity_type,
                            sources=[source] if source else [],
                            extractor_source=[MARKDOWN_DOC_SOURCE],
                        )
                    )

                if sec is None:
                    continue
                if (sec, canonical) in seen_mention:
                    continue
                seen_mention.add((sec, canonical))
                triples.append(
                    Triple(
                        subject=sec,
                        predicate="mentions",
                        object=canonical,
                        source=source,
                        extractor_source=MARKDOWN_DOC_SOURCE,
                    )
                )

        return entities, triples


def _collect_prose(node: Dict[str, Any]) -> str:
    """Recursively collect non-code text from an AST node.

    Skips ``codespan`` nodes so that backtick-wrapped text is excluded from
    entity-name matching.
    """
    if node.get("type") == "codespan":
        return ""
    if node.get("type") == "text":
        return node.get("raw", "")
    parts: List[str] = []
    for child in node.get("children") or []:
        parts.append(_collect_prose(child))
    return " ".join(p for p in parts if p)

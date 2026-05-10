# @summary
# Markdown documentation extractor with RTL doc fusion.
# Parses headers into Section entities, emits `references` edges for in-doc
# anchor links, and fuses references to known RTL entities by emitting
# same-named/typed entities (the backend's case-insensitive dedup merges
# them, growing the original entity's ``sources`` list with the doc path).
# Exports: MarkdownDocExtractor
# Deps: re, os, src.knowledge_graph.common
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
"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = ["MarkdownDocExtractor", "MARKDOWN_DOC_SOURCE"]


MARKDOWN_DOC_SOURCE = "markdown_doc"

# h1/h2/h3 ATX-style headers at line start (allow trailing # in some flavours)
_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$", re.MULTILINE)

# Inline markdown link: [label](target)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# Fenced code block (```...```) and inline code spans (`...`) — to be stripped
# before whole-word matching of known entity names.
_FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _slugify(header: str) -> str:
    """Slugify a markdown header to a GitHub-style anchor.

    Lowercases, strips non-alphanumerics (keeping ``-`` and spaces), and
    collapses whitespace runs into single hyphens.
    """
    text = header.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def _basename(source: str) -> str:
    """Return the basename of *source*, or the source itself if no path sep."""
    if not source:
        return ""
    return os.path.basename(source)


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

        sections, header_to_section = self._extract_sections(text, base, source)
        triples = self._extract_references(text, base, source, header_to_section)
        fusion, mentions = self._extract_fusion_entities_and_mentions(
            text, source, base, header_to_section
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
        self, text: str, base: str, source: str
    ) -> Tuple[List[Entity], Dict[str, str]]:
        """Walk h1/h2/h3 headers and emit Section entities.

        Returns the list of entities and a mapping from
        ``slug -> section_name`` to support intra-doc reference resolution.
        """
        entities: List[Entity] = []
        slug_to_name: Dict[str, str] = {}

        for match in _HEADER_RE.finditer(text):
            header = match.group(2).strip()
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
        text: str,
        base: str,
        source: str,
        header_to_section: Dict[str, str],
    ) -> List[Triple]:
        """Emit ``references`` triples for ``[label](target)`` links.

        For each link, identify the section the link sits inside (the most
        recent preceding header) and emit ``current_section --references-->
        target_section``.
        """
        triples: List[Triple] = []

        # Pre-compute (offset, section_name) pairs sorted by offset for
        # efficient "current section" lookup per link.
        header_offsets: List[Tuple[int, str]] = []
        for match in _HEADER_RE.finditer(text):
            slug = _slugify(match.group(2).strip())
            if not slug:
                continue
            sec_name = header_to_section.get(slug)
            if sec_name is None:
                continue
            header_offsets.append((match.start(), sec_name))

        def _section_at(offset: int) -> Optional[str]:
            current: Optional[str] = None
            for off, sec in header_offsets:
                if off <= offset:
                    current = sec
                else:
                    break
            return current

        for match in _LINK_RE.finditer(text):
            target = match.group(2).strip()
            target_section = self._resolve_link_target(target, base)
            if target_section is None:
                continue

            current_section = _section_at(match.start())
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
        text: str,
        source: str,
        base: str,
        header_to_section: Dict[str, str],
    ) -> Tuple[List[Entity], List[Triple]]:
        """Emit fusion entities AND ``Section --mentions--> Module`` edges.

        Without the mentions edges, doc Sections form a disconnected component
        in the KG and ForceAtlas2 banishes them to the periphery. Anchoring
        each section to the modules it discusses ties prose into the design.
        """
        if not self._known_names:
            return [], []

        # Strip fenced and inline code so a literal `aes_core` mention in a
        # backtick span doesn't fuse — we want references in actual prose.
        stripped = _FENCED_BLOCK_RE.sub(lambda m: " " * len(m.group(0)), text)
        stripped = _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), stripped)

        # Pre-compute (offset, section_name) pairs to map matches → section.
        header_offsets: List[Tuple[int, str]] = []
        for match in _HEADER_RE.finditer(text):
            slug = _slugify(match.group(2).strip())
            sec_name = header_to_section.get(slug) if slug else None
            if sec_name is not None:
                header_offsets.append((match.start(), sec_name))

        def _section_at(offset: int) -> Optional[str]:
            current: Optional[str] = None
            for off, sec in header_offsets:
                if off <= offset:
                    current = sec
                else:
                    break
            return current

        entities: List[Entity] = []
        triples: List[Triple] = []
        seen_entity: Set[str] = set()
        seen_mention: Set[Tuple[str, str]] = set()

        for canonical in self._known_names:
            pattern = re.compile(
                r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE
            )
            matches = list(pattern.finditer(stripped))
            if not matches:
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

            # One mentions edge per (section, module) pair, even if the same
            # module is mentioned multiple times within the section.
            for m in matches:
                sec = _section_at(m.start())
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

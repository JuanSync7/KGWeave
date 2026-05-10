# @summary
# LLM-driven spec-claim extractor: turns markdown prose into queryable claim
# nodes (Structural / Behavioral / Protocol / Security) plus claims_about,
# target_entity, decomposes_into edges. Walks the document section-by-section,
# batches each section's prose through a provider with `.generate(prompt)`
# returning JSON, and fuses claim targets against known_entity_names.
# Exports: SpecClaimExtractor, LLM_DOC_SOURCE, CLAIM_EXTRACTION_PROMPT
# Deps: json, logging, unicodedata, kgweave.knowledge_graph.common
# @end-summary
"""LLM spec-claim extractor.

Closes the natural-language ↔ structure linkage required by the killer audit
query: every prose claim in a spec becomes a first-class node in the KG so we
can ask "for every claim, is there a testpoint / SVA / coverpoint / realized
test for it?". Phase 1 supports four claim types and emits five edge classes;
fusion against ``known_entity_names`` turns claim targets into ``target_entity``
edges to canonical RTL/Spec entities.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = [
    "SpecClaimExtractor",
    "LLM_DOC_SOURCE",
    "CLAIM_EXTRACTION_PROMPT",
    "VALID_CLAIM_TYPES",
    "VALID_VERIFICATION_STRENGTHS",
]


LLM_DOC_SOURCE = "llm_doc"

_logger = logging.getLogger("kgweave.knowledge_graph.spec_claims")


VALID_CLAIM_TYPES: Set[str] = {
    "StructuralClaim",
    "BehavioralClaim",
    "ProtocolClaim",
    "SecurityClaim",
}

VALID_VERIFICATION_STRENGTHS: Set[str] = {
    "equivalence",
    "coverage",
    "decomposed",
    "unverified",
}

def _iter_atx_headers(text: str):
    """Yield (match_start, match_end, level, title) for h1/h2/h3 ATX headers.

    Structural line scanner: replaces the former ``_HEADER_RE`` regex compile.
    An ATX header line begins with 1–3 ``#`` chars followed by at least one
    whitespace character, then the title text, then optionally trailing ``#``
    chars and whitespace.  Blank lines and non-header lines are skipped.
    """
    pos = 0
    for raw_line in text.splitlines(keepends=True):
        line_len = len(raw_line)
        line = raw_line.rstrip("\r\n")
        # Count leading '#' chars (1–3)
        level = 0
        for ch in line:
            if ch == "#":
                level += 1
            else:
                break
        if level < 1 or level > 3:
            pos += line_len
            continue
        rest = line[level:]
        # Must have at least one whitespace after the hashes
        if not rest or rest[0] not in (" ", "\t"):
            pos += line_len
            continue
        title = rest.lstrip()
        # Strip optional trailing ATX closing hashes + spaces
        title = title.rstrip()
        while title.endswith("#"):
            title = title[:-1]
        title = title.rstrip()
        if title:
            yield pos, pos + line_len, level, title
        pos += line_len


def _blank_fenced_blocks(text: str) -> str:
    """Return *text* with every fenced code block replaced by spaces.

    Structural scanner: replaces the former ``_FENCED_BLOCK_RE`` regex compile.
    Walks character-by-character looking for triple-backtick fence openers and
    closers.  Content between the fences is replaced by space characters so that
    downstream length calculations remain stable (same as the old ``lambda m:
    ' ' * len(m.group(0))`` approach).
    """
    result = list(text)
    i = 0
    n = len(text)
    fence = "```"
    flen = len(fence)
    while i <= n - flen:
        if text[i:i + flen] == fence:
            start = i
            i += flen
            # Consume to end of opening fence line (info string)
            while i < n and text[i] != "\n":
                i += 1
            # Search for closing fence
            while i <= n - flen:
                if text[i:i + flen] == fence:
                    end = i + flen
                    # Blank out from start to end (inclusive)
                    for j in range(start, end):
                        result[j] = " "
                    i = end
                    break
                i += 1
            else:
                break  # unclosed fence — leave as-is
        else:
            i += 1
    return "".join(result)


CLAIM_EXTRACTION_PROMPT: str = (
    "You are a hardware-spec claim extractor. Read the prose below and extract "
    "every concrete CLAIM the prose makes about the design. A claim is a "
    "verifiable assertion about structure, behavior, protocol, or security.\n\n"
    "## Claim taxonomy\n"
    "- StructuralClaim: a static structural fact (e.g. \"AES has a 128-bit data path\").\n"
    "- BehavioralClaim: a runtime behavior, latency, throughput, or sequencing "
    "claim (e.g. \"the cipher completes in 14 cycles\").\n"
    "- ProtocolClaim: a signal-level or interface protocol fact "
    "(e.g. \"data_in is sampled on rising edge of clk_i\").\n"
    "- SecurityClaim: a security property or threat-model claim "
    "(e.g. \"the implementation is constant-time\").\n\n"
    "## Verification strength\n"
    "Set verification_strength to one of:\n"
    "- equivalence: matchable structurally (e.g. width / port count)\n"
    "- coverage: needs an SVA or testpoint to verify\n"
    "- decomposed: a parent claim that refines into child claims\n"
    "- unverified: no verification mechanism is implied by the prose\n\n"
    "## Rules\n"
    "- Emit ONLY claims grounded in the prose. Do NOT infer beyond the text.\n"
    "- Use a name from KNOWN_ENTITIES for `target` whenever the prose names "
    "that entity. Otherwise put the most specific noun phrase the prose uses.\n"
    "- `evidence_span` MUST be the original sentence (verbatim, single sentence).\n"
    "- For compound claims, emit a parent claim with type appropriate to the "
    "parent and child claims that reference the parent via `parent_id`.\n"
    "- If you cannot find any claims, return {\"claims\": []}.\n\n"
    "## Output schema (strict JSON, no prose around it)\n"
    "{\n"
    '  "claims": [\n'
    "    {\n"
    '      "id": "c1",\n'
    '      "type": "BehavioralClaim",\n'
    '      "target": "example_module",\n'
    '      "evidence_span": "The cipher completes in 14 cycles.",\n'
    '      "verification_strength": "coverage",\n'
    '      "parent_id": null,\n'
    '      "fields": {"behavior": "completion_latency", "value": "14 cycles"}\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "## KNOWN_ENTITIES\n"
    "{known_entities}\n\n"
    "## Section: {section_name}\n"
    "## Prose\n"
    "```\n{prose}\n```\n"
)


class FakeLLMProvider:
    """Test double that returns canned JSON responses in order.

    Not meant for production use. Intentionally keeps a record of every prompt
    so unit tests can assert on the exact instructions sent to the LLM.
    """

    def __init__(self, responses: Iterable[str]) -> None:
        self.responses: List[str] = list(responses)
        self.calls: List[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            return "{\"claims\": []}"
        return self.responses.pop(0)


class SpecClaimExtractor:
    """Extract spec-claim nodes from markdown prose using an LLM provider.

    Parameters
    ----------
    llm_provider:
        Any object exposing ``.generate(prompt: str) -> str`` returning a JSON
        string matching :data:`CLAIM_EXTRACTION_PROMPT`'s schema. The
        :class:`FakeLLMProvider` in this module is suitable for unit tests.
    known_entity_names:
        Iterable of canonical entity names already present in the KG. Used to
        fuse claim ``target`` strings into ``target_entity`` edges; targets that
        do not match are still emitted (with the literal target name as object).
    schema, config:
        Accepted for symmetry with sibling extractors; not currently consulted.
    """

    extractor_name: str = LLM_DOC_SOURCE

    def __init__(
        self,
        llm_provider: Any,
        known_entity_names: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
    ) -> None:
        self._llm = llm_provider
        self._schema = schema
        self._config = config
        names = list(known_entity_names) if known_entity_names else []
        self._known_lower: Dict[str, str] = {}
        for n in names:
            if not n:
                continue
            self._known_lower.setdefault(n.lower(), n)
        self._known_names: List[str] = list(self._known_lower.values())

    @property
    def name(self) -> str:
        return self.extractor_name

    # -- Public API ----------------------------------------------------------

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Walk *text* section-by-section, extract claims, return a result."""
        if not text or not text.strip():
            return ExtractionResult()

        base = self._basename(source)
        sections = self._iter_sections(text, base)
        if not sections:
            sections = [(self._anonymous_section_name(base), text)]

        entities: List[Entity] = []
        triples: List[Triple] = []
        seen_entities: Set[str] = set()
        section_seen: Set[str] = set()

        for section_name, prose in sections:
            cleaned_prose = _blank_fenced_blocks(prose).strip()
            if not cleaned_prose:
                continue

            raw = self._call_llm(section_name, cleaned_prose)
            parsed = self._safe_parse(raw, source)
            if not parsed:
                continue

            self._upsert_section_entity(
                section_name, source, entities, section_seen
            )
            self._build_claim_objects(
                parsed, section_name, source, entities, triples, seen_entities
            )

        return ExtractionResult(entities=entities, triples=triples)

    def extract_entities(self, text: str) -> Set[str]:
        return {e.name for e in self.extract(text).entities}

    def extract_relations(
        self, text: str, known_entities: Set[str]
    ) -> List[Triple]:
        return self.extract(text).triples

    # -- Section walking -----------------------------------------------------

    @staticmethod
    def _basename(source: str) -> str:
        if not source:
            return ""
        # Mimic os.path.basename semantics without importing os twice.
        for sep in ("/", "\\"):
            if sep in source:
                source = source.rsplit(sep, 1)[1]
        return source

    @staticmethod
    def _slugify(header: str) -> str:
        """Slugify *header* using structural character classification.

        Replaces three former ``re.sub`` calls with a single-pass char scanner:
        1. Lower-case and strip.
        2. Keep unicode word chars (as classified by ``unicodedata.category``),
           spaces, and dashes; discard everything else.
        3. Collapse runs of whitespace/underscores to a single dash.
        4. Collapse runs of dashes; strip leading/trailing dashes.
        """
        text = header.strip().lower()
        # Pass 1: keep word-chars (letter/digit), spaces, and dashes.
        # Underscores (Pc category) are treated as whitespace → normalised to space.
        # A char is a "word char" if its Unicode category starts with L (letter)
        # or N (number).
        kept: List[str] = []
        for ch in text:
            cat = unicodedata.category(ch)
            if cat.startswith("L") or cat.startswith("N"):
                kept.append(ch)
            elif ch in (" ", "\t", "_"):
                kept.append(" ")  # normalise underscore/whitespace to space
            elif ch == "-":
                kept.append("-")
            # else: discard punctuation, symbols, connector chars, etc.
        # Pass 2: collapse spaces/consecutive spaces → single dash, then dashes.
        parts: List[str] = []
        i = 0
        s = "".join(kept)
        while i < len(s):
            ch = s[i]
            if ch in (" ", "-"):
                # consume the whole run
                j = i
                while j < len(s) and s[j] in (" ", "-"):
                    j += 1
                parts.append("-")
                i = j
            else:
                parts.append(ch)
                i += 1
        result = "".join(parts).strip("-")
        return result

    @staticmethod
    def _anonymous_section_name(base: str) -> str:
        return f"{base}#_unnamed" if base else "#_unnamed"

    def _iter_sections(
        self, text: str, base: str
    ) -> List[Tuple[str, str]]:
        """Yield (section_name, prose) pairs for every h1/h2/h3 header.

        Uses the structural ``_iter_atx_headers`` scanner instead of the former
        ``_HEADER_RE`` regex compile.
        """
        matches = list(_iter_atx_headers(text))
        if not matches:
            return []

        result: List[Tuple[str, str]] = []
        for i, (match_start, match_end, _level, header) in enumerate(matches):
            slug = self._slugify(header.strip())
            if not slug:
                continue
            section_name = f"{base}#{slug}" if base else f"#{slug}"
            body_start = match_end
            body_end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
            body = text[body_start:body_end].strip()
            result.append((section_name, body))
        return result

    @staticmethod
    def _upsert_section_entity(
        section_name: str,
        source: str,
        entities: List[Entity],
        section_seen: Set[str],
    ) -> None:
        if section_name in section_seen:
            return
        section_seen.add(section_name)
        entities.append(Entity(
            name=section_name,
            type="Section",
            sources=[source] if source else [],
            extractor_source=[LLM_DOC_SOURCE],
            layer=LLM_DOC_SOURCE,
        ))

    # -- LLM invocation ------------------------------------------------------

    def _build_prompt(self, section_name: str, prose: str) -> str:
        if self._known_names:
            known_block = "\n".join(f"- {n}" for n in self._known_names)
        else:
            known_block = "(none)"
        return (
            CLAIM_EXTRACTION_PROMPT
            .replace("{known_entities}", known_block)
            .replace("{section_name}", section_name or "(unnamed)")
            .replace("{prose}", prose)
        )

    def _call_llm(self, section_name: str, prose: str) -> str:
        prompt = self._build_prompt(section_name, prose)
        try:
            return self._llm.generate(prompt)
        except Exception as exc:  # pragma: no cover - defensive
            _logger.warning("LLM provider raised on section %s: %s",
                            section_name, exc)
            return ""

    def _safe_parse(self, raw: str, source: str) -> Optional[Dict[str, Any]]:
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
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            _logger.warning(
                "spec-claim LLM response was not valid JSON for %s: %s",
                source or "<unknown>", exc,
            )
            return None
        if not isinstance(parsed, dict):
            _logger.warning(
                "spec-claim LLM response was not a JSON object for %s",
                source or "<unknown>",
            )
            return None
        return parsed

    # -- Entity / Triple build ---------------------------------------------

    def _build_claim_objects(
        self,
        parsed: Dict[str, Any],
        section_name: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
        seen_entities: Set[str],
    ) -> None:
        raw_claims = parsed.get("claims")
        if not isinstance(raw_claims, list):
            return

        local_id_to_canonical: Dict[str, str] = {}

        # First pass: build claim entities and section / target edges.
        prepared: List[Tuple[str, Dict[str, Any]]] = []
        for raw in raw_claims:
            if not isinstance(raw, dict):
                continue
            claim_type = str(raw.get("type", "")).strip()
            if claim_type not in VALID_CLAIM_TYPES:
                _logger.debug(
                    "Skipping claim with unknown type %r in %s",
                    claim_type, source or "<unknown>",
                )
                continue

            evidence = str(raw.get("evidence_span", "")).strip()
            target_raw = str(raw.get("target", "")).strip()
            target_canonical = self._fuse_target(target_raw)
            verification = str(raw.get("verification_strength", "unverified")).strip()
            if verification not in VALID_VERIFICATION_STRENGTHS:
                verification = "unverified"

            canonical_name = self._canonical_claim_name(
                section_name, claim_type, evidence, target_canonical
            )

            local_id = str(raw.get("id", "") or "").strip()
            if local_id:
                local_id_to_canonical[local_id] = canonical_name

            if canonical_name not in seen_entities:
                seen_entities.add(canonical_name)
                aliases: List[str] = []
                fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
                # Stash the structured fields onto aliases as "key=value" so the
                # entity remains a pure dataclass while still carrying the
                # extra metadata for downstream queries.
                for k, v in (fields or {}).items():
                    aliases.append(f"{k}={v}")
                aliases.append(f"verification_strength={verification}")
                if evidence:
                    aliases.append(f"evidence_span={evidence}")
                entities.append(Entity(
                    name=canonical_name,
                    type=claim_type,
                    sources=[source] if source else [],
                    extractor_source=[LLM_DOC_SOURCE],
                    aliases=aliases,
                    layer=LLM_DOC_SOURCE,
                ))

            triples.append(Triple(
                subject=section_name,
                predicate="claims_about",
                object=canonical_name,
                source=source,
                extractor_source=LLM_DOC_SOURCE,
                evidence_span=evidence,
                layer=LLM_DOC_SOURCE,
            ))

            if target_canonical:
                triples.append(Triple(
                    subject=canonical_name,
                    predicate="target_entity",
                    object=target_canonical,
                    source=source,
                    extractor_source=LLM_DOC_SOURCE,
                    evidence_span=evidence,
                    layer=LLM_DOC_SOURCE,
                ))

            prepared.append((canonical_name, raw))

        # Second pass: parent → child decomposes_into edges.
        for canonical_name, raw in prepared:
            parent_id = str(raw.get("parent_id") or "").strip()
            if not parent_id:
                continue
            parent_canonical = local_id_to_canonical.get(parent_id)
            if not parent_canonical or parent_canonical == canonical_name:
                continue
            triples.append(Triple(
                subject=parent_canonical,
                predicate="decomposes_into",
                object=canonical_name,
                source=source,
                extractor_source=LLM_DOC_SOURCE,
                evidence_span=str(raw.get("evidence_span", "")),
                layer=LLM_DOC_SOURCE,
            ))

    def _fuse_target(self, target: str) -> str:
        if not target:
            return ""
        return self._known_lower.get(target.lower(), target)

    @staticmethod
    def _canonical_claim_name(
        section_name: str,
        claim_type: str,
        evidence: str,
        target: str,
    ) -> str:
        """Build a stable, namespaced claim name from section + type + evidence.

        Replaces the former ``re.sub(r"[^a-z0-9]+", "-", ...)`` call with a
        structural single-pass char filter: keep ASCII a-z and 0-9, replace all
        other chars with ``-``, then collapse consecutive dashes and strip ends.
        """
        digest_seed = evidence or target or claim_type
        lowered = digest_seed.lower()
        # Single-pass: keep a-z / 0-9, replace everything else with '-'
        chars: List[str] = []
        for ch in lowered:
            if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
                chars.append(ch)
            else:
                chars.append("-")
        # Collapse consecutive dashes
        slug_parts: List[str] = []
        prev_dash = False
        for ch in chars:
            if ch == "-":
                if not prev_dash:
                    slug_parts.append("-")
                prev_dash = True
            else:
                slug_parts.append(ch)
                prev_dash = False
        slug = "".join(slug_parts).strip("-")
        if len(slug) > 60:
            slug = slug[:60].rstrip("-")
        if not slug:
            slug = "claim"
        return f"{section_name}::{claim_type}::{slug}"

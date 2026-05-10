# @summary
# OpenTitan-style HJSON CSR (control/status register) extractor.
# Parses an .hjson register description and emits CSR_Register / CSR_Field
# entities, plus has_register / has_field edges. Module-level emission
# (RTL_Module entity for the canonical block name) leverages the backend's
# case-insensitive dedup so existing parser-derived RTL_Module entities of
# the same name (any casing) absorb the hjson source path on upsert.
# Exports: HJSONCSRExtractor, HJSON_CSR_SOURCE
# Deps: hjson, src.knowledge_graph.common
# @end-summary
"""OpenTitan-style HJSON CSR extractor.

Walks the ``registers[]`` list in an OpenTitan-style HJSON description and
emits, per real register:

* a ``CSR_Register`` entity named ``"{MODULE_UPPER}.{REG_NAME}"``
* one ``CSR_Field`` entity per field, named ``"{MODULE_UPPER}.{REG_NAME}.{FIELD}"``
* a ``has_field`` triple from each register to its fields, with the
  ``bits=...`` (and optional ``swaccess=...``) string in ``evidence_span``
* a ``has_register`` triple from the module to each register, with the
  register's ``swaccess`` / offset / address pulled into ``evidence_span``
  when available

Control entries inside ``registers[]`` (``skipto``, ``reserved``, ``window``)
are skipped silently. ``multireg`` blocks are extracted as a single inner
register definition under the multireg's ``name`` — improving multireg
unrolling can be a follow-up ticket.

The module-level emission uses ``type="RTL_Module"`` with the canonical
hjson ``name`` field uppercased; the backend's case-insensitive dedup
will fuse this with any pre-existing RTL_Module of the same name (any
case) so the existing entity's ``sources`` grows with the hjson path.

All emitted entities and triples carry ``extractor_source="hjson_csr"``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import hjson

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = ["HJSONCSRExtractor", "HJSON_CSR_SOURCE"]

HJSON_CSR_SOURCE = "hjson_csr"

_logger = logging.getLogger("rag.knowledge_graph.hjson_csr")

# Keys in registers[] that indicate control entries (not real registers) we
# skip silently. ``multireg`` is unwrapped (see _normalize_register_entry).
_CONTROL_KEYS = frozenset({"skipto", "reserved", "window", "sameaddr"})


class HJSONCSRExtractor:
    """Extractor for OpenTitan-style HJSON register descriptions."""

    @property
    def name(self) -> str:
        """Extractor identifier reported on emitted entities/triples."""
        return HJSON_CSR_SOURCE

    def __init__(
        self,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
    ) -> None:
        # Constructor accepts (schema, config) for symmetry with other
        # extractors; neither is required by this extractor.
        self._schema = schema
        self._config = config

    # -- Public API ----------------------------------------------------------

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Parse *text* as HJSON and emit CSR entities + edges."""
        try:
            doc = hjson.loads(text)
        except Exception as exc:  # pragma: no cover - defensive
            _logger.warning("HJSON parse failed for %s: %s", source, exc)
            return ExtractionResult()

        if not isinstance(doc, dict):
            return ExtractionResult()

        module_raw = str(doc.get("name", "")).strip()
        if not module_raw:
            return ExtractionResult()

        module_upper = module_raw.upper()
        registers_list = doc.get("registers", [])
        if not isinstance(registers_list, list):
            return ExtractionResult()

        entities: List[Entity] = []
        triples: List[Triple] = []

        # Module fusion entity — type RTL_Module so the backend's case-
        # insensitive dedup merges with any existing module of the same name.
        entities.append(
            Entity(
                name=module_upper,
                type="RTL_Module",
                sources=[source] if source else [],
                extractor_source=[HJSON_CSR_SOURCE],
            )
        )

        for raw_entry in registers_list:
            normalized = self._normalize_register_entry(raw_entry)
            if normalized is None:
                continue

            reg_name = normalized.get("name")
            if not reg_name or not isinstance(reg_name, str):
                continue

            reg_canonical = f"{module_upper}.{reg_name}"
            entities.append(
                Entity(
                    name=reg_canonical,
                    type="CSR_Register",
                    sources=[source] if source else [],
                    extractor_source=[HJSON_CSR_SOURCE],
                )
            )

            # has_register edge from module → register
            reg_evidence = self._register_evidence(normalized)
            triples.append(
                Triple(
                    subject=module_upper,
                    predicate="has_register",
                    object=reg_canonical,
                    source=source,
                    extractor_source=HJSON_CSR_SOURCE,
                    evidence_span=reg_evidence,
                )
            )

            # Fields
            fields = normalized.get("fields", [])
            if not isinstance(fields, list):
                continue
            for fld in fields:
                if not isinstance(fld, dict):
                    continue
                fld_name = fld.get("name")
                if not fld_name or not isinstance(fld_name, str):
                    continue
                fld_canonical = f"{reg_canonical}.{fld_name}"
                entities.append(
                    Entity(
                        name=fld_canonical,
                        type="CSR_Field",
                        sources=[source] if source else [],
                        extractor_source=[HJSON_CSR_SOURCE],
                    )
                )
                triples.append(
                    Triple(
                        subject=reg_canonical,
                        predicate="has_field",
                        object=fld_canonical,
                        source=source,
                        extractor_source=HJSON_CSR_SOURCE,
                        evidence_span=self._field_evidence(fld),
                    )
                )

        return ExtractionResult(entities=entities, triples=triples)

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _normalize_register_entry(entry: Any) -> Optional[Dict[str, Any]]:
        """Return a real register dict, or ``None`` for control entries.

        ``multireg`` blocks are unwrapped to their inner register-like dict;
        this loses the per-instance unrolling but captures the canonical
        register/fields once. Improving multireg handling (full unrolling)
        is a follow-up.
        """
        if not isinstance(entry, dict):
            return None
        # Single-key control entries (skipto / reserved / window / sameaddr)
        if len(entry) == 1:
            only_key = next(iter(entry))
            if only_key in _CONTROL_KEYS:
                return None
            if only_key == "multireg":
                inner = entry["multireg"]
                if isinstance(inner, dict):
                    return inner
                return None
        # Some descriptions may put multireg alongside other keys; handle the
        # nested form too.
        if "multireg" in entry and isinstance(entry["multireg"], dict):
            return entry["multireg"]
        # If any control key is present without a name, treat as control.
        if "name" not in entry:
            if any(k in entry for k in _CONTROL_KEYS):
                return None
            return None
        return entry

    @staticmethod
    def _register_evidence(reg: Dict[str, Any]) -> str:
        """Build an evidence_span string for a has_register triple.

        Pulls swaccess and address/offset (whichever key is present) into
        a compact ``key=value`` string. Either field may be absent.
        """
        parts: List[Tuple[str, str]] = []
        sw = reg.get("swaccess")
        if isinstance(sw, str) and sw:
            parts.append(("swaccess", sw))
        # OpenTitan typically uses neither in the register dict (offsets are
        # implicit via skipto), but accept both ``offset`` and ``address``.
        for key in ("offset", "address"):
            val = reg.get(key)
            if isinstance(val, str) and val:
                parts.append((key, val))
                break
        return " ".join(f"{k}={v}" for k, v in parts)

    @staticmethod
    def _field_evidence(fld: Dict[str, Any]) -> str:
        """Build an evidence_span string for a has_field triple."""
        parts: List[Tuple[str, str]] = []
        bits = fld.get("bits")
        if isinstance(bits, str) and bits:
            parts.append(("bits", bits))
        elif bits is not None:
            parts.append(("bits", str(bits)))
        sw = fld.get("swaccess")
        if isinstance(sw, str) and sw:
            parts.append(("swaccess", sw))
        return " ".join(f"{k}={v}" for k, v in parts)

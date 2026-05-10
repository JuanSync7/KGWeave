# @summary
# IP-XACT 1685-2014 (and 1685-2009 spirit-namespace) component extractor.
# Walks <component> XML and emits IPXACT_Component / IPXACT_Port /
# IPXACT_Clock / IPXACT_Reset / IPXACT_Register / IPXACT_Field /
# IPXACT_BusInterface / IPXACT_AddressBlock / IPXACT_FieldEnum /
# IPXACT_Parameter / IPXACT_FileSet entities, plus has_ipxact_* / has_*
# composition edges and `specifies` / `parameterizes` / `implemented_by`
# cross-source edges to canonical entities resolved via
# known_entity_names (case-insensitive, with module-suffix index).
# Exports: IPXACTExtractor, IPXACT_SOURCE
# Deps: xml.etree.ElementTree, kgweave.knowledge_graph.common
# @end-summary
"""IP-XACT 1685-2014 component extractor.

Parses IEEE 1685-2014 (``ipxact``) and 1685-2009 (``spirit``) component
XML and emits typed nodes + edges into the unified KG, all tagged
``layer="ipxact"``. The extractor handles both namespaces transparently.

Phase 1 scope:

* ``<component>`` → ``IPXACT_Component`` (``specifies`` → RTL_Module)
* ``<port>`` → ``IPXACT_Port`` with direction + vector width attributes
  (``specifies`` → Port via case-insensitive fusion)
* Clock-bearing ports (``isClock`` qualifier or vendor extension) →
  ``IPXACT_Clock`` (``specifies`` → ClockDomain)
* Reset-bearing ports (``isReset``) → ``IPXACT_Reset``
  (``specifies`` → ResetDomain)
* ``<register>`` inside ``memoryMap`` / ``addressBlock`` →
  ``IPXACT_Register`` (``specifies`` → CSR_Register)
* ``<field>`` → ``IPXACT_Field`` (``specifies`` → CSR_Field)
* ``<busInterface>`` → ``IPXACT_BusInterface`` (no canonical analog yet —
  ``specifies`` edge is intentionally omitted in Phase 1)

Phase 2 additions:

* ``<addressBlock>`` → ``IPXACT_AddressBlock`` with ``base_address`` /
  ``range`` / ``width`` (composition: ``has_address_block`` from
  IPXACT_Component, ``contains_register`` to IPXACT_Register).
* ``<register><reset>`` (1685-2014) and flat ``<resetValue>`` /
  ``<resetMask>`` (1685-2009 spirit) surfaced as register attrs.
* ``<enumeratedValue>`` → ``IPXACT_FieldEnum`` (composition:
  ``has_ipxact_enum`` from IPXACT_Field; fused via ``specifies`` to
  CSR_FieldEnum where reggen produces a same-named canonical).
* ``<parameter>`` / ``<moduleParameter>`` → ``IPXACT_Parameter``
  (cross-source ``parameterizes`` to fused RTL_Module).
* ``<fileSet>`` → ``IPXACT_FileSet`` plus ``implemented_by`` edges from
  IPXACT_Component to SV_File entities matched by basename.

Deferred: ``<modifiedWriteValue>`` / ``<readAction>`` semantics,
``<componentInstantiation>`` / ``<view>`` cross-references,
``<addressSpace>`` / ``<cpu>``, ``<powerDomain>``, vendor extensions,
configurable / choice parameters, abstraction-definition references,
connection-element semantics. Multi-component XML files (IP-XACT
design / catalog) are out of scope.

Naming convention:

* ``IPXACT_Component``: ``"{component_name}"``
* ``IPXACT_Port``:      ``"{component_name}.ipxact_port.{port_name}"``
* ``IPXACT_Clock``:     ``"{component_name}.ipxact_clock.{port_name}"``
* ``IPXACT_Reset``:     ``"{component_name}.ipxact_reset.{port_name}"``
* ``IPXACT_Register``:  ``"{component_name}.ipxact_register.{reg_name}"``
* ``IPXACT_Field``:     ``"{component_name}.ipxact_register.{reg_name}.{field_name}"``
* ``IPXACT_BusInterface``: ``"{component_name}.ipxact_busif.{name}"``
* ``IPXACT_AddressBlock``: ``"{component_name}.ipxact_addrblock.{name}"``
* ``IPXACT_FieldEnum``:    ``"{component_name}.ipxact_register.{reg}.{field}.{enum}"``
* ``IPXACT_Parameter``:    ``"{component_name}.ipxact_param.{name}"``
* ``IPXACT_FileSet``:      ``"{component_name}.ipxact_fileset.{name}"``
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Tuple

from kgweave.knowledge_graph.common import (
    Entity,
    EntityDescription,
    ExtractionResult,
    Triple,
)

__all__ = ["IPXACTExtractor", "IPXACT_SOURCE"]

IPXACT_SOURCE = "ipxact"

_logger = logging.getLogger("rag.knowledge_graph.ipxact")

_NAMESPACES = {
    "ipxact": "http://www.accellera.org/XMLSchema/IPXACT/1685-2014",
    "spirit": "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009",
}


def _detect_ns(root: ET.Element) -> str:
    """Return the IP-XACT namespace URI in use, or ``""`` if none."""
    tag = root.tag
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def _local(tag: str) -> str:
    """Strip the ``{ns}`` prefix from an ElementTree tag."""
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _qn(ns: str, name: str) -> str:
    """Build a Clark-notation qualified name for a given local name."""
    return f"{{{ns}}}{name}" if ns else name


def _findtext(elem: ET.Element, ns: str, path: str) -> str:
    """Return stripped text of the first matching descendant, or ``""``."""
    target = _qn(ns, path) if ns else path
    found = elem.find(target)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _children_local(elem: ET.Element, name: str) -> List[ET.Element]:
    """Return direct children whose local name matches ``name``."""
    return [c for c in list(elem) if _local(c.tag) == name]


def _descendants_local(elem: ET.Element, name: str) -> List[ET.Element]:
    """Return all descendants whose local name matches ``name``."""
    return [c for c in elem.iter() if _local(c.tag) == name]


class IPXACTExtractor:
    """Parse an IP-XACT 1685-2014 / 1685-2009 component XML document.

    Parameters
    ----------
    known_entity_names:
        Optional iterable of canonical entity names. When provided, IP-XACT
        port / register / field / module names are fused to the closest
        case-insensitive match (or to a name ending in ``.<bare>``) so the
        emitted ``specifies`` edges land on existing canonical entities.
    schema, config:
        Accepted for symmetry with the other extractors; not required.
    """

    @property
    def name(self) -> str:
        return IPXACT_SOURCE

    def __init__(
        self,
        known_entity_names: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
    ) -> None:
        self._schema = schema
        self._config = config
        names = list(known_entity_names) if known_entity_names else []
        self._known_lower: Dict[str, str] = {}
        self._suffix_lower: Dict[str, str] = {}
        for n in names:
            if not n:
                continue
            self._known_lower[n.lower()] = n
            if "." in n:
                _, _, tail = n.rpartition(".")
                if tail:
                    self._suffix_lower[tail.lower()] = n

    # -- Public API ---------------------------------------------------------

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Parse IP-XACT XML and return entities + triples."""
        entities: List[Entity] = []
        triples: List[Triple] = []
        if not text or not text.strip():
            return ExtractionResult(entities=entities, triples=triples)
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            _logger.warning("IP-XACT parse failed for %s: %s", source, exc)
            return ExtractionResult(entities=entities, triples=triples)

        ns = _detect_ns(root)
        if _local(root.tag) != "component":
            _logger.debug("IP-XACT root is %r; expected 'component'", root.tag)
            return ExtractionResult(entities=entities, triples=triples)

        component_name = _findtext(root, ns, "name")
        if not component_name:
            _logger.warning("IP-XACT component has no <name>: %s", source)
            return ExtractionResult(entities=entities, triples=triples)

        comp_ent_name = component_name
        vendor = _findtext(root, ns, "vendor")
        library = _findtext(root, ns, "library")
        version = _findtext(root, ns, "version")
        attr_summary = "; ".join(
            x for x in (
                f"vendor={vendor}" if vendor else "",
                f"library={library}" if library else "",
                f"version={version}" if version else "",
            ) if x
        )
        entities.append(self._make_entity(
            name=comp_ent_name,
            etype="IPXACT_Component",
            source=source,
            text=attr_summary or component_name,
        ))
        # Fuse component to RTL_Module if a same-named module exists.
        triples.append(self._make_triple(
            subject=comp_ent_name,
            predicate="specifies",
            obj=self._fuse(component_name),
            source=source,
            evidence_span=attr_summary,
        ))

        # Ports (and clock / reset specializations).
        self._extract_ports(root, ns, component_name, source, entities, triples)
        # Bus interfaces.
        self._extract_bus_interfaces(
            root, ns, component_name, source, entities, triples,
        )
        # Memory map registers + fields (also emits address blocks + enums).
        self._extract_memory_maps(
            root, ns, component_name, source, entities, triples,
        )
        # Component-scope parameters and module parameters.
        self._extract_parameters(
            root, ns, component_name, source, entities, triples,
        )
        # File sets (RTL realization fusion).
        self._extract_file_sets(
            root, ns, component_name, source, entities, triples,
        )

        return ExtractionResult(entities=entities, triples=triples)

    # -- Section extractors -------------------------------------------------

    def _extract_ports(
        self,
        root: ET.Element,
        ns: str,
        component_name: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> None:
        # <component>/<model>/<ports>/<port>. We pull all <ports> wrappers
        # (one or two for typical components) and iterate their direct
        # <port> children — avoids accidentally matching <port> elements
        # nested inside abstractionDefinition references.
        port_elems: List[ET.Element] = []
        for ports_wrapper in _descendants_local(root, "ports"):
            port_elems.extend(_children_local(ports_wrapper, "port"))
        for port_elem in port_elems:
            port_name = _findtext(port_elem, ns, "name")
            if not port_name:
                continue
            wire = _first_child_local(port_elem, "wire")
            direction = ""
            vector_width = ""
            is_clock = False
            is_reset = False
            if wire is not None:
                direction = _findtext(wire, ns, "direction")
                vector = _first_child_local(wire, "vector")
                if vector is not None:
                    left = _findtext(vector, ns, "left")
                    right = _findtext(vector, ns, "right")
                    if left or right:
                        vector_width = f"[{left}:{right}]"
                # Qualifiers — prefer the 1685-2014 <qualifier> child.
                qualifier = _first_child_local(wire, "qualifier")
                if qualifier is not None:
                    if _findtext(qualifier, ns, "isClock").lower() == "true":
                        is_clock = True
                    if _findtext(qualifier, ns, "isReset").lower() == "true":
                        is_reset = True
                # Spirit-side flat qualifiers (rare).
                if not is_clock and _findtext(wire, ns, "isClock").lower() == "true":
                    is_clock = True
                if not is_reset and _findtext(wire, ns, "isReset").lower() == "true":
                    is_reset = True

            attrs: List[str] = []
            if direction:
                attrs.append(f"direction={direction}")
            if vector_width:
                attrs.append(f"width={vector_width}")
            if is_clock:
                attrs.append("isClock=true")
            if is_reset:
                attrs.append("isReset=true")
            attr_text = "; ".join(attrs)

            port_ent_name = f"{component_name}.ipxact_port.{port_name}"
            entities.append(self._make_entity(
                name=port_ent_name,
                etype="IPXACT_Port",
                source=source,
                text=attr_text or port_name,
            ))
            # has_ipxact_port composition.
            triples.append(self._make_triple(
                subject=component_name,
                predicate="has_ipxact_port",
                obj=port_ent_name,
                source=source,
            ))
            # Fuse to a canonical Port if known.
            fused = self._fuse(port_name)
            if fused != port_name:
                triples.append(self._make_triple(
                    subject=port_ent_name,
                    predicate="specifies",
                    obj=fused,
                    source=source,
                    evidence_span=attr_text,
                ))

            # Specialized clock / reset wrappers, anchored to the same port.
            if is_clock:
                clk_ent = f"{component_name}.ipxact_clock.{port_name}"
                entities.append(self._make_entity(
                    name=clk_ent,
                    etype="IPXACT_Clock",
                    source=source,
                    text=attr_text or port_name,
                ))
                if fused != port_name:
                    triples.append(self._make_triple(
                        subject=clk_ent,
                        predicate="specifies",
                        obj=fused,
                        source=source,
                    ))
            if is_reset:
                rst_ent = f"{component_name}.ipxact_reset.{port_name}"
                entities.append(self._make_entity(
                    name=rst_ent,
                    etype="IPXACT_Reset",
                    source=source,
                    text=attr_text or port_name,
                ))
                if fused != port_name:
                    triples.append(self._make_triple(
                        subject=rst_ent,
                        predicate="specifies",
                        obj=fused,
                        source=source,
                    ))

    def _extract_bus_interfaces(
        self,
        root: ET.Element,
        ns: str,
        component_name: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> None:
        # Track unique busTypes across the whole component so a single
        # IPXACT_BusType node is emitted per (vendor, library, name, version).
        seen_bustypes: set = set()
        # Track address spaces declared at component scope; busInterface
        # <addressSpaceRef> may point at one of them. (We emit IPXACT_AddressSpace
        # for every declared <addressSpace> regardless of master refs so the
        # node is present even if no busInterface references it.)
        for asp in _descendants_local(root, "addressSpace"):
            asp_name = _findtext(asp, ns, "name")
            if not asp_name:
                continue
            asp_range = _findtext(asp, ns, "range")
            asp_width = _findtext(asp, ns, "width")
            asp_attrs: List[str] = []
            if asp_range:
                asp_attrs.append(f"range={asp_range}")
            if asp_width:
                asp_attrs.append(f"width={asp_width}")
            asp_ent = f"{component_name}.ipxact_addrspace.{asp_name}"
            entities.append(self._make_entity(
                name=asp_ent,
                etype="IPXACT_AddressSpace",
                source=source,
                text="; ".join(asp_attrs) or asp_name,
                aliases=asp_attrs,
            ))

        for busif in _descendants_local(root, "busInterface"):
            bif_name = _findtext(busif, ns, "name")
            if not bif_name:
                continue
            kind = ""
            kind_elem: Optional[ET.Element] = None
            for tag in ("master", "slave", "initiator", "target",
                        "system", "monitor", "mirroredMaster",
                        "mirroredSlave", "mirroredSystem"):
                child = _first_child_local(busif, tag)
                if child is not None:
                    kind = tag
                    kind_elem = child
                    break
            attrs = [f"kind={kind}"] if kind else []
            ent_name = f"{component_name}.ipxact_busif.{bif_name}"
            entities.append(self._make_entity(
                name=ent_name,
                etype="IPXACT_BusInterface",
                source=source,
                text="; ".join(attrs) or bif_name,
            ))
            triples.append(self._make_triple(
                subject=component_name,
                predicate="has_bus_interface",
                obj=ent_name,
                source=source,
            ))

            # Feature 1: <busType> -> IPXACT_BusType + conforms_to.
            bustype = _first_child_local(busif, "busType")
            if bustype is not None:
                bt_vendor = bustype.attrib.get("vendor", "")
                bt_library = bustype.attrib.get("library", "")
                bt_name = bustype.attrib.get("name", "")
                bt_version = bustype.attrib.get("version", "")
                if bt_name:
                    bt_ent = (
                        f"{bt_vendor}::{bt_library}::{bt_name}::{bt_version}"
                    )
                    if bt_ent not in seen_bustypes:
                        seen_bustypes.add(bt_ent)
                        bt_attrs = [
                            f"vendor={bt_vendor}",
                            f"library={bt_library}",
                            f"name={bt_name}",
                            f"version={bt_version}",
                        ]
                        entities.append(self._make_entity(
                            name=bt_ent,
                            etype="IPXACT_BusType",
                            source=source,
                            text="; ".join(bt_attrs),
                            aliases=bt_attrs,
                        ))
                    triples.append(self._make_triple(
                        subject=ent_name,
                        predicate="conforms_to",
                        obj=bt_ent,
                        source=source,
                    ))

            # Feature 2: <portMaps>/<portMap> -> IPXACT_LogicalPort
            #            + has_logical_port + aggregates_port + physical_for.
            for portmap in _descendants_local(busif, "portMap"):
                logical = _first_child_local(portmap, "logicalPort")
                physical = _first_child_local(portmap, "physicalPort")
                if logical is None or physical is None:
                    continue
                logical_name = _findtext(logical, ns, "name")
                physical_name = _findtext(physical, ns, "name")
                if not logical_name or not physical_name:
                    continue
                # Logical-side direction (from <wire><direction>) when present.
                lp_dir = ""
                lp_wire = _first_child_local(logical, "wire")
                if lp_wire is not None:
                    lp_dir = _findtext(lp_wire, ns, "direction")
                lp_attrs: List[str] = []
                if lp_dir:
                    lp_attrs.append(f"direction={lp_dir}")
                lp_ent = f"{ent_name}.logical.{logical_name}"
                entities.append(self._make_entity(
                    name=lp_ent,
                    etype="IPXACT_LogicalPort",
                    source=source,
                    text="; ".join(lp_attrs) or logical_name,
                    aliases=lp_attrs,
                ))
                triples.append(self._make_triple(
                    subject=ent_name,
                    predicate="has_logical_port",
                    obj=lp_ent,
                    source=source,
                ))
                # aggregates_port (busif -> physical Port). Fuse to canonical
                # if known; else fall back to bare physical name (the audit
                # signal: orphan flat ports surface as missing fusion).
                fused_phys = self._fuse(physical_name)
                triples.append(self._make_triple(
                    subject=ent_name,
                    predicate="aggregates_port",
                    obj=fused_phys,
                    source=source,
                    evidence_span=f"logical={logical_name}",
                ))
                triples.append(self._make_triple(
                    subject=lp_ent,
                    predicate="physical_for",
                    obj=fused_phys,
                    source=source,
                ))

            # Feature 3: <slave><memoryMapRef> + <master><addressSpaceRef>.
            if kind_elem is not None:
                mm_ref = _first_child_local(kind_elem, "memoryMapRef")
                if mm_ref is not None:
                    mm_target = (
                        mm_ref.attrib.get("memoryMapRef")
                        or _findtext(mm_ref, ns, "name")
                        or (mm_ref.text.strip() if mm_ref.text else "")
                    )
                    if mm_target:
                        triples.append(self._make_triple(
                            subject=ent_name,
                            predicate="exposes_memory_map",
                            obj=f"{component_name}.ipxact_memmap.{mm_target}",
                            source=source,
                        ))
                as_ref = _first_child_local(kind_elem, "addressSpaceRef")
                if as_ref is not None:
                    as_target = (
                        as_ref.attrib.get("addressSpaceRef")
                        or _findtext(as_ref, ns, "name")
                        or (as_ref.text.strip() if as_ref.text else "")
                    )
                    if as_target:
                        triples.append(self._make_triple(
                            subject=ent_name,
                            predicate="connects_to_address_space",
                            obj=f"{component_name}.ipxact_addrspace.{as_target}",
                            source=source,
                        ))

    def _extract_memory_maps(
        self,
        root: ET.Element,
        ns: str,
        component_name: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> None:
        """Emit IPXACT_AddressBlock / IPXACT_Register / IPXACT_Field /
        IPXACT_FieldEnum and their composition + fusion edges.

        Walks ``<addressBlock>`` first so we can emit the
        ``has_address_block`` / ``contains_register`` composition wedge,
        then falls back to a flat ``<register>`` sweep for any registers
        that live outside an explicit address block (defensive).
        """
        seen_regs: set = set()

        # Emit IPXACT_MemoryMap parents and contains_address_block edges.
        # We keep has_address_block (Component -> AddressBlock) for backward
        # compat below — both edges fire so existing audit queries continue
        # to work while the new memmap-rooted traversal becomes available.
        ablock_to_memmap: Dict[str, str] = {}
        for memmap in _descendants_local(root, "memoryMap"):
            mm_name = _findtext(memmap, ns, "name")
            if not mm_name:
                continue
            mm_ent = f"{component_name}.ipxact_memmap.{mm_name}"
            entities.append(self._make_entity(
                name=mm_ent,
                etype="IPXACT_MemoryMap",
                source=source,
                text=mm_name,
            ))
            triples.append(self._make_triple(
                subject=component_name,
                predicate="has_memory_map",
                obj=mm_ent,
                source=source,
            ))
            for ablock in _descendants_local(memmap, "addressBlock"):
                ab_name = _findtext(ablock, ns, "name")
                if not ab_name:
                    continue
                ab_ent = f"{component_name}.ipxact_addrblock.{ab_name}"
                ablock_to_memmap[ab_ent] = mm_ent
                triples.append(self._make_triple(
                    subject=mm_ent,
                    predicate="contains_address_block",
                    obj=ab_ent,
                    source=source,
                ))

        for ablock in _descendants_local(root, "addressBlock"):
            ab_name = _findtext(ablock, ns, "name")
            if not ab_name:
                continue
            base = _findtext(ablock, ns, "baseAddress")
            ab_range = _findtext(ablock, ns, "range")
            width = _findtext(ablock, ns, "width")
            ab_attrs: List[str] = []
            if base:
                ab_attrs.append(f"base_address={base}")
            if ab_range:
                ab_attrs.append(f"range={ab_range}")
            if width:
                ab_attrs.append(f"width={width}")
            ab_attr_text = "; ".join(ab_attrs)
            ab_ent = f"{component_name}.ipxact_addrblock.{ab_name}"
            entities.append(self._make_entity(
                name=ab_ent,
                etype="IPXACT_AddressBlock",
                source=source,
                text=ab_attr_text or ab_name,
                aliases=ab_attrs,
            ))
            triples.append(self._make_triple(
                subject=component_name,
                predicate="has_address_block",
                obj=ab_ent,
                source=source,
            ))
            for reg in _descendants_local(ablock, "register"):
                reg_ent = self._emit_register(
                    reg, ns, component_name, source, entities, triples,
                )
                if reg_ent is None:
                    continue
                seen_regs.add(reg_ent)
                triples.append(self._make_triple(
                    subject=ab_ent,
                    predicate="contains_register",
                    obj=reg_ent,
                    source=source,
                ))

        # Defensive: also pick up any <register> not nested under an
        # <addressBlock> (rare; preserves prior behaviour).
        for reg in _descendants_local(root, "register"):
            reg_name = _findtext(reg, ns, "name")
            if not reg_name:
                continue
            reg_ent = f"{component_name}.ipxact_register.{reg_name}"
            if reg_ent in seen_regs:
                continue
            self._emit_register(reg, ns, component_name, source, entities, triples)

    def _emit_register(
        self,
        reg: ET.Element,
        ns: str,
        component_name: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> Optional[str]:
        """Emit a single IPXACT_Register (with reset + fields + enums)."""
        reg_name = _findtext(reg, ns, "name")
        if not reg_name:
            return None
        offset = _findtext(reg, ns, "addressOffset")
        size = _findtext(reg, ns, "size")
        attrs: List[str] = []
        if offset:
            attrs.append(f"address_offset={offset}")
        if size:
            attrs.append(f"size={size}")

        # Reset value/mask. 1685-2014 nests under <reset><value>/<mask>;
        # 1685-2009 spirit uses flat <resetValue>/<resetMask>.
        reset_value = ""
        reset_mask = ""
        reset_elem = _first_child_local(reg, "reset")
        if reset_elem is not None:
            reset_value = _findtext(reset_elem, ns, "value")
            reset_mask = _findtext(reset_elem, ns, "mask")
        if not reset_value:
            reset_value = _findtext(reg, ns, "resetValue")
        if not reset_mask:
            reset_mask = _findtext(reg, ns, "resetMask")
        if reset_value:
            attrs.append(f"reset_value={reset_value}")
        if reset_mask:
            attrs.append(f"reset_mask={reset_mask}")
        attr_text = "; ".join(attrs)

        reg_ent = f"{component_name}.ipxact_register.{reg_name}"
        entities.append(self._make_entity(
            name=reg_ent,
            etype="IPXACT_Register",
            source=source,
            text=attr_text or reg_name,
            aliases=attrs,
        ))
        triples.append(self._make_triple(
            subject=component_name,
            predicate="has_ipxact_register",
            obj=reg_ent,
            source=source,
        ))
        fused_reg = self._fuse(reg_name)
        if fused_reg != reg_name:
            triples.append(self._make_triple(
                subject=reg_ent,
                predicate="specifies",
                obj=fused_reg,
                source=source,
                evidence_span=attr_text,
            ))

        # Fields.
        for field in _children_local(reg, "field"):
            field_name = _findtext(field, ns, "name")
            if not field_name:
                continue
            bit_offset = _findtext(field, ns, "bitOffset")
            bit_width = _findtext(field, ns, "bitWidth")
            access = _findtext(field, ns, "access")
            f_attrs: List[str] = []
            if bit_offset:
                f_attrs.append(f"bit_offset={bit_offset}")
            if bit_width:
                f_attrs.append(f"bit_width={bit_width}")
            if access:
                f_attrs.append(f"access={access}")
            f_text = "; ".join(f_attrs)

            field_ent = f"{component_name}.ipxact_register.{reg_name}.{field_name}"
            entities.append(self._make_entity(
                name=field_ent,
                etype="IPXACT_Field",
                source=source,
                text=f_text or field_name,
                aliases=f_attrs,
            ))
            triples.append(self._make_triple(
                subject=reg_ent,
                predicate="has_ipxact_field",
                obj=field_ent,
                source=source,
            ))
            fused_field = self._fuse(field_name)
            if fused_field != field_name:
                triples.append(self._make_triple(
                    subject=field_ent,
                    predicate="specifies",
                    obj=fused_field,
                    source=source,
                    evidence_span=f_text,
                ))

            # Enumerated values.
            self._emit_field_enums(
                field, ns, component_name, reg_name, field_name,
                field_ent, source, entities, triples,
            )

        return reg_ent

    def _emit_field_enums(
        self,
        field: ET.Element,
        ns: str,
        component_name: str,
        reg_name: str,
        field_name: str,
        field_ent: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> None:
        """Emit IPXACT_FieldEnum entities + has_ipxact_enum + specifies edges."""
        # <field>/<enumeratedValues>/<enumeratedValue>
        wrappers = _children_local(field, "enumeratedValues")
        for wrapper in wrappers:
            for enum in _children_local(wrapper, "enumeratedValue"):
                enum_name = _findtext(enum, ns, "name")
                if not enum_name:
                    continue
                value = _findtext(enum, ns, "value")
                usage = _findtext(enum, ns, "usage") or "read-write"
                e_attrs: List[str] = []
                if value:
                    e_attrs.append(f"value={value}")
                e_attrs.append(f"usage={usage}")
                e_text = "; ".join(e_attrs)

                enum_ent = (
                    f"{component_name}.ipxact_register.{reg_name}."
                    f"{field_name}.{enum_name}"
                )
                entities.append(self._make_entity(
                    name=enum_ent,
                    etype="IPXACT_FieldEnum",
                    source=source,
                    text=e_text or enum_name,
                    aliases=e_attrs,
                ))
                triples.append(self._make_triple(
                    subject=field_ent,
                    predicate="has_ipxact_enum",
                    obj=enum_ent,
                    source=source,
                ))
                # Try to fuse to a canonical CSR_FieldEnum (HJSON reggen
                # often emits these as `{reg}.{field}.{enum}` or simply
                # `{enum}`). The shared suffix-index handles both.
                fused = self._fuse(
                    f"{reg_name}.{field_name}.{enum_name}"
                )
                if fused == f"{reg_name}.{field_name}.{enum_name}":
                    fused = self._fuse(enum_name)
                if fused != enum_name and fused != (
                    f"{reg_name}.{field_name}.{enum_name}"
                ):
                    triples.append(self._make_triple(
                        subject=enum_ent,
                        predicate="specifies",
                        obj=fused,
                        source=source,
                        evidence_span=e_text,
                    ))

    def _extract_parameters(
        self,
        root: ET.Element,
        ns: str,
        component_name: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> None:
        """Emit IPXACT_Parameter entities for component <parameter> /
        <moduleParameter> elements and a ``parameterizes`` edge to the
        fused canonical RTL_Module (same name as the component).
        """
        param_elems: List[ET.Element] = []
        # <parameters>/<parameter> (component-scope).
        for wrapper in _descendants_local(root, "parameters"):
            param_elems.extend(_children_local(wrapper, "parameter"))
        # <moduleParameters>/<moduleParameter> (model-scope).
        for wrapper in _descendants_local(root, "moduleParameters"):
            param_elems.extend(_children_local(wrapper, "moduleParameter"))

        fused_module = self._fuse(component_name)
        for pelem in param_elems:
            pname = _findtext(pelem, ns, "name")
            if not pname:
                continue
            value = _findtext(pelem, ns, "value")
            data_type = pelem.attrib.get("dataType", "") or pelem.attrib.get(
                "type", ""
            )
            attrs: List[str] = []
            if value:
                attrs.append(f"value={value}")
            if data_type:
                attrs.append(f"data_type={data_type}")
            attr_text = "; ".join(attrs)

            ent_name = f"{component_name}.ipxact_param.{pname}"
            entities.append(self._make_entity(
                name=ent_name,
                etype="IPXACT_Parameter",
                source=source,
                text=attr_text or pname,
                aliases=attrs,
            ))
            triples.append(self._make_triple(
                subject=component_name,
                predicate="has_ipxact_parameter",
                obj=ent_name,
                source=source,
            ))
            if fused_module != component_name:
                triples.append(self._make_triple(
                    subject=ent_name,
                    predicate="parameterizes",
                    obj=fused_module,
                    source=source,
                    evidence_span=attr_text,
                ))

    def _extract_file_sets(
        self,
        root: ET.Element,
        ns: str,
        component_name: str,
        source: str,
        entities: List[Entity],
        triples: List[Triple],
    ) -> None:
        """Emit IPXACT_FileSet entities and ``implemented_by`` edges from
        IPXACT_Component to SV_File entities matched by basename.
        """
        for fs_wrapper in _descendants_local(root, "fileSets"):
            for fs in _children_local(fs_wrapper, "fileSet"):
                fs_name = _findtext(fs, ns, "name")
                if not fs_name:
                    continue
                file_names: List[str] = []
                for f_elem in _children_local(fs, "file"):
                    fn = _findtext(f_elem, ns, "name")
                    if fn:
                        file_names.append(fn)
                attrs: List[str] = []
                if file_names:
                    attrs.append(f"files={','.join(file_names)}")
                attr_text = "; ".join(attrs)

                ent_name = f"{component_name}.ipxact_fileset.{fs_name}"
                entities.append(self._make_entity(
                    name=ent_name,
                    etype="IPXACT_FileSet",
                    source=source,
                    text=attr_text or fs_name,
                    aliases=attrs,
                ))
                triples.append(self._make_triple(
                    subject=component_name,
                    predicate="has_ipxact_fileset",
                    obj=ent_name,
                    source=source,
                ))
                # implemented_by edges: fuse each file basename to a
                # known SV_File entity (case-insensitive, with .sv
                # stripped).
                for fn in file_names:
                    base = fn.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                    stem = base[:-3] if base.lower().endswith(".sv") else base
                    fused = self._fuse(stem)
                    if fused == stem:
                        # Try with full basename (e.g. "aes.sv") in case
                        # SV_File entities are keyed with extension.
                        fused = self._fuse(base)
                    if fused != stem and fused != base:
                        triples.append(self._make_triple(
                            subject=component_name,
                            predicate="implemented_by",
                            obj=fused,
                            source=source,
                            evidence_span=fn,
                        ))

    # -- Builders -----------------------------------------------------------

    def _make_entity(
        self,
        *,
        name: str,
        etype: str,
        source: str,
        text: str,
        aliases: Optional[List[str]] = None,
    ) -> Entity:
        return Entity(
            name=name,
            type=etype,
            sources=[source] if source else [],
            extractor_source=[IPXACT_SOURCE],
            raw_mentions=[EntityDescription(
                text=text, source=source, chunk_id="",
            )],
            aliases=list(aliases) if aliases else [],
            layer=IPXACT_SOURCE,
        )

    def _make_triple(
        self,
        *,
        subject: str,
        predicate: str,
        obj: str,
        source: str,
        evidence_span: str = "",
    ) -> Triple:
        return Triple(
            subject=subject,
            predicate=predicate,
            object=obj,
            source=source,
            extractor_source=IPXACT_SOURCE,
            evidence_span=evidence_span,
            layer=IPXACT_SOURCE,
        )

    # -- Fusion -------------------------------------------------------------

    def _fuse(self, bare: str) -> str:
        """Return canonical entity name for ``bare``, or ``bare`` if no match."""
        if not bare:
            return bare
        key = bare.lower()
        if key in self._known_lower:
            return self._known_lower[key]
        if key in self._suffix_lower:
            return self._suffix_lower[key]
        return bare


def _first_child_local(elem: ET.Element, name: str) -> Optional[ET.Element]:
    """Return the first direct child whose local name matches ``name``."""
    for c in list(elem):
        if _local(c.tag) == name:
            return c
    return None



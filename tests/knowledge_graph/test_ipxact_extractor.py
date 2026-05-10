"""Tests for the IP-XACT 1685-2014 component extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity
from kgweave.knowledge_graph.extraction import IPXACT_SOURCE, IPXACTExtractor


_NS_2014 = 'xmlns:ipxact="http://www.accellera.org/XMLSchema/IPXACT/1685-2014"'
_NS_2009 = 'xmlns:spirit="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"'


def _minimal_2014(component_name: str = "demo") -> str:
    return f"""<?xml version="1.0"?>
<ipxact:component {_NS_2014}>
  <ipxact:vendor>v</ipxact:vendor>
  <ipxact:library>l</ipxact:library>
  <ipxact:name>{component_name}</ipxact:name>
  <ipxact:version>0.1</ipxact:version>
  <ipxact:model>
    <ipxact:ports>
      <ipxact:port>
        <ipxact:name>data_in</ipxact:name>
        <ipxact:wire>
          <ipxact:direction>in</ipxact:direction>
          <ipxact:vector>
            <ipxact:left>31</ipxact:left>
            <ipxact:right>0</ipxact:right>
          </ipxact:vector>
        </ipxact:wire>
      </ipxact:port>
    </ipxact:ports>
  </ipxact:model>
</ipxact:component>
"""


def _full_2014() -> str:
    return f"""<?xml version="1.0"?>
<ipxact:component {_NS_2014}>
  <ipxact:vendor>v</ipxact:vendor>
  <ipxact:library>l</ipxact:library>
  <ipxact:name>demo</ipxact:name>
  <ipxact:version>0.1</ipxact:version>
  <ipxact:busInterfaces>
    <ipxact:busInterface>
      <ipxact:name>tlul</ipxact:name>
      <ipxact:slave/>
    </ipxact:busInterface>
  </ipxact:busInterfaces>
  <ipxact:memoryMaps>
    <ipxact:memoryMap>
      <ipxact:name>regs</ipxact:name>
      <ipxact:addressBlock>
        <ipxact:name>blk</ipxact:name>
        <ipxact:baseAddress>0x0</ipxact:baseAddress>
        <ipxact:range>0x100</ipxact:range>
        <ipxact:width>32</ipxact:width>
        <ipxact:register>
          <ipxact:name>CTRL</ipxact:name>
          <ipxact:addressOffset>0x0</ipxact:addressOffset>
          <ipxact:size>32</ipxact:size>
          <ipxact:field>
            <ipxact:name>ENABLE</ipxact:name>
            <ipxact:bitOffset>0</ipxact:bitOffset>
            <ipxact:bitWidth>1</ipxact:bitWidth>
            <ipxact:access>read-write</ipxact:access>
          </ipxact:field>
        </ipxact:register>
      </ipxact:addressBlock>
    </ipxact:memoryMap>
  </ipxact:memoryMaps>
  <ipxact:model>
    <ipxact:ports>
      <ipxact:port>
        <ipxact:name>clk_i</ipxact:name>
        <ipxact:wire>
          <ipxact:direction>in</ipxact:direction>
          <ipxact:qualifier><ipxact:isClock>true</ipxact:isClock></ipxact:qualifier>
        </ipxact:wire>
      </ipxact:port>
      <ipxact:port>
        <ipxact:name>rst_ni</ipxact:name>
        <ipxact:wire>
          <ipxact:direction>in</ipxact:direction>
          <ipxact:qualifier><ipxact:isReset>true</ipxact:isReset></ipxact:qualifier>
        </ipxact:wire>
      </ipxact:port>
      <ipxact:port>
        <ipxact:name>data_in</ipxact:name>
        <ipxact:wire>
          <ipxact:direction>in</ipxact:direction>
          <ipxact:vector>
            <ipxact:left>31</ipxact:left>
            <ipxact:right>0</ipxact:right>
          </ipxact:vector>
        </ipxact:wire>
      </ipxact:port>
      <ipxact:port>
        <ipxact:name>nonexistent</ipxact:name>
        <ipxact:wire><ipxact:direction>out</ipxact:direction></ipxact:wire>
      </ipxact:port>
    </ipxact:ports>
  </ipxact:model>
</ipxact:component>
"""


def _minimal_2009() -> str:
    return f"""<?xml version="1.0"?>
<spirit:component {_NS_2009}>
  <spirit:vendor>v</spirit:vendor>
  <spirit:library>l</spirit:library>
  <spirit:name>demo</spirit:name>
  <spirit:version>0.1</spirit:version>
  <spirit:model>
    <spirit:ports>
      <spirit:port>
        <spirit:name>data_in</spirit:name>
        <spirit:wire>
          <spirit:direction>in</spirit:direction>
        </spirit:wire>
      </spirit:port>
    </spirit:ports>
  </spirit:model>
</spirit:component>
"""


def test_minimal_component_emitted():
    r = IPXACTExtractor().extract(_minimal_2014("foo"))
    comps = [e for e in r.entities if e.type == "IPXACT_Component"]
    assert len(comps) == 1
    assert comps[0].name == "foo"


def test_port_entity_with_direction():
    r = IPXACTExtractor().extract(_minimal_2014())
    ports = [e for e in r.entities if e.type == "IPXACT_Port"]
    assert len(ports) == 1
    assert ports[0].name == "demo.ipxact_port.data_in"
    text = ports[0].raw_mentions[0].text
    assert "direction=in" in text


def test_port_vector_width_extracted():
    r = IPXACTExtractor().extract(_minimal_2014())
    ports = [e for e in r.entities if e.type == "IPXACT_Port"]
    text = ports[0].raw_mentions[0].text
    assert "[31:0]" in text


def test_register_entity_emitted():
    r = IPXACTExtractor().extract(_full_2014())
    regs = [e for e in r.entities if e.type == "IPXACT_Register"]
    assert len(regs) == 1
    assert regs[0].name == "demo.ipxact_register.CTRL"
    assert "address_offset=0x0" in regs[0].raw_mentions[0].text


def test_field_entity_emitted():
    r = IPXACTExtractor().extract(_full_2014())
    fields = [e for e in r.entities if e.type == "IPXACT_Field"]
    assert len(fields) == 1
    assert fields[0].name == "demo.ipxact_register.CTRL.ENABLE"
    text = fields[0].raw_mentions[0].text
    assert "bit_offset=0" in text and "bit_width=1" in text


def test_bus_interface_emitted():
    r = IPXACTExtractor().extract(_full_2014())
    bifs = [e for e in r.entities if e.type == "IPXACT_BusInterface"]
    assert len(bifs) == 1
    assert bifs[0].name == "demo.ipxact_busif.tlul"
    assert "kind=slave" in bifs[0].raw_mentions[0].text
    has_bif = [t for t in r.triples if t.predicate == "has_bus_interface"]
    assert len(has_bif) == 1


def test_clock_and_reset_qualifiers():
    r = IPXACTExtractor().extract(_full_2014())
    clocks = [e for e in r.entities if e.type == "IPXACT_Clock"]
    resets = [e for e in r.entities if e.type == "IPXACT_Reset"]
    assert len(clocks) == 1 and clocks[0].name == "demo.ipxact_clock.clk_i"
    assert len(resets) == 1 and resets[0].name == "demo.ipxact_reset.rst_ni"


def test_specifies_edge_to_known_port():
    known = ["aes.data_in", "aes"]
    ex = IPXACTExtractor(known_entity_names=known)
    xml = _minimal_2014("aes")
    r = ex.extract(xml)
    spec = [t for t in r.triples
            if t.predicate == "specifies"
            and t.subject == "aes.ipxact_port.data_in"]
    assert len(spec) == 1
    assert spec[0].object == "aes.data_in"


def test_specifies_edge_to_known_register():
    known = ["AES.CTRL"]
    ex = IPXACTExtractor(known_entity_names=known)
    xml = _full_2014().replace("<ipxact:name>CTRL</ipxact:name>",
                               "<ipxact:name>CTRL</ipxact:name>")
    r = ex.extract(xml)
    spec = [t for t in r.triples
            if t.predicate == "specifies"
            and t.subject == "demo.ipxact_register.CTRL"]
    assert len(spec) == 1
    assert spec[0].object == "AES.CTRL"


def test_no_fusion_when_unknown():
    ex = IPXACTExtractor(known_entity_names=["other.port"])
    r = ex.extract(_full_2014())
    # 'nonexistent' port is in IPXACT_Port entities...
    ports = [e for e in r.entities if e.type == "IPXACT_Port"]
    names = {e.name for e in ports}
    assert "demo.ipxact_port.nonexistent" in names
    # ...but no specifies edge for it.
    specs_for_nx = [
        t for t in r.triples
        if t.predicate == "specifies"
        and t.subject == "demo.ipxact_port.nonexistent"
    ]
    assert specs_for_nx == []


def test_namespace_detection_2009_vs_2014():
    r2014 = IPXACTExtractor().extract(_minimal_2014())
    r2009 = IPXACTExtractor().extract(_minimal_2009())
    p2014 = [e for e in r2014.entities if e.type == "IPXACT_Port"]
    p2009 = [e for e in r2009.entities if e.type == "IPXACT_Port"]
    assert len(p2014) == 1 and len(p2009) == 1
    assert p2014[0].name == p2009[0].name == "demo.ipxact_port.data_in"


def test_round_trip_extract_to_backend():
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="aes.data_in", type="Port", layer="sv_parser"),
    ])
    known = list(backend.get_all_node_names_and_aliases().keys())
    r = IPXACTExtractor(known_entity_names=known).extract(_minimal_2014("aes"))
    backend.upsert_entities(r.entities)
    backend.upsert_triples(r.triples)
    out_edges = backend.get_outgoing_edges("aes.ipxact_port.data_in")
    spec_edges = [t for t in out_edges if t.predicate == "specifies"]
    assert len(spec_edges) == 1
    assert spec_edges[0].object == "aes.data_in"


def test_layer_tag_set():
    r = IPXACTExtractor().extract(_full_2014())
    assert r.entities, "expected entities"
    assert r.triples, "expected triples"
    for e in r.entities:
        assert e.layer == IPXACT_SOURCE, f"{e.name} missing ipxact layer"
        assert IPXACT_SOURCE in e.extractor_source
    for t in r.triples:
        assert t.layer == IPXACT_SOURCE, f"{t.subject}->{t.object} missing ipxact layer"
        assert t.extractor_source == IPXACT_SOURCE


def test_real_aes_synthetic_smoke():
    fixture = (Path(__file__).resolve().parents[2]
               / "data" / "demo" / "aes_synthetic.ipxact.xml")
    if not fixture.exists():
        pytest.skip(f"synthetic fixture not present: {fixture}")
    text = fixture.read_text()
    r = IPXACTExtractor().extract(text, source=str(fixture))
    comps = [e for e in r.entities if e.type == "IPXACT_Component"]
    ports = [e for e in r.entities if e.type == "IPXACT_Port"]
    regs = [e for e in r.entities if e.type == "IPXACT_Register"]
    assert len(comps) >= 1
    assert len(ports) >= 4
    assert len(regs) >= 2


def test_specifies_edge_to_known_field():
    known = ["AES.CTRL.ENABLE"]
    r = IPXACTExtractor(known_entity_names=known).extract(_full_2014())
    spec = [t for t in r.triples
            if t.predicate == "specifies"
            and t.subject == "demo.ipxact_register.CTRL.ENABLE"]
    assert len(spec) == 1
    assert spec[0].object == "AES.CTRL.ENABLE"


def test_empty_input_returns_empty():
    r = IPXACTExtractor().extract("")
    assert r.entities == [] and r.triples == []


def test_invalid_xml_returns_empty():
    r = IPXACTExtractor().extract("<not-xml")
    assert r.entities == [] and r.triples == []


# ---------------------------------------------------------------------------
# Phase-2 additions: address blocks, register reset, field enums,
# parameters, file sets.
# ---------------------------------------------------------------------------


def _phase2_2014() -> str:
    return f"""<?xml version="1.0"?>
<ipxact:component {_NS_2014}>
  <ipxact:vendor>v</ipxact:vendor>
  <ipxact:library>l</ipxact:library>
  <ipxact:name>aes</ipxact:name>
  <ipxact:version>0.1</ipxact:version>
  <ipxact:memoryMaps>
    <ipxact:memoryMap>
      <ipxact:name>regs</ipxact:name>
      <ipxact:addressBlock>
        <ipxact:name>blk</ipxact:name>
        <ipxact:baseAddress>0x0</ipxact:baseAddress>
        <ipxact:range>0x100</ipxact:range>
        <ipxact:width>32</ipxact:width>
        <ipxact:register>
          <ipxact:name>CTRL</ipxact:name>
          <ipxact:addressOffset>0x0</ipxact:addressOffset>
          <ipxact:size>32</ipxact:size>
          <ipxact:reset>
            <ipxact:value>0x1</ipxact:value>
            <ipxact:mask>0xFFFFFFFF</ipxact:mask>
          </ipxact:reset>
          <ipxact:field>
            <ipxact:name>OP</ipxact:name>
            <ipxact:bitOffset>0</ipxact:bitOffset>
            <ipxact:bitWidth>2</ipxact:bitWidth>
            <ipxact:access>read-write</ipxact:access>
            <ipxact:enumeratedValues>
              <ipxact:enumeratedValue>
                <ipxact:name>AES_ENC</ipxact:name>
                <ipxact:value>1</ipxact:value>
              </ipxact:enumeratedValue>
              <ipxact:enumeratedValue>
                <ipxact:name>AES_DEC</ipxact:name>
                <ipxact:value>2</ipxact:value>
              </ipxact:enumeratedValue>
            </ipxact:enumeratedValues>
          </ipxact:field>
        </ipxact:register>
      </ipxact:addressBlock>
    </ipxact:memoryMap>
  </ipxact:memoryMaps>
  <ipxact:parameters>
    <ipxact:parameter dataType="int">
      <ipxact:name>NumRegsKey</ipxact:name>
      <ipxact:value>8</ipxact:value>
    </ipxact:parameter>
    <ipxact:parameter dataType="bit">
      <ipxact:name>EN_MASKING</ipxact:name>
      <ipxact:value>1</ipxact:value>
    </ipxact:parameter>
  </ipxact:parameters>
  <ipxact:fileSets>
    <ipxact:fileSet>
      <ipxact:name>aes_rtl</ipxact:name>
      <ipxact:file>
        <ipxact:name>rtl/aes.sv</ipxact:name>
      </ipxact:file>
      <ipxact:file>
        <ipxact:name>rtl/aes_core.sv</ipxact:name>
      </ipxact:file>
    </ipxact:fileSet>
  </ipxact:fileSets>
</ipxact:component>
"""


def _phase2_2009_flat_reset() -> str:
    return f"""<?xml version="1.0"?>
<spirit:component {_NS_2009}>
  <spirit:vendor>v</spirit:vendor>
  <spirit:library>l</spirit:library>
  <spirit:name>demo</spirit:name>
  <spirit:version>0.1</spirit:version>
  <spirit:memoryMaps>
    <spirit:memoryMap>
      <spirit:name>regs</spirit:name>
      <spirit:addressBlock>
        <spirit:name>blk</spirit:name>
        <spirit:baseAddress>0x0</spirit:baseAddress>
        <spirit:range>0x10</spirit:range>
        <spirit:width>32</spirit:width>
        <spirit:register>
          <spirit:name>R</spirit:name>
          <spirit:addressOffset>0x0</spirit:addressOffset>
          <spirit:size>32</spirit:size>
          <spirit:resetValue>0xDEAD</spirit:resetValue>
          <spirit:resetMask>0xFFFF</spirit:resetMask>
        </spirit:register>
      </spirit:addressBlock>
    </spirit:memoryMap>
  </spirit:memoryMaps>
</spirit:component>
"""


def test_address_block_emitted():
    r = IPXACTExtractor().extract(_phase2_2014())
    abs_ = [e for e in r.entities if e.type == "IPXACT_AddressBlock"]
    assert len(abs_) == 1
    ab = abs_[0]
    assert ab.name == "aes.ipxact_addrblock.blk"
    assert "base_address=0x0" in ab.aliases
    assert "range=0x100" in ab.aliases
    assert "width=32" in ab.aliases
    has_ab = [t for t in r.triples if t.predicate == "has_address_block"]
    contains = [t for t in r.triples if t.predicate == "contains_register"]
    assert len(has_ab) == 1 and has_ab[0].object == ab.name
    assert len(contains) == 1
    assert contains[0].subject == ab.name
    assert contains[0].object == "aes.ipxact_register.CTRL"
    # has_ipxact_register must STILL fire (backwards compat).
    assert any(t.predicate == "has_ipxact_register" for t in r.triples)


def test_register_reset_value_and_mask_2014():
    r = IPXACTExtractor().extract(_phase2_2014())
    regs = [e for e in r.entities if e.type == "IPXACT_Register"]
    assert len(regs) == 1
    text = regs[0].raw_mentions[0].text
    assert "reset_value=0x1" in text
    assert "reset_mask=0xFFFFFFFF" in text


def test_register_reset_value_and_mask_2009_flat():
    r = IPXACTExtractor().extract(_phase2_2009_flat_reset())
    regs = [e for e in r.entities if e.type == "IPXACT_Register"]
    assert len(regs) == 1
    text = regs[0].raw_mentions[0].text
    assert "reset_value=0xDEAD" in text
    assert "reset_mask=0xFFFF" in text


def test_field_enum_emitted():
    r = IPXACTExtractor().extract(_phase2_2014())
    enums = [e for e in r.entities if e.type == "IPXACT_FieldEnum"]
    assert len(enums) == 2
    names = {e.name for e in enums}
    assert "aes.ipxact_register.CTRL.OP.AES_ENC" in names
    assert "aes.ipxact_register.CTRL.OP.AES_DEC" in names
    has_enum = [t for t in r.triples if t.predicate == "has_ipxact_enum"]
    assert len(has_enum) == 2
    enc = next(e for e in enums if e.name.endswith("AES_ENC"))
    assert "value=1" in enc.aliases
    assert "usage=read-write" in enc.aliases  # default applied


def test_field_enum_specifies_canonical():
    known = ["aes.ctrl.op.AES_ENC"]
    r = IPXACTExtractor(known_entity_names=known).extract(_phase2_2014())
    spec = [
        t for t in r.triples
        if t.predicate == "specifies"
        and t.subject == "aes.ipxact_register.CTRL.OP.AES_ENC"
    ]
    assert len(spec) == 1
    assert spec[0].object == "aes.ctrl.op.AES_ENC"


def test_parameter_emitted_and_parameterizes():
    known = ["aes"]  # canonical RTL_Module name (case-insensitive fuse).
    r = IPXACTExtractor(known_entity_names=known).extract(_phase2_2014())
    params = [e for e in r.entities if e.type == "IPXACT_Parameter"]
    assert len(params) == 2
    names = {e.name for e in params}
    assert "aes.ipxact_param.NumRegsKey" in names
    assert "aes.ipxact_param.EN_MASKING" in names
    nr = next(e for e in params if e.name.endswith("NumRegsKey"))
    assert "value=8" in nr.aliases
    assert "data_type=int" in nr.aliases
    parameterizes = [
        t for t in r.triples if t.predicate == "parameterizes"
    ]
    # Only fires when component fuses to a different (canonical) name; here
    # known list contains "aes" exactly so fused == component_name and
    # parameterizes should NOT fire.
    assert parameterizes == []


def test_parameter_parameterizes_when_fused_distinct():
    # Canonical RTL_Module is "AES" (uppercase) so case-insensitive fusion
    # rewrites it; parameterizes edge fires.
    known = ["AES"]
    r = IPXACTExtractor(known_entity_names=known).extract(_phase2_2014())
    parameterizes = [
        t for t in r.triples if t.predicate == "parameterizes"
    ]
    assert len(parameterizes) == 2
    assert all(t.object == "AES" for t in parameterizes)


def test_file_set_emitted_and_implemented_by():
    # Provide canonical SV_File entities the file-set basenames should fuse to.
    known = ["sv.aes", "sv.aes_core"]
    r = IPXACTExtractor(known_entity_names=known).extract(_phase2_2014())
    fsets = [e for e in r.entities if e.type == "IPXACT_FileSet"]
    assert len(fsets) == 1
    assert fsets[0].name == "aes.ipxact_fileset.aes_rtl"
    assert "files=rtl/aes.sv,rtl/aes_core.sv" in fsets[0].aliases
    impl = [t for t in r.triples if t.predicate == "implemented_by"]
    objs = sorted(t.object for t in impl)
    assert objs == ["sv.aes", "sv.aes_core"]


# ---------------------------------------------------------------------------
# Phase-2b additions: bus interface fusion (busType, portMaps, memoryMapRef).
# ---------------------------------------------------------------------------


def _phase2b_2014() -> str:
    return f"""<?xml version="1.0"?>
<ipxact:component {_NS_2014}>
  <ipxact:vendor>v</ipxact:vendor>
  <ipxact:library>l</ipxact:library>
  <ipxact:name>aes</ipxact:name>
  <ipxact:version>0.1</ipxact:version>
  <ipxact:busInterfaces>
    <ipxact:busInterface>
      <ipxact:name>tlul</ipxact:name>
      <ipxact:busType vendor="lowrisc.org" library="ip" name="tlul" version="1.0"/>
      <ipxact:abstractionTypes>
        <ipxact:abstractionType>
          <ipxact:portMaps>
            <ipxact:portMap>
              <ipxact:logicalPort><ipxact:name>a_valid</ipxact:name></ipxact:logicalPort>
              <ipxact:physicalPort><ipxact:name>tl_i_a_valid</ipxact:name></ipxact:physicalPort>
            </ipxact:portMap>
            <ipxact:portMap>
              <ipxact:logicalPort><ipxact:name>a_ready</ipxact:name></ipxact:logicalPort>
              <ipxact:physicalPort><ipxact:name>tl_o_a_ready</ipxact:name></ipxact:physicalPort>
            </ipxact:portMap>
          </ipxact:portMaps>
        </ipxact:abstractionType>
      </ipxact:abstractionTypes>
      <ipxact:slave>
        <ipxact:memoryMapRef memoryMapRef="aes_regs"/>
      </ipxact:slave>
    </ipxact:busInterface>
    <ipxact:busInterface>
      <ipxact:name>tlul2</ipxact:name>
      <ipxact:busType vendor="lowrisc.org" library="ip" name="tlul" version="1.0"/>
      <ipxact:slave/>
    </ipxact:busInterface>
    <ipxact:busInterface>
      <ipxact:name>edn</ipxact:name>
      <ipxact:busType vendor="lowrisc.org" library="ip" name="edn" version="1.0"/>
      <ipxact:master>
        <ipxact:addressSpaceRef addressSpaceRef="edn_addr_space"/>
      </ipxact:master>
    </ipxact:busInterface>
  </ipxact:busInterfaces>
  <ipxact:addressSpaces>
    <ipxact:addressSpace>
      <ipxact:name>edn_addr_space</ipxact:name>
      <ipxact:range>0x1000</ipxact:range>
      <ipxact:width>32</ipxact:width>
    </ipxact:addressSpace>
  </ipxact:addressSpaces>
  <ipxact:memoryMaps>
    <ipxact:memoryMap>
      <ipxact:name>aes_regs</ipxact:name>
      <ipxact:addressBlock>
        <ipxact:name>regs</ipxact:name>
        <ipxact:baseAddress>0x0</ipxact:baseAddress>
        <ipxact:range>0x100</ipxact:range>
        <ipxact:width>32</ipxact:width>
        <ipxact:register>
          <ipxact:name>CTRL</ipxact:name>
          <ipxact:addressOffset>0x0</ipxact:addressOffset>
          <ipxact:size>32</ipxact:size>
        </ipxact:register>
      </ipxact:addressBlock>
    </ipxact:memoryMap>
  </ipxact:memoryMaps>
</ipxact:component>
"""


def test_bus_type_entity_emitted_and_dedup():
    r = IPXACTExtractor().extract(_phase2b_2014())
    bts = [e for e in r.entities if e.type == "IPXACT_BusType"]
    # tlul appears twice, edn once -> dedup to 2 unique busTypes.
    names = sorted(e.name for e in bts)
    assert names == [
        "lowrisc.org::ip::edn::1.0",
        "lowrisc.org::ip::tlul::1.0",
    ]


def test_conforms_to_edge_per_bus_interface():
    r = IPXACTExtractor().extract(_phase2b_2014())
    conforms = [t for t in r.triples if t.predicate == "conforms_to"]
    assert len(conforms) == 3  # one per busInterface
    bif_subs = sorted(t.subject for t in conforms)
    assert bif_subs == [
        "aes.ipxact_busif.edn",
        "aes.ipxact_busif.tlul",
        "aes.ipxact_busif.tlul2",
    ]
    # Both tlul interfaces target the same busType.
    tlul_targets = {t.object for t in conforms
                    if t.subject.startswith("aes.ipxact_busif.tlul")}
    assert tlul_targets == {"lowrisc.org::ip::tlul::1.0"}


def test_port_map_emits_logical_port_and_aggregates_port():
    r = IPXACTExtractor().extract(_phase2b_2014())
    lp = [e for e in r.entities if e.type == "IPXACT_LogicalPort"]
    assert len(lp) == 2
    names = {e.name for e in lp}
    assert "aes.ipxact_busif.tlul.logical.a_valid" in names
    has_lp = [t for t in r.triples if t.predicate == "has_logical_port"]
    assert len(has_lp) == 2
    agg = [t for t in r.triples if t.predicate == "aggregates_port"]
    assert len(agg) == 2
    physfor = [t for t in r.triples if t.predicate == "physical_for"]
    assert len(physfor) == 2


def test_aggregates_port_fuses_to_canonical_port():
    # Pretend tl_i_a_valid is a known canonical Port.
    known = ["aes.tl_i_a_valid"]
    r = IPXACTExtractor(known_entity_names=known).extract(_phase2b_2014())
    agg_to_known = [
        t for t in r.triples
        if t.predicate == "aggregates_port"
        and t.object == "aes.tl_i_a_valid"
    ]
    assert len(agg_to_known) == 1


def test_aggregates_port_unfused_when_unknown():
    r = IPXACTExtractor().extract(_phase2b_2014())
    agg = [t for t in r.triples if t.predicate == "aggregates_port"]
    # No fusion -> bare physical names.
    objs = {t.object for t in agg}
    assert objs == {"tl_i_a_valid", "tl_o_a_ready"}


def test_memory_map_entity_and_has_memory_map_edge():
    r = IPXACTExtractor().extract(_phase2b_2014())
    mm = [e for e in r.entities if e.type == "IPXACT_MemoryMap"]
    assert len(mm) == 1
    assert mm[0].name == "aes.ipxact_memmap.aes_regs"
    has_mm = [t for t in r.triples if t.predicate == "has_memory_map"]
    assert len(has_mm) == 1
    assert has_mm[0].subject == "aes"
    assert has_mm[0].object == "aes.ipxact_memmap.aes_regs"


def test_address_block_now_under_memory_map():
    r = IPXACTExtractor().extract(_phase2b_2014())
    contains = [t for t in r.triples if t.predicate == "contains_address_block"]
    assert len(contains) == 1
    assert contains[0].subject == "aes.ipxact_memmap.aes_regs"
    assert contains[0].object == "aes.ipxact_addrblock.regs"
    # Backwards-compat: has_address_block STILL fires.
    assert any(t.predicate == "has_address_block" for t in r.triples)


def test_exposes_memory_map_on_slave():
    r = IPXACTExtractor().extract(_phase2b_2014())
    em = [t for t in r.triples if t.predicate == "exposes_memory_map"]
    assert len(em) == 1
    assert em[0].subject == "aes.ipxact_busif.tlul"
    assert em[0].object == "aes.ipxact_memmap.aes_regs"


def test_connects_to_address_space_on_master():
    r = IPXACTExtractor().extract(_phase2b_2014())
    asp = [e for e in r.entities if e.type == "IPXACT_AddressSpace"]
    assert len(asp) == 1
    assert asp[0].name == "aes.ipxact_addrspace.edn_addr_space"
    cas = [t for t in r.triples if t.predicate == "connects_to_address_space"]
    assert len(cas) == 1
    assert cas[0].subject == "aes.ipxact_busif.edn"
    assert cas[0].object == "aes.ipxact_addrspace.edn_addr_space"


def test_full_bus_to_csr_traversal():
    r = IPXACTExtractor().extract(_phase2b_2014())
    triples_by_subj: dict = {}
    for t in r.triples:
        triples_by_subj.setdefault(t.subject, []).append(t)

    # 4-hop: busif -> memmap -> addrblock -> register chain (1 reg)
    bif = "aes.ipxact_busif.tlul"
    hop1 = [t for t in triples_by_subj.get(bif, [])
            if t.predicate == "exposes_memory_map"]
    assert hop1
    mm = hop1[0].object
    hop2 = [t for t in triples_by_subj.get(mm, [])
            if t.predicate == "contains_address_block"]
    assert hop2
    ab = hop2[0].object
    hop3 = [t for t in triples_by_subj.get(ab, [])
            if t.predicate == "contains_register"]
    assert hop3
    assert hop3[0].object == "aes.ipxact_register.CTRL"


def test_phase2_layer_tags():
    r = IPXACTExtractor().extract(_phase2_2014())
    for e in r.entities:
        assert e.layer == IPXACT_SOURCE
    for t in r.triples:
        assert t.layer == IPXACT_SOURCE

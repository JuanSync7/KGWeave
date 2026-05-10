# @summary
# Tests for HJSONCSRExtractor — CSR register/field extraction, has_register
# fusion with existing RTL_Module via case-insensitive backend dedup, graceful
# handling of skipto/reserved/window/multireg control entries, and
# extractor_source attribution.
# @end-summary
"""TDD coverage for the OpenTitan-style HJSON CSR extractor."""

from __future__ import annotations

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity
from kgweave.knowledge_graph.extraction.hjson_csr_extractor import (
    HJSONCSRExtractor,
)


_AES_HJSON_ONE_REG = """
{
  name: "aes",
  human_name: "AES Accelerator",
  registers: [
    { name: "CTRL",
      desc: "Control register",
      swaccess: "rw",
      hwaccess: "hro",
      fields: [
        { bits: "0",   name: "EN",   desc: "Enable",   swaccess: "rw", resval: "0" }
        { bits: "31:1", name: "RSVD", desc: "Reserved", swaccess: "ro", resval: "0" }
      ]
    }
  ]
}
"""


_AES_HJSON_WITH_CONTROL_ENTRIES = """
{
  name: "aes",
  registers: [
    { name: "CTRL",
      desc: "Control",
      swaccess: "rw",
      fields: [
        { bits: "0", name: "EN", desc: "Enable", swaccess: "rw", resval: "0" }
      ]
    }
    { skipto: "0x10" }
    { reserved: 4 }
    { window: { name: "MEM", items: 16, swaccess: "rw" } }
    { name: "STATUS",
      desc: "Status",
      swaccess: "ro",
      fields: [
        { bits: "0", name: "IDLE", desc: "Idle", swaccess: "ro", resval: "0" }
      ]
    }
  ]
}
"""


def _make() -> HJSONCSRExtractor:
    return HJSONCSRExtractor()


# ---------------------------------------------------------------------------


def test_csr_register_entity_extracted() -> None:
    """A register named CTRL becomes a CSR_Register entity AES.CTRL."""
    res = _make().extract(_AES_HJSON_ONE_REG, source="aes.hjson")
    regs = [e for e in res.entities if e.type == "CSR_Register"]
    names = {e.name for e in regs}
    assert "AES.CTRL" in names

    reg = next(e for e in regs if e.name == "AES.CTRL")
    assert reg.sources == ["aes.hjson"]
    assert reg.extractor_source == ["hjson_csr"]


def test_csr_field_entity_and_has_field_edge() -> None:
    """Each field becomes a CSR_Field, linked by has_field from its register."""
    res = _make().extract(_AES_HJSON_ONE_REG, source="aes.hjson")

    fields = [e for e in res.entities if e.type == "CSR_Field"]
    names = {e.name for e in fields}
    assert "AES.CTRL.EN" in names
    assert "AES.CTRL.RSVD" in names
    assert len(fields) == 2

    has_field = [t for t in res.triples if t.predicate == "has_field"]
    assert len(has_field) == 2
    objects = {t.object for t in has_field}
    assert objects == {"AES.CTRL.EN", "AES.CTRL.RSVD"}
    for t in has_field:
        assert t.subject == "AES.CTRL"
        # bits should be in evidence_span
        assert "bits=" in t.evidence_span


def test_module_to_csr_register_has_register_edge() -> None:
    """has_register triple from AES module to AES.CTRL register."""
    res = _make().extract(_AES_HJSON_ONE_REG, source="aes.hjson")

    has_reg = [t for t in res.triples if t.predicate == "has_register"]
    assert any(t.subject == "AES" and t.object == "AES.CTRL" for t in has_reg)


def test_module_name_fuses_with_existing_rtl_module() -> None:
    """Pre-existing lowercase 'aes' RTL_Module fuses with hjson AES emission."""
    backend = NetworkXBackend()
    backend.upsert_entities(
        [Entity(name="aes", type="RTL_Module", sources=["rtl/aes.sv"])]
    )

    res = _make().extract(_AES_HJSON_ONE_REG, source="hw/ip/aes/data/aes.hjson")
    backend.upsert_entities(res.entities)

    fused = backend.get_entity("aes")
    assert fused is not None
    assert fused.type == "RTL_Module"  # original type preserved
    assert "rtl/aes.sv" in fused.sources
    assert "hw/ip/aes/data/aes.hjson" in fused.sources


def test_skips_non_register_entries() -> None:
    """skipto / reserved / window entries don't crash and don't emit entities."""
    res = _make().extract(_AES_HJSON_WITH_CONTROL_ENTRIES, source="aes.hjson")

    reg_names = {e.name for e in res.entities if e.type == "CSR_Register"}
    assert reg_names == {"AES.CTRL", "AES.STATUS"}

    # No spurious entities for control entries.
    all_names = {e.name for e in res.entities}
    for stray in ("AES.SKIPTO", "AES.RESERVED", "AES.WINDOW", "AES.MEM"):
        assert stray not in all_names


def test_extractor_source_attribution() -> None:
    """Every triple carries extractor_source='hjson_csr'."""
    res = _make().extract(_AES_HJSON_ONE_REG, source="aes.hjson")
    assert res.triples
    for t in res.triples:
        assert t.extractor_source == "hjson_csr"
    for e in res.entities:
        assert e.extractor_source == ["hjson_csr"]

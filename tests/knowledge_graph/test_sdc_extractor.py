# @summary
# Tests for SDCExtractor — Synopsys Design Constraints (.sdc/.tcl/.xdc)
# parsing into ClockConstraint / IODelay / FalsePath / MulticyclePath /
# ClockGroup entities, with fusion to known Port / ClockDomain entities.
# @end-summary
"""TDD coverage for the SDC timing-constraints extractor."""

from __future__ import annotations

from kgweave.knowledge_graph.backends.networkx_backend import NetworkXBackend
from kgweave.knowledge_graph.common import Entity
from kgweave.knowledge_graph.extraction.sdc_extractor import SDCExtractor


def _make(known=None) -> SDCExtractor:
    return SDCExtractor(known_entity_names=known)


# ---------------------------------------------------------------------------


def test_create_clock() -> None:
    """create_clock with -period and -name emits ClockConstraint + edge."""
    sdc = "create_clock -period 10 -name main_clk [get_ports clk_i]\n"
    res = _make().extract(sdc, source="aes.sdc")

    cc = [e for e in res.entities if e.type == "ClockConstraint"]
    assert len(cc) == 1
    assert cc[0].name == "aes.sdc.create_clock.main_clk"
    assert cc[0].extractor_source == ["sdc"]

    edges = [t for t in res.triples if t.predicate == "constrains_clock"]
    assert len(edges) == 1
    assert edges[0].subject == "aes.sdc.create_clock.main_clk"
    assert edges[0].object == "main_clk"


def test_create_generated_clock() -> None:
    """create_generated_clock emits ClockConstraint with generated flag + source edge."""
    sdc = (
        "create_generated_clock -name div2 -source [get_ports clk_i] "
        "-divide_by 2 [get_pins divider/q]\n"
    )
    res = _make().extract(sdc, source="aes.sdc")

    cc = [e for e in res.entities if e.type == "ClockConstraint"]
    assert len(cc) == 1
    entity = cc[0]
    assert entity.name == "aes.sdc.create_clock.div2"
    # Generated-flag captured in raw_mentions/aliases so caller can detect.
    assert any("generated" in (m.text or "") for m in entity.raw_mentions) \
        or "generated" in entity.aliases

    edges = [t for t in res.triples if t.predicate == "constrains_clock"]
    assert len(edges) == 1
    # Source edge: relative_to_clock points at the master clock (clk_i).
    rel = [t for t in res.triples if t.predicate == "relative_to_clock"]
    assert any(t.object == "clk_i" for t in rel)


def test_set_input_delay() -> None:
    """set_input_delay emits IODelay, constrains_port, relative_to_clock."""
    sdc = "set_input_delay -clock main_clk 2.0 [get_ports data_i]\n"
    res = _make().extract(sdc, source="aes.sdc")

    iod = [e for e in res.entities if e.type == "IODelay"]
    assert len(iod) == 1
    assert iod[0].name == "aes.sdc.input_delay.data_i"

    cp = [t for t in res.triples if t.predicate == "constrains_port"]
    assert len(cp) == 1
    assert cp[0].object == "data_i"

    rc = [t for t in res.triples if t.predicate == "relative_to_clock"]
    assert len(rc) == 1
    assert rc[0].object == "main_clk"


def test_set_false_path() -> None:
    """set_false_path emits FalsePath with from_endpoint and to_endpoint edges."""
    sdc = "set_false_path -from [get_ports a_i] -to [get_ports b_o]\n"
    res = _make().extract(sdc, source="aes.sdc")

    fp = [e for e in res.entities if e.type == "FalsePath"]
    assert len(fp) == 1
    assert fp[0].name == "aes.sdc.false_path.0"

    fr = [t for t in res.triples if t.predicate == "from_endpoint"]
    to = [t for t in res.triples if t.predicate == "to_endpoint"]
    assert len(fr) == 1 and fr[0].object == "a_i"
    assert len(to) == 1 and to[0].object == "b_o"


def test_set_multicycle_path() -> None:
    """set_multicycle_path emits MulticyclePath with cycles=2 and clock edges."""
    sdc = "set_multicycle_path -setup 2 -from [get_clocks fast_clk] -to [get_clocks slow_clk]\n"
    res = _make().extract(sdc, source="aes.sdc")

    mc = [e for e in res.entities if e.type == "MulticyclePath"]
    assert len(mc) == 1
    entity = mc[0]
    # cycles attribute carried in raw_mentions text.
    joined = " ".join(m.text for m in entity.raw_mentions)
    assert "cycles=2" in joined

    fr = [t for t in res.triples if t.predicate == "from_endpoint"]
    to = [t for t in res.triples if t.predicate == "to_endpoint"]
    assert any(t.object == "fast_clk" for t in fr)
    assert any(t.object == "slow_clk" for t in to)


def test_set_clock_groups() -> None:
    """set_clock_groups emits ClockGroup entity with one groups_clock per member."""
    sdc = "set_clock_groups -asynchronous -group {clk_a clk_b} -group {clk_c}\n"
    res = _make().extract(sdc, source="aes.sdc")

    cg = [e for e in res.entities if e.type == "ClockGroup"]
    assert len(cg) == 1

    grp = [t for t in res.triples if t.predicate == "groups_clock"]
    assert len(grp) == 3
    assert {t.object for t in grp} == {"clk_a", "clk_b", "clk_c"}


def test_comments_and_continuations() -> None:
    """Comments, line continuations, and blank lines parse cleanly."""
    sdc = (
        "# this is a comment\n"
        "\n"
        "create_clock -period 10 \\\n"
        "    -name main_clk \\\n"
        "    [get_ports clk_i]   ;# trailing comment\n"
        "\n"
        "# another comment\n"
        "set_input_delay -clock main_clk 1.5 [get_ports d_i]\n"
    )
    res = _make().extract(sdc, source="aes.sdc")
    cc = [e for e in res.entities if e.type == "ClockConstraint"]
    iod = [e for e in res.entities if e.type == "IODelay"]
    assert len(cc) == 1
    assert len(iod) == 1


def test_fusion_to_known_ports() -> None:
    """Edges target the namespaced names when known_entity_names supplied."""
    sdc = (
        "create_clock -period 10 -name main_clk [get_ports clk_i]\n"
        "set_input_delay -clock main_clk 1.0 [get_ports data_i]\n"
    )
    known = ["aes.clk_i", "aes.data_i", "main_clk"]
    res = _make(known=known).extract(sdc, source="aes.sdc")

    cp = [t for t in res.triples if t.predicate == "constrains_port"]
    assert any(t.object == "aes.data_i" for t in cp)


def test_unresolved_variable_kept_literal() -> None:
    """Tcl variables like $CLK_PERIOD are preserved literally, not evaluated."""
    sdc = "create_clock -period $CLK_PERIOD -name main_clk [get_ports clk_i]\n"
    res = _make().extract(sdc, source="aes.sdc")

    cc = [e for e in res.entities if e.type == "ClockConstraint"]
    assert len(cc) == 1
    # period attribute carried as literal in raw_mentions.
    joined = " ".join(m.text for m in cc[0].raw_mentions)
    assert "$CLK_PERIOD" in joined


def test_round_trip_extract_to_backend() -> None:
    """Full pipeline: extract → upsert → query backend."""
    sdc = (
        "create_clock -period 10 -name main_clk [get_ports clk_i]\n"
        "set_input_delay -clock main_clk 1.0 [get_ports data_i]\n"
        "set_false_path -from [get_ports a_i] -to [get_ports b_o]\n"
    )
    backend = NetworkXBackend()
    backend.upsert_entities([
        Entity(name="main_clk", type="ClockDomain"),
        Entity(name="clk_i", type="Port"),
        Entity(name="data_i", type="Port"),
        Entity(name="a_i", type="Port"),
        Entity(name="b_o", type="Port"),
    ])
    res = SDCExtractor(known_entity_names=list(
        backend.get_all_node_names_and_aliases().keys()
    )).extract(sdc, source="aes.sdc")
    backend.upsert_entities(res.entities)
    backend.upsert_triples(res.triples)

    assert backend.get_entity("aes.sdc.create_clock.main_clk") is not None
    assert backend.get_entity("aes.sdc.input_delay.data_i") is not None
    assert backend.get_entity("aes.sdc.false_path.0") is not None

    out = backend.get_outgoing_edges("aes.sdc.create_clock.main_clk")
    assert any(t.predicate == "constrains_clock" and t.object == "main_clk"
               for t in out)

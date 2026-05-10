"""Tier B Phase 2: dvsim hjson reader tests.

dvsim sim_cfg files declare ``name:`` (the IP / module name under test) and
a ``tests:`` array. Each test entry's ``name`` becomes a SW_Test source
candidate; the ``name`` field of the cfg is the canonical RTL module.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from kgweave.knowledge_graph.common.sw_test_buildsys import (
    BuildSystemLink,
    discover_links,
)


def _make_dvsim_cfg(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(dedent(content))
    return p


# ---------------------------------------------------------------------------
# (1) Basic parse: name + tests[] array
# ---------------------------------------------------------------------------


def test_dvsim_reader_emits_links_for_each_test(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    cfg = _make_dvsim_cfg(tmp_path, "aes_sim_cfg.hjson", """
        {
          name: aes
          dut: aes
          tb: tb
          tests: [
            {
              name: aes_smoke
            }
            {
              name: aes_stress
            }
            {
              name: aes_b2b
            }
          ]
        }
    """)
    reader = DvsimHjsonReader()
    assert reader.applies_to(tmp_path) is True
    links = reader.read(tmp_path)
    assert len(links) == 3
    assert {l.module_name for l in links} == {"aes"}
    assert {l.source_format for l in links} == {"dvsim_hjson"}
    assert {l.confidence_tier for l in links} == {"high"}
    test_names = {Path(l.test_path).name for l in links}
    assert "aes_smoke" in test_names
    assert "aes_stress" in test_names
    assert "aes_b2b" in test_names
    # All point back to the same source_file.
    assert all(Path(l.source_file).name == "aes_sim_cfg.hjson" for l in links)


# ---------------------------------------------------------------------------
# (2) When `name:` differs from `dut:`, dut wins (it's the actual module)
# ---------------------------------------------------------------------------


def test_dvsim_reader_prefers_dut_over_name(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    _make_dvsim_cfg(tmp_path, "x_sim_cfg.hjson", """
        {
          name: aes_masked
          dut: aes
          tests: [
            {
              name: aes_smoke
            }
          ]
        }
    """)
    links = DvsimHjsonReader().read(tmp_path)
    assert len(links) == 1
    assert links[0].module_name == "aes"


# ---------------------------------------------------------------------------
# (3) No tests array → no links (but no crash)
# ---------------------------------------------------------------------------


def test_dvsim_reader_no_tests_array(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    _make_dvsim_cfg(tmp_path, "empty_sim_cfg.hjson", """
        {
          name: aes
          dut: aes
        }
    """)
    links = DvsimHjsonReader().read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (4) Multiple cfg files in tree — all picked up
# ---------------------------------------------------------------------------


def test_dvsim_reader_walks_multiple_cfgs(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    sub_aes = tmp_path / "hw" / "ip" / "aes" / "dv"
    sub_aes.mkdir(parents=True)
    (sub_aes / "aes_sim_cfg.hjson").write_text(
        '{\n  name: aes\n  tests: [\n    {\n      name: aes_smoke\n    }\n  ]\n}\n'
    )
    sub_hmac = tmp_path / "hw" / "ip" / "hmac" / "dv"
    sub_hmac.mkdir(parents=True)
    (sub_hmac / "hmac_sim_cfg.hjson").write_text(
        '{\n  name: hmac\n  tests: [\n    {\n      name: hmac_smoke\n    }\n    {\n      name: hmac_stress\n    }\n  ]\n}\n'
    )
    links = DvsimHjsonReader().read(tmp_path)
    assert len(links) == 3
    by_mod = {}
    for l in links:
        by_mod.setdefault(l.module_name, []).append(l)
    assert sorted(by_mod) == ["aes", "hmac"]
    assert len(by_mod["aes"]) == 1
    assert len(by_mod["hmac"]) == 2


# ---------------------------------------------------------------------------
# (5) Malformed hjson surfaces a clear warning, no crash, returns []
# ---------------------------------------------------------------------------


def test_dvsim_reader_malformed_hjson(tmp_path, caplog):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    (tmp_path / "broken_sim_cfg.hjson").write_text("{ this is :: not valid hjson @@@")
    with caplog.at_level("WARNING"):
        links = DvsimHjsonReader().read(tmp_path)
    assert links == []


# ---------------------------------------------------------------------------
# (6) applies_to: False when no *sim_cfg.hjson exists
# ---------------------------------------------------------------------------


def test_dvsim_reader_applies_to_false_when_no_files(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    (tmp_path / "random.txt").write_text("hello")
    assert DvsimHjsonReader().applies_to(tmp_path) is False


# ---------------------------------------------------------------------------
# (7) Real OpenTitan AES dvsim file (skipped if absent)
# ---------------------------------------------------------------------------


def test_real_opentitan_aes_dvsim(tmp_path):
    real = Path.home() / "RagWeave" / "opentitan_data" / "hw" / "ip" / "aes" / "dv"
    if not real.exists():
        pytest.skip("OpenTitan data not present")

    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    # Stage just the AES dv tree under tmp_path so the reader's recursive
    # glob doesn't walk the entire OpenTitan checkout.
    import shutil
    staged = tmp_path / "hw" / "ip" / "aes" / "dv"
    shutil.copytree(real, staged)

    links = DvsimHjsonReader().read(tmp_path)
    aes_links = [l for l in links if l.module_name == "aes"]
    assert len(aes_links) >= 10, f"expected ≥10 aes links, got {len(aes_links)}"


# ---------------------------------------------------------------------------
# (8) Top-level chip cfg with heavy import_cfgs but no own tests[]
# ---------------------------------------------------------------------------


def test_dvsim_chip_cfg_with_import_cfgs_only(tmp_path):
    """Chip-level cfgs (e.g. chip_sim_cfg.hjson) declare ``import_cfgs:``
    pointing at per-IP cfgs and may not carry a ``tests:`` array of their
    own. The reader must not crash and should emit no spurious links from
    the chip cfg itself; the per-IP cfgs are picked up separately by the
    glob walk."""
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    _make_dvsim_cfg(tmp_path, "chip_sim_cfg.hjson", """
        {
          name: chip_earlgrey_asic
          dut: chip_earlgrey_asic
          import_cfgs:
          [
            "{proj_root}/hw/ip/aes/dv/aes_sim_cfg.hjson"
            "{proj_root}/hw/ip/hmac/dv/hmac_sim_cfg.hjson"
          ]
          regressions:
          [
            {
              name: smoke
            }
          ]
        }
    """)
    sub_aes = tmp_path / "hw" / "ip" / "aes" / "dv"
    sub_aes.mkdir(parents=True)
    (sub_aes / "aes_sim_cfg.hjson").write_text(
        '{\n  name: aes\n  dut: aes\n  tests:\n  [\n    {\n      name: aes_smoke\n    }\n  ]\n}\n'
    )
    links = DvsimHjsonReader().read(tmp_path)
    # Chip cfg has no own tests[] — but recursive import_cfgs resolution
    # produces one transitively-attributed link per imported IP test, plus
    # the direct glob discovery of the IP cfg adds another. Both target
    # the same (test, module). Reader does not dedup (downstream does) so
    # we expect two links here, one with chain attribution and one without.
    assert len(links) == 2
    assert {l.module_name for l in links} == {"aes"}
    # Transitive link carries the import-chain provenance.
    chain_links = [l for l in links if l.raw_match.get("dvsim_import_chain")]
    direct_links = [l for l in links if not l.raw_match.get("dvsim_import_chain")]
    assert len(chain_links) == 1
    assert len(direct_links) == 1
    chain = chain_links[0].raw_match["dvsim_import_chain"]
    assert chain[-1].endswith("aes_sim_cfg.hjson")
    assert any(p.endswith("chip_sim_cfg.hjson") for p in chain)
    # Source attribution (where the test was defined) preserved on both.
    assert all(Path(l.source_file).name == "aes_sim_cfg.hjson" for l in links)
    # No link should claim the chip module name.
    assert not any(l.module_name == "chip_earlgrey_asic" for l in links)


# ---------------------------------------------------------------------------
# (9) FPV cfg with `tool: jaspergold` parses identically to sim cfg
# ---------------------------------------------------------------------------


def test_dvsim_fpv_cfg_jaspergold_tool(tmp_path):
    """FPV cfgs (formal property verification) carry ``tool: jaspergold``
    and a different test_pattern, but the reader is tool-agnostic and
    only needs name+tests[]. Provenance attributes should preserve the
    tool field for downstream debugging."""
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    _make_dvsim_cfg(tmp_path, "aes_fpv_cfg.hjson", """
        {
          name: aes
          dut: aes
          tool: jaspergold
          fusesoc_core: lowrisc:fpv:aes_fpv
          import_cfgs: ["{proj_root}/hw/formal/tools/dvsim/common_fpv_cfg.hjson"]
          tests:
          [
            {
              name: aes_fpv
            }
            {
              name: aes_csr_assert_fpv
            }
          ]
        }
    """)
    links = DvsimHjsonReader().read(tmp_path)
    assert len(links) == 2
    assert {l.module_name for l in links} == {"aes"}
    test_names = {Path(l.test_path).name for l in links}
    assert "aes_fpv" in test_names
    assert "aes_csr_assert_fpv" in test_names


# ---------------------------------------------------------------------------
# (10) Cross-IP cfg with a multi-segment dut name and uvm_test attribute
# ---------------------------------------------------------------------------


def test_dvsim_cross_ip_cfg_with_uvm_test(tmp_path):
    """Some cfgs target a top-level integration block whose dut: is a
    multi-segment identifier and whose tests carry a uvm_test attribute.
    The raw_match dict should preserve that uvm_test value verbatim."""
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    _make_dvsim_cfg(tmp_path, "xbar_main_sim_cfg.hjson", """
        {
          name: xbar_main
          dut: xbar_main
          tb: tb
          tests: [
            {
              name: xbar_main_smoke
              uvm_test: xbar_base_test
              uvm_test_seq: xbar_smoke_vseq
            }
            {
              name: xbar_main_random
              uvm_test: xbar_base_test
              uvm_test_seq: xbar_random_vseq
            }
          ]
        }
    """)
    links = DvsimHjsonReader().read(tmp_path)
    assert len(links) == 2
    assert {l.module_name for l in links} == {"xbar_main"}
    uvm_tests = {l.raw_match.get("uvm_test") for l in links}
    assert "xbar_base_test" in uvm_tests


# ===========================================================================
# V3 #2: import_cfgs recursive resolution
# ===========================================================================


def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dedent(body))
    return p


# ---------------------------------------------------------------------------
# (R1) Chip cfg with only import_cfgs[] (no own tests[]) resolves transitively
# ---------------------------------------------------------------------------


def test_dvsim_recursive_chip_only_imports(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    # Place the imported IP cfg outside the reader's glob root so the only
    # way it can be discovered is via the chip cfg's import_cfgs entry.
    project_root = tmp_path / "proj"
    external = tmp_path / "external" / "ip" / "aes" / "dv"
    _write(external / "aes_sim_cfg.hjson", """
        {
          name: aes
          dut: aes
          tests:
          [
            {
              name: aes_smoke
            }
            {
              name: aes_stress
            }
          ]
        }
    """)
    chip = _write(project_root / "chip_sim_cfg.hjson", f"""
        {{
          name: chip_earlgrey_asic
          dut: chip_earlgrey_asic
          import_cfgs: [
            "{external / "aes_sim_cfg.hjson"}"
          ]
        }}
    """)
    reader = DvsimHjsonReader()
    links = reader.read(project_root)
    # Both AES tests surface via the import chain.
    assert {Path(l.test_path).name for l in links} == {"aes_smoke", "aes_stress"}
    assert {l.module_name for l in links} == {"aes"}
    # Transitive links retain attribution to the cfg the tests live in.
    assert all(Path(l.source_file).name == "aes_sim_cfg.hjson" for l in links)
    for link in links:
        chain = link.raw_match.get("dvsim_import_chain")
        assert isinstance(chain, list) and len(chain) >= 2
        assert chain[0].endswith("chip_sim_cfg.hjson")
        assert chain[-1].endswith("aes_sim_cfg.hjson")
        assert link.raw_match.get("dvsim_root_cfg", "").endswith("chip_sim_cfg.hjson")


# ---------------------------------------------------------------------------
# (R2) Union semantics: cfg with own tests AND import_cfgs emits both
# ---------------------------------------------------------------------------


def test_dvsim_recursive_union_own_and_imported(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    project_root = tmp_path / "proj"
    external = tmp_path / "external"
    _write(external / "extra_cfg.hjson", """
        {
          name: hmac
          dut: hmac
          tests:
          [
            {
              name: hmac_extra
            }
          ]
        }
    """)
    _write(project_root / "main_sim_cfg.hjson", f"""
        {{
          name: aes
          dut: aes
          tests:
          [
            {{
              name: aes_own
            }}
          ]
          import_cfgs:
          [
            "{external / "extra_cfg.hjson"}"
          ]
        }}
    """)
    links = DvsimHjsonReader().read(project_root)
    by_test = {Path(l.test_path).name: l for l in links}
    assert "aes_own" in by_test
    assert "hmac_extra" in by_test
    assert by_test["aes_own"].module_name == "aes"
    assert by_test["hmac_extra"].module_name == "hmac"
    # Own tests have no chain attribute; imported tests do.
    assert "dvsim_import_chain" not in by_test["aes_own"].raw_match or \
        not by_test["aes_own"].raw_match.get("dvsim_import_chain")
    assert by_test["hmac_extra"].raw_match.get("dvsim_import_chain")


# ---------------------------------------------------------------------------
# (R3) Cycle protection: A imports B imports A — no infinite loop
# ---------------------------------------------------------------------------


def test_dvsim_recursive_cycle_protection(tmp_path, caplog):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    project_root = tmp_path / "proj"
    a_path = project_root / "a_sim_cfg.hjson"
    b_path = project_root / "b_sim_cfg.hjson"
    _write(a_path, f"""
        {{
          name: a_mod
          dut: a_mod
          tests:
          [
            {{
              name: a_test
            }}
          ]
          import_cfgs:
          [
            "{b_path}"
          ]
        }}
    """)
    _write(b_path, f"""
        {{
          name: b_mod
          dut: b_mod
          tests:
          [
            {{
              name: b_test
            }}
          ]
          import_cfgs:
          [
            "{a_path}"
          ]
        }}
    """)
    with caplog.at_level("WARNING"):
        links = DvsimHjsonReader().read(project_root)
    # a_test and b_test each emitted once via direct glob; cycle visits
    # produce additional transitive entries but the reader breaks before
    # looping. We at minimum surface both unique test names without hanging.
    test_names = {Path(l.test_path).name for l in links}
    assert "a_test" in test_names
    assert "b_test" in test_names
    # Cycle warning logged.
    assert any("cycle" in rec.message.lower() for rec in caplog.records), \
        f"expected cycle warning, got {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# (R4) Depth limit honored — chain of 6, depth=5 drops the sixth
# ---------------------------------------------------------------------------


def test_dvsim_recursive_depth_limit(tmp_path, caplog):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    # Each level lives outside project_root so the only path to it is via
    # imports. project_root contains only the entry cfg.
    project_root = tmp_path / "proj"
    ext = tmp_path / "ext"
    paths = []
    for i in range(6):
        paths.append(ext / f"level{i}.hjson")
    for i in range(6):
        if i < 5:
            nxt = f'import_cfgs:\n          [\n            "{paths[i + 1]}"\n          ]'
        else:
            nxt = ""
        _write(paths[i], f"""
            {{
              name: mod{i}
              dut: mod{i}
              tests:
              [
                {{
                  name: test{i}
                }}
              ]
              {nxt}
            }}
        """)
    entry = _write(project_root / "entry_cfg.hjson", f"""
        {{
          name: entry_mod
          dut: entry_mod
          import_cfgs:
          [
            "{paths[0]}"
          ]
        }}
    """)
    # depth=5 — entry recurses into level0..level4 (5 hops), level5 dropped.
    reader = DvsimHjsonReader(max_import_depth=5)
    with caplog.at_level("WARNING"):
        links = reader.read(project_root)
    test_names = {Path(l.test_path).name for l in links}
    for i in range(5):
        assert f"test{i}" in test_names, f"test{i} should be reachable within depth=5"
    assert "test5" not in test_names, "test5 must be dropped at depth limit"
    assert any("depth" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# (R5) Missing import path — warning + sibling imports still resolve
# ---------------------------------------------------------------------------


def test_dvsim_recursive_missing_import(tmp_path, caplog):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    project_root = tmp_path / "proj"
    ext = tmp_path / "ext"
    _write(ext / "good.hjson", """
        {
          name: good_mod
          dut: good_mod
          tests:
          [
            {
              name: good_test
            }
          ]
        }
    """)
    missing = ext / "does_not_exist.hjson"
    _write(project_root / "entry_cfg.hjson", f"""
        {{
          name: entry
          dut: entry
          import_cfgs:
          [
            "{missing}"
            "{ext / "good.hjson"}"
          ]
        }}
    """)
    with caplog.at_level("WARNING"):
        links = DvsimHjsonReader().read(project_root)
    test_names = {Path(l.test_path).name for l in links}
    assert "good_test" in test_names
    assert any("does_not_exist" in r.message or "missing" in r.message.lower() or
               "not found" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# (R6) {proj_root} token expansion
# ---------------------------------------------------------------------------


def test_dvsim_recursive_proj_root_token(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    project_root = tmp_path / "proj"
    sub = _write(project_root / "hw" / "ip" / "aes" / "dv" / "aes_sim_cfg.hjson", """
        {
          name: aes
          dut: aes
          tests:
          [
            {
              name: aes_smoke
            }
          ]
        }
    """)
    chip = _write(project_root / "top" / "chip_sim_cfg.hjson", """
        {
          name: chip
          dut: chip
          import_cfgs:
          [
            "{proj_root}/hw/ip/aes/dv/aes_sim_cfg.hjson"
          ]
        }
    """)
    # Pass project_root explicitly so {proj_root} can be expanded.
    links = DvsimHjsonReader().read(project_root)
    test_names = {Path(l.test_path).name for l in links}
    assert "aes_smoke" in test_names
    # Verify at least one link reached aes_smoke via the chip cfg chain.
    chain_links = [l for l in links if l.raw_match.get("dvsim_import_chain")
                   and Path(l.test_path).name == "aes_smoke"]
    assert chain_links, "expected a transitively-resolved aes_smoke link"
    chain = chain_links[0].raw_match["dvsim_import_chain"]
    assert any("chip_sim_cfg.hjson" in p for p in chain)


# ---------------------------------------------------------------------------
# (R7) dvsim_import_chain ordering: root first, defining cfg last
# ---------------------------------------------------------------------------


def test_dvsim_recursive_chain_ordering(tmp_path):
    from kgweave.knowledge_graph.extraction.buildsys_dvsim import DvsimHjsonReader

    project_root = tmp_path / "proj"
    ext = tmp_path / "ext"
    leaf = _write(ext / "leaf_cfg.hjson", """
        {
          name: leaf_mod
          dut: leaf_mod
          tests:
          [
            {
              name: leaf_test
            }
          ]
        }
    """)
    mid = _write(ext / "mid_cfg.hjson", f"""
        {{
          name: mid
          dut: mid
          import_cfgs:
          [
            "{leaf}"
          ]
        }}
    """)
    root_cfg = _write(project_root / "root_cfg.hjson", f"""
        {{
          name: root_mod
          dut: root_mod
          import_cfgs:
          [
            "{mid}"
          ]
        }}
    """)
    links = DvsimHjsonReader().read(project_root)
    leaf_links = [l for l in links if Path(l.test_path).name == "leaf_test"]
    assert leaf_links
    chain = leaf_links[0].raw_match["dvsim_import_chain"]
    # Chain: root -> mid -> leaf
    assert len(chain) == 3
    assert chain[0].endswith("root_cfg.hjson")
    assert chain[1].endswith("mid_cfg.hjson")
    assert chain[2].endswith("leaf_cfg.hjson")
    assert leaf_links[0].raw_match["dvsim_root_cfg"].endswith("root_cfg.hjson")


# ---------------------------------------------------------------------------
# (R8 — infra) YAML round-trip dvsim_max_import_depth
# ---------------------------------------------------------------------------


def test_load_sw_test_config_dvsim_max_import_depth(tmp_path):
    from kgweave.knowledge_graph.common.sw_test_config import load_sw_test_config

    yml = tmp_path / "cfg.yaml"
    yml.write_text(dedent("""
        build_systems:
          dvsim_hjson:
            enabled: true
            max_import_depth: 3
    """))
    cfg = load_sw_test_config(str(yml))
    assert cfg.build_systems.dvsim_hjson_enabled is True
    assert cfg.build_systems.dvsim_max_import_depth == 3


# ---------------------------------------------------------------------------
# (R9 — integration) discover_links() on 3-level chip→top→ip fixture
# ---------------------------------------------------------------------------


def test_discover_links_three_level_chain(tmp_path):
    from kgweave.knowledge_graph.common.sw_test_buildsys import (
        SwTestBuildSystemConfig,
        default_readers,
        discover_links,
    )

    project_root = tmp_path / "proj"
    ip_cfg = _write(
        project_root / "hw" / "ip" / "aes" / "dv" / "aes_sim_cfg.hjson",
        """
        {
          name: aes
          dut: aes
          tests:
          [
            {
              name: aes_smoke
            }
          ]
        }
        """,
    )
    top_cfg = _write(
        project_root / "hw" / "top_earlgrey" / "dv" / "top_earlgrey_sim_cfg.hjson",
        f"""
        {{
          name: top_earlgrey
          dut: top_earlgrey
          import_cfgs:
          [
            "{ip_cfg}"
          ]
        }}
        """,
    )
    chip_cfg = _write(
        project_root / "hw" / "chip" / "dv" / "chip_sim_cfg.hjson",
        f"""
        {{
          name: chip
          dut: chip
          import_cfgs:
          [
            "{top_cfg}"
          ]
        }}
        """,
    )
    bs_cfg = SwTestBuildSystemConfig(dvsim_hjson_enabled=True)
    readers = default_readers(bs_cfg)
    links = discover_links(project_root, readers=readers)
    # Three-level resolution should surface aes_smoke via the chip→top→ip
    # chain, in addition to the direct glob hits at each level.
    chain_links = [l for l in links
                   if Path(l.test_path).name == "aes_smoke"
                   and l.raw_match.get("dvsim_import_chain")
                   and any("chip_sim_cfg.hjson" in p
                           for p in l.raw_match["dvsim_import_chain"])]
    assert chain_links, "expected aes_smoke reached via chip→top→ip chain"
    chain = chain_links[0].raw_match["dvsim_import_chain"]
    assert chain[-1].endswith("aes_sim_cfg.hjson")
    assert any("chip_sim_cfg.hjson" in p for p in chain)
    assert any("top_earlgrey_sim_cfg.hjson" in p for p in chain)

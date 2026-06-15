"""v1.6-#1 regression: md↔sv lift/promote cache must not poison cross-source runs.

The MD `test_isolation_i7.py` suite calls `extract(source="sv", ...)` with
`[fifo.sv, fifo_pkg.sv]` (fifo-first). The SV legacy test_types fixtures
then call `build_kg([fifo_pkg.sv, fifo.sv])` (pkg-first). Pre-v1.6-#1 the
shared promote cache replayed the MD-order delta (with `_unresolved.fifo_pkg`
edges) for the SV legacy run, flipping S32/S50 assertions to zero matches.

The fix makes `compute_corpus_fp` order-preserving so the two file orderings
hash to distinct corpus fingerprints and don't share cache entries.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


SV_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "sv"
)
MD_FIXTURE_DIR = (
    Path(__file__).resolve().parent / "md" / "fixtures"
)


def _imports_dsts(graph: dict) -> set[str]:
    return {
        e["dst"]
        for e in graph["edges"]
        if e.get("type") == "imports" and "fifo:" in e.get("src", "")
    }


def test_sv_legacy_build_unpoisoned_by_prior_md_test_isolation_extract():
    """Pkg-first build_kg must resolve `fifo.imports -> fifo_pkg` even after
    a fifo-first extract has run in the same process (md/test_isolation_i7
    triggers this fifo-first extract)."""
    from knowledge_graph import extract, open_store
    from knowledge_graph.builders.sv.build import build_kg

    # Poison-prelude: mimics md/test_isolation_i7's fifo-first SV extract.
    tmp = Path(tempfile.mkdtemp(prefix="v16_1_"))
    try:
        store = open_store(tmp / "iso.kuzu")
        extract(
            store,
            source="sv",
            corpus="demo",
            paths=[SV_FIXTURE_DIR / "fifo.sv", SV_FIXTURE_DIR / "fifo_pkg.sv"],
        )
        store.close()

        # Legacy build_kg in pkg-first order.
        graph, _, _ = build_kg(
            [SV_FIXTURE_DIR / "fifo_pkg.sv", SV_FIXTURE_DIR / "fifo.sv"]
        )
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    dsts = _imports_dsts(graph)
    assert any("fifo_pkg" in d and not d.startswith("_unresolved.") for d in dsts), (
        f"fifo.imports must resolve to the fifo_pkg node, got: {dsts}"
    )
    assert not any(d == "_unresolved.fifo_pkg" for d in dsts), (
        f"fifo.imports must NOT resolve to the unresolved placeholder, got: {dsts}"
    )


def test_corpus_fp_distinguishes_file_order():
    """compute_corpus_fp must produce DIFFERENT fingerprints for the two
    file orderings — otherwise the promote cache can replay the wrong
    delta. This is a direct, in-process check of the fix's contract that
    survives test-isolation issues with the shared module-level caches.
    """
    from knowledge_graph.builders.sv.lift import _sha256_hex
    from knowledge_graph.builders.sv.semantic.promote_cache import (
        compute_corpus_fp,
    )

    files = []
    for p in (SV_FIXTURE_DIR / "fifo.sv", SV_FIXTURE_DIR / "fifo_pkg.sv"):
        files.append((str(p.resolve()), _sha256_hex(p.read_bytes())))

    fp_fifo_first = compute_corpus_fp(files)
    fp_pkg_first = compute_corpus_fp(list(reversed(files)))

    assert fp_fifo_first != fp_pkg_first, (
        "corpus_fp must encode file order; same fp for two orderings causes "
        "promote-cache replay bugs (v1.6-#1)."
    )

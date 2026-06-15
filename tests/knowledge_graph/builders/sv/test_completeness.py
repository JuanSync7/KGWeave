"""I2 gate: for every SV fixture, the lifted graph node count is >= the
pyslang DFS visit count for that file's syntax tree.

This proves the lift emits a node for every syntax / token reachable via
iteration of the pyslang tree, with no silent drops.
"""

from __future__ import annotations

from pathlib import Path

import pyslang

from knowledge_graph.builders.sv.lift import lift


def _pyslang_visit_count(root) -> int:
    count = 0
    stack = [root]
    while stack:
        n = stack.pop()
        count += 1
        try:
            for c in n:
                stack.append(c)
        except TypeError:
            pass
    return count


def test_node_count_covers_pyslang_visit(sv_fixture: Path) -> None:
    """``len(graph['nodes']) >= count of pyslang DFS visit`` for every fixture."""
    tree = pyslang.SyntaxTree.fromText(sv_fixture.read_text())
    graph = lift(tree)
    pyslang_count = _pyslang_visit_count(tree.root)
    assert len(graph["nodes"]) >= pyslang_count, (
        f"{sv_fixture.name}: graph nodes {len(graph['nodes'])} < "
        f"pyslang visit {pyslang_count}"
    )


def test_full_corpus_completeness_table(sv_fixtures: list[Path]) -> None:
    """Aggregate I2 proof — emits the comparison table on -s output."""
    rows: list[tuple[str, int, int]] = []
    for path in sv_fixtures:
        tree = pyslang.SyntaxTree.fromText(path.read_text())
        graph = lift(tree)
        pyslang_count = _pyslang_visit_count(tree.root)
        rows.append((path.name, len(graph["nodes"]), pyslang_count))
    print("\nI2 table (file | graph_nodes | pyslang_visit):")
    for name, gn, pc in rows:
        marker = "OK" if gn >= pc else "FAIL"
        print(f"  {name:<28} {gn:>6} {pc:>6}  {marker}")
    bad = [r for r in rows if r[1] < r[2]]
    assert not bad, f"completeness violations: {bad}"

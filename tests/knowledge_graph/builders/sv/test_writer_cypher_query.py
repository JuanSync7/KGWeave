"""Golden semantic query parity: 'all module names' via Cypher matches the
python ``semantic/queries`` helper view of the dict.

Modules are promoted with ``semantic.role == 'module'`` and
``kind == 'SyntaxKind.ModuleDeclaration'``. After write_graph, the Cypher
projection MUST return the same set of module names.
"""

from __future__ import annotations


# The locked-in Cypher: every Module is a semantic Node whose payload encodes
# role='module'. We expose the name via the promoted ``name`` column so
# downstream Phase D intents stay schema-stable.
MODULES_CYPHER = """
MATCH (n:Node)
WHERE n.category = 'semantic'
  AND n.kind = 'SyntaxKind.ModuleDeclaration'
RETURN n.name AS name ORDER BY name
"""


def _modules_from_dict(graph) -> list[str]:
    out = []
    for n in graph["nodes"]:
        sem = n.get("semantic")
        if not isinstance(sem, dict):
            continue
        if sem.get("role") != "module":
            continue
        name = sem.get("name")
        if name:
            out.append(name)
    return sorted(out)


def test_all_modules_cypher_matches_python_helper(sv_corpus_store) -> None:
    """Same set of module names from Cypher and from the dict helper."""
    store, graph, _origins, _stats = sv_corpus_store
    expected = _modules_from_dict(graph)
    assert expected, "fixture corpus must contain at least one module"

    res = store.conn.execute(MODULES_CYPHER)
    got: list[str] = []
    while res.has_next():
        row = res.get_next()
        if row[0] is not None:
            got.append(row[0])
    got.sort()

    assert got == expected, (
        f"module-name set mismatch\n  cypher: {got}\n  dict:   {expected}"
    )


def test_module_count_via_cypher(sv_corpus_store) -> None:
    """Sanity: every module from the dict has exactly one Kuzu row."""
    store, graph, _origins, _stats = sv_corpus_store
    expected_count = len(_modules_from_dict(graph))
    res = store.conn.execute(
        "MATCH (n:Node {category: 'semantic', kind: 'SyntaxKind.ModuleDeclaration'}) "
        "RETURN count(*)"
    )
    assert res.get_next()[0] == expected_count

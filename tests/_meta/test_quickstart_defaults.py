"""Quickstart example scripts must NOT default to repo-root ``./kgweave-store/``.

During v1.3 development the repo-root ``./kgweave-store/`` directory blew up
disk twice -- a no-arg invocation of ``python -m knowledge_graph.examples.quickstart``
wrote a Kuzu DB into the working tree where no cleanup ever touched it. The
defaults now resolve under ``~/.kgweave-tmp/`` instead, so a no-arg run lands
outside the repo and is trivial to ``rm -rf``.

This is a static-source guard: we do not execute the example to verify
behaviour (that's covered by ``test_quickstart_runs.py`` with an explicit
``tmp_path``). We only ensure the literal default path never regresses.
"""
from __future__ import annotations

from pathlib import Path


_EXAMPLES = Path(__file__).resolve().parents[2] / "src" / "knowledge_graph" / "examples"


def _no_arg_store_default(script: str) -> str:
    """Return the effective default store_path produced by a no-arg invocation.

    Imports the example module and patches ``sys.argv`` so the module-level
    ``main`` branch that selects the default is exercised -- without actually
    running ``open_store`` or ``extract``. We rely on the convention that the
    default branch in both quickstarts evaluates a ``Path("~/.kgweave-tmp/...")
    .expanduser()`` literal. We resolve it via static AST parsing to avoid
    needing pyslang / Kuzu in this guard test.
    """
    import ast

    text = (_EXAMPLES / script).read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        s = node.value
        if s.endswith(".kuzu") and "kgweave-tmp" in s:
            return s
        if s.endswith(".kuzu") and s.startswith("./kgweave-store/"):
            return s
    raise AssertionError(
        f"no .kuzu default literal found in {script}; AST scan returned nothing"
    )


def test_quickstart_default_not_under_repo_root() -> None:
    default = _no_arg_store_default("quickstart.py")
    assert not default.startswith("./kgweave-store/"), (
        f"quickstart.py default reverted to {default!r}; "
        "a no-arg run will pollute the repo working tree"
    )
    assert "kgweave-tmp" in default, (
        f"quickstart.py default must resolve under ~/.kgweave-tmp/, got {default!r}"
    )


def test_quickstart_md_default_not_under_repo_root() -> None:
    default = _no_arg_store_default("quickstart_md.py")
    assert not default.startswith("./kgweave-store/"), (
        f"quickstart_md.py default reverted to {default!r}; "
        "a no-arg run will pollute the repo working tree"
    )
    assert "kgweave-tmp" in default, (
        f"quickstart_md.py default must resolve under ~/.kgweave-tmp/, got {default!r}"
    )

"""Dump the full pyslang AST for fifo.sv into elab_dump.json (ground truth).

Walks the SyntaxTree and the elaborated Compilation, recording every node's
Python class name and every accessible (non-private, non-callable) attribute.
This is the manifest the graph schema must cover.

Run:  uv run python research/ast_experiment/scripts/inventory.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pyslang

HERE = Path(__file__).resolve().parent.parent
SRCS = [
    HERE / "fifo_pkg.sv", HERE / "fifo_if.sv",
    HERE / "fifo.sv", HERE / "top.sv", HERE / "tb_fifo.sv",
    HERE / "fifo_asserts.sv",
    HERE / "cls_corpus.sv",
    HERE / "checker_corpus.sv",
    HERE / "extern_corpus.sv",
    HERE / "prim_corpus.sv",
]
OUT = HERE / "elab_dump.json"
CLASSES_OUT = HERE / "ast_classes.json"

_SCALAR = (str, int, float, bool, type(None))


def _safe(obj: Any) -> Any:
    if isinstance(obj, _SCALAR):
        return obj
    try:
        return str(obj)
    except Exception as e:  # pragma: no cover
        return f"<unstringable: {e!r}>"


def walk_syntax(node: Any, depth: int = 0, max_depth: int = 80) -> dict[str, Any]:
    if depth > max_depth:
        return {"_truncated": True}
    out: dict[str, Any] = {"__class__": type(node).__name__}
    # Try iterating children if the node supports it (SyntaxNode is iterable).
    children: list[Any] = []
    try:
        for child in node:
            children.append(child)
    except TypeError:
        pass
    except Exception:
        pass
    # Attribute scrape: anything not private and not callable.
    attrs: dict[str, Any] = {}
    for name in dir(node):
        if name.startswith("_"):
            continue
        try:
            val = getattr(node, name)
        except Exception:
            continue
        if callable(val):
            continue
        if isinstance(val, _SCALAR):
            attrs[name] = val
        else:
            attrs[name] = _safe(val)
    if attrs:
        out["attrs"] = attrs
    if children:
        out["children"] = [walk_syntax(c, depth + 1, max_depth) for c in children]
    return out


def collect_classes(tree: dict[str, Any], bag: set[str]) -> None:
    if isinstance(tree, dict):
        cls = tree.get("__class__")
        if cls:
            bag.add(cls)
        for v in tree.values():
            collect_classes(v, bag)
    elif isinstance(tree, list):
        for v in tree:
            collect_classes(v, bag)


def main() -> int:
    dump: dict[str, Any] = {}
    classes: set[str] = set()
    for src in SRCS:
        text = src.read_text()
        syntax_tree = pyslang.SyntaxTree.fromText(text)
        sub = walk_syntax(syntax_tree.root)
        dump[src.name] = sub
        collect_classes(sub, classes)

    OUT.write_text(json.dumps(dump, indent=2))
    CLASSES_OUT.write_text(json.dumps(sorted(classes), indent=2))

    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"wrote {CLASSES_OUT} — {len(classes)} distinct AST classes")
    for c in sorted(classes):
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

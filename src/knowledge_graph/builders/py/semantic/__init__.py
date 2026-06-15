"""Python builder semantic layer — empty in v1.

The SV semantic layer (``builders.sv.semantic``) hosts the
pass1/pass2 promote rules that derive cross-file edges. The Python
builder v1 has no semantic post-processing — declarations land in the
graph with structural edges (PARENT_OF) and the Python ↔ MD connector
does the cross-builder reference resolution at run-connectors time.

This package exists so the directory structure mirrors SV; future
slates that add Python semantic rules (e.g. resolving ``from x import
y`` to the target Origin) plug in here.
"""

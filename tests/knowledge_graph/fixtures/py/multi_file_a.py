"""Module A — defines `make_widget` consumed by multi_file_b."""

from __future__ import annotations


def make_widget(name: str) -> dict:
    return {"name": name, "kind": "widget"}


class Widget:
    """Class A — referenced by multi_file_b as ``a.Widget``."""

    pass

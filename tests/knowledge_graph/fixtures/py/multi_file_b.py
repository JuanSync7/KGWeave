"""Module B — imports symbols from multi_file_a."""

from __future__ import annotations

from multi_file_a import Widget, make_widget


def assemble(name: str) -> Widget:
    return Widget()


def widget_factory(name: str) -> dict:
    return make_widget(name)

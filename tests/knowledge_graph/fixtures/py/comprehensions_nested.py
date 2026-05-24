"""Fixture: comprehensions in varying lexical scopes.

Used by v1.7-#2 to assert that the walker attributes each
PyComprehension to its nearest enclosing scope (PyModule,
PyFunction, PyClass, or outer PyComprehension) rather than
unconditionally to the module.
"""
from __future__ import annotations

# Case 1: comprehension at module top level -- parent = PyModule.
TOP = [x * 2 for x in range(3)]


def foo() -> list[int]:
    """Case 2: comprehension inside a function -- parent = PyFunction(foo)."""
    return [x + 1 for x in range(5)]


def outer() -> list[list[int]]:
    """Case 3: nested comprehensions.

    Outer parent = PyFunction(outer); inner parent = the outer
    PyComprehension.
    """
    return [[y for y in range(x)] for x in range(4)]


class Widget:
    """Case 4: comprehension inside a method.

    Parent = PyFunction(method), NOT PyClass(Widget).
    """

    def method(self) -> list[int]:
        return [z * 3 for z in range(2)]

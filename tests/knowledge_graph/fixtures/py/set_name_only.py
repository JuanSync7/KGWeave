"""Fixture: class declaring only ``__set_name__``.

Used by v1.9-#2 set-name-hook connector tests. A class qualifies as a
set-name-hook when it directly declares ``__set_name__`` — the
binding-time protocol hook (PEP 487). No other dunder is required.
"""


class TaggedField:
    def __set_name__(self, owner, name):
        self._name = name

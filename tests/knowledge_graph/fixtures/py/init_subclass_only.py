"""Fixture: class declaring only ``__init_subclass__``.

Used by v1.10-#4 init-subclass-hook connector tests. A class qualifies
as an init-subclass-hook when it directly declares
``__init_subclass__`` — the PEP 487 subclass-creation hook. No other
dunder is required. Inheritance is not chased: only direct
declarations qualify.
"""


class TaggedBase:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._tagged = True

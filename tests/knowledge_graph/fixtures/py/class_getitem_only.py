"""Fixture: class declaring only ``__class_getitem__`` (v1.15-#2).

A class qualifies as a class-getitem-hook when it directly declares
``__class_getitem__`` — the PEP 560 subscription hook
(``Cls[key]`` resolves through this method when present). No other
dunder is required.
"""


class TaggedBase:
    def __class_getitem__(cls, item):
        return cls

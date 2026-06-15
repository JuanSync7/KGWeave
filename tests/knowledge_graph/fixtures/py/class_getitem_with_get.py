"""Fixture: class with both ``__get__`` and ``__class_getitem__`` (v1.15-#2).

Precedence: descriptor protocol (``__get__``) is the more specific
structural role, so this class MUST be tagged
``semantic_role='descriptor'`` and NOT overwritten to
``'class-getitem-hook'``.
"""


class DescriptorWithClassGetitem:
    def __get__(self, instance, owner=None):
        return self._value

    def __class_getitem__(cls, item):
        return cls

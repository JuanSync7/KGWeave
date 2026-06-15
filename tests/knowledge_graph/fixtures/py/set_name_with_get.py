"""Fixture: class with both ``__get__`` and ``__set_name__``.

Used by v1.9-#2 set-name-hook connector tests to validate precedence:
descriptor protocol (``__get__``) is the more specific role, so this
class MUST be tagged ``semantic_role='descriptor'`` and NOT
overwritten to ``'set-name-hook'``.
"""


class DescriptorWithName:
    def __get__(self, instance, owner=None):
        return self._value

    def __set_name__(self, owner, name):
        self._name = name

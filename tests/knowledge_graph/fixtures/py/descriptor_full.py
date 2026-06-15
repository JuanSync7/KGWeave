"""Fixture: full data-descriptor (``__get__`` + ``__set__`` + ``__delete__``).

Used by v1.8-#4 descriptor-protocol connector tests. A class that
implements the full data-descriptor trio is the canonical positive
case for descriptor-role tagging.
"""


class FullDescriptor:
    def __get__(self, instance, owner=None):
        return self._value

    def __set__(self, instance, value):
        self._value = value

    def __delete__(self, instance):
        del self._value

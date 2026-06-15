"""Fixture: minimal descriptor (only ``__get__``).

Used by v1.8-#4 descriptor-protocol connector tests. A class qualifies
as a descriptor when it defines ``__get__`` (the binding method); the
companion ``__set__`` / ``__delete__`` are optional under the protocol.
"""


class ReadOnlyDescriptor:
    def __get__(self, instance, owner=None):
        return 42

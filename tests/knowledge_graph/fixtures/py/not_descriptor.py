"""Fixture: ordinary class with no ``__get__`` method.

Used by v1.8-#4 descriptor-protocol connector tests as a negative
control. Classes that lack ``__get__`` must NOT be tagged as
descriptors, even if they define ``__set__`` / ``__delete__`` /
``__init__`` / other dunder methods.
"""


class Plain:
    def __init__(self, value):
        self._value = value

    def __repr__(self):
        return f"Plain({self._value!r})"


class SetOnly:
    # Has __set__ but no __get__ — not a descriptor.
    def __set__(self, instance, value):
        self._value = value

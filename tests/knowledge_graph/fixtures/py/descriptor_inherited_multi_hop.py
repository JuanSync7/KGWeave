"""Fixture: descriptor inheritance — multi-hop chain.

Used by v1.9-#4 connector tests. ``A`` declares ``__get__``;
``B(A)`` inherits; ``C(B)`` inherits transitively. All three must be
tagged ``semantic_role='descriptor'`` once inheritance chasing
recurses through declared bases.
"""


class A:
    def __get__(self, instance, owner=None):
        return 1


class B(A):
    pass


class C(B):
    pass

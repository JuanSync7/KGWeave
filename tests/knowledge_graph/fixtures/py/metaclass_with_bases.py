"""Fixture: metaclass kwarg combined with positional bases.

Used by v1.8-#4 walker tests: the ``metaclass`` payload must be captured
even when there are other base classes positionally.
"""


class Base:
    pass


class Meta(type):
    pass


class Foo(Base, metaclass=Meta):
    pass

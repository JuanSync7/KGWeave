"""Fixture: plain class with no metaclass kwarg.

Used by v1.8-#4 walker tests: ``PyClass.payload.metaclass`` must be
absent (or ``None``) when the class declares no metaclass keyword.
"""


class Base:
    pass


class Plain(Base):
    pass


class Bare:
    pass

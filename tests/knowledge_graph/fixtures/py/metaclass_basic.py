"""Fixture: basic metaclass declaration.

Used by v1.8-#4 walker tests: ``PyClass.payload.metaclass`` must record
the dotted name of the metaclass keyword argument.
"""


class Meta(type):
    pass


class Foo(metaclass=Meta):
    pass

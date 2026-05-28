"""Metaclass-driven __init_subclass__ hook (v1.14-#2 fixture)."""


class Meta(type):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)


class Klass(metaclass=Meta):
    pass

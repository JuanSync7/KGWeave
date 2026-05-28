"""Metaclass NOT in corpus -> class NOT tagged (v1.14-#2 fixture)."""


class Klass2(metaclass=ExternalMeta):  # ExternalMeta not in corpus  # noqa: F821
    pass

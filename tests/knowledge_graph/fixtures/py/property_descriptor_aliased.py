"""Aliased cached_property descriptor (v1.15-#4 fixture)."""
from functools import cached_property as cp


class Klass:
    @cp
    def value(self):
        return 1

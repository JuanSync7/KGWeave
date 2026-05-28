"""@functools.cached_property descriptor (v1.15-#4 fixture)."""
import functools


class Klass:
    @functools.cached_property
    def value(self):
        return 1

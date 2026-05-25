"""Fixture: descriptor inheritance — single hop.

Used by v1.9-#4 connector tests. Class ``A`` directly declares
``__get__``; class ``B(A)`` inherits it without declaring any methods
of its own. Both must be tagged ``semantic_role='descriptor'`` once
inheritance chasing is wired in.
"""


class A:
    def __get__(self, instance, owner=None):
        return 1


class B(A):
    pass

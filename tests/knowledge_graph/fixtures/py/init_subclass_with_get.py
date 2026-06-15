"""Fixture: class with both ``__get__`` and ``__init_subclass__``.

Used by v1.10-#4 init-subclass-hook connector tests to validate
precedence: descriptor protocol (``__get__``) is the more specific
role, so this class MUST be tagged ``semantic_role='descriptor'`` and
NOT overwritten to ``'init-subclass-hook'``.
"""


class DescriptorWithInitSubclass:
    def __get__(self, instance, owner=None):
        return self._value

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._tagged = True

"""Fixture: ``__init_subclass__`` inheritance — multi-hop chain (v1.11-#4).

Mirrors the v1.9-#4 multi-hop descriptor fixture. ``A`` declares
``__init_subclass__``; ``B(A)`` inherits; ``C(B)`` inherits
transitively. All three must be tagged
``semantic_role='init-subclass-hook'`` once v1.11-#4 enables
inheritance chasing.
"""


class A:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._tagged = True


class B(A):
    pass


class C(B):
    pass

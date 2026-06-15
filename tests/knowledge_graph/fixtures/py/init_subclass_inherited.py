"""Fixture: ``__init_subclass__`` inheritance — single hop (v1.11-#4).

Mirrors the v1.9-#4 descriptor-inheritance fixture pattern. Class
``A`` directly declares ``__init_subclass__``; class ``B(A)`` inherits
it without declaring any methods of its own. Both must be tagged
``semantic_role='init-subclass-hook'`` once v1.11-#4 flips the helper's
``chase_bases`` flag to ``True``.
"""


class A:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._tagged = True


class B(A):
    pass

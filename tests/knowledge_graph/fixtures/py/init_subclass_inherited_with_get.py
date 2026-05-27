"""Fixture: descriptor with INHERITED ``__init_subclass__`` (v1.11-#4 precedence).

``HookBase`` declares ``__init_subclass__``. ``DescriptorChild(HookBase)``
declares ``__get__`` directly (descriptor) and inherits
``__init_subclass__`` via its base. Precedence: descriptor (v1.8-#4)
is the more specific structural role; the v1.11-#4 inheritance-chasing
``__init_subclass__`` connector must NOT overwrite the
already-stamped ``'descriptor'`` role on ``DescriptorChild``.

``HookBase`` itself directly declares ``__init_subclass__`` and is
expected to be tagged ``'init-subclass-hook'``.
"""


class HookBase:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._tagged = True


class DescriptorChild(HookBase):
    def __get__(self, instance, owner=None):
        return 1

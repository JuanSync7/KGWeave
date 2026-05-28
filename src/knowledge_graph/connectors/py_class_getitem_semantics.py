"""``__class_getitem__`` protocol-hook semantic-role tagging for Python
classes (v1.15-#2).

PEP 560 introduced ``__class_getitem__(cls, item)`` as a subscription
hook: when present, ``Cls[key]`` resolves through this classmethod
rather than the metaclass's ``__getitem__``. Any class declaring
``__class_getitem__`` participates in the protocol — as does any
class that inherits it through its declared ``bases`` chain.

This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "class-getitem-hook"``.

Detection rule
--------------
A ``PyClass`` qualifies when any of:

1. At least one of its direct ``PyFunction`` children (via
   ``PARENT_OF``) is named exactly ``__class_getitem__``, OR
2. Any of its in-corpus ancestors along the declared ``bases`` chain
   qualifies under rule 1 (``chase_bases=True``).

Out-of-corpus bases (e.g. ``object``, stdlib) are silently skipped —
no external introspection.

No metaclass pass
-----------------
Unlike ``__init_subclass__`` (v1.14-#2), ``__class_getitem__`` does
*not* resolve through the metaclass. PEP 560 specifies that
``Cls[key]`` looks up ``__class_getitem__`` on the class itself (via
MRO), bypassing the metaclass entirely. So a metaclass declaring
``__class_getitem__`` does *not* expose the hook on instances of that
metaclass — only direct declaration or MRO inheritance counts.

Precedence
----------
``semantic_role`` is a single-valued payload field. Order from
most-specific to least-specific:

1. ``dataclass`` / ``property`` / ``fixture`` (decorator-driven).
2. ``descriptor`` (v1.8-#4) — structural ``__get__`` binding method.
3. ``set-name-hook`` (v1.9-#2) — structural ``__set_name__`` hook.
4. ``init-subclass-hook`` (v1.10-#4) — structural
   ``__init_subclass__`` hook.
5. ``class-getitem-hook`` (this connector) — structural
   ``__class_getitem__`` subscription hook.

The shared helper enforces precedence by skipping any class whose
``semantic_role`` is already populated.

Idempotence
-----------
Re-running on a tagged store re-sets the same role on the same rows
and returns the same "rows touched" count.
"""

from __future__ import annotations

from knowledge_graph.connectors._py_class_tag import tag_pyclass_by_method


_CLASS_GETITEM_METHOD: str = "__class_getitem__"
_ROLE: str = "class-getitem-hook"


class PyClassGetitemSemanticsConnector:
    """Tag ``__class_getitem__``-hook classes with ``semantic_role='class-getitem-hook'``."""

    name: str = "py-class-getitem-semantics"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        # Direct declaration + base chain (no metaclass pass — see
        # module docstring for the PEP 560 rationale).
        return tag_pyclass_by_method(
            store, _CLASS_GETITEM_METHOD, _ROLE, chase_bases=True
        )


__all__ = ["PyClassGetitemSemanticsConnector"]

"""``__set_name__`` protocol-hook semantic-role tagging for Python
classes (v1.9-#2).

PEP 487 introduced ``__set_name__(owner, name)`` as a binding-time
hook: the interpreter calls it on every class attribute that defines
the method, immediately after the owning class is created. The hook is
commonly paired with descriptors but stands on its own — any class
declaring ``__set_name__`` participates in the protocol.

This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "set-name-hook"``.

Detection rule (closed)
-----------------------
A ``PyClass`` qualifies iff at least one of its direct ``PyFunction``
children (via ``PARENT_OF``) is named exactly ``__set_name__``.
Inheritance is NOT chased — mirrors v1.8-#4's closed rule.

Precedence
----------
``semantic_role`` is a single-valued payload field. Order from
most-specific to least-specific:

1. ``dataclass`` / ``property`` / ``fixture`` (decorator-driven,
   v1.7-#4 / v1.8-#1) — *explicit*.
2. ``descriptor`` (v1.8-#4) — structural, the ``__get__`` binding
   method.
3. ``set-name-hook`` (this connector) — structural, the binding-time
   hook. Descriptor wins because ``__set_name__`` commonly accompanies
   ``__get__`` and the descriptor role is the more specific shape.

The shared helper enforces precedence by skipping any class whose
``semantic_role`` is already populated.

Implementation
--------------
v1.11-#2 collapsed the body to a single call into
:func:`knowledge_graph.connectors._py_class_tag.tag_pyclass_by_method`.

Idempotence
-----------
Re-running on a tagged store re-sets the same role on the same rows
and returns the same "rows touched" count.
"""

from __future__ import annotations

from knowledge_graph.connectors._py_class_tag import tag_pyclass_by_method


_SET_NAME_METHOD: str = "__set_name__"
_ROLE: str = "set-name-hook"


class PySetNameSemanticsConnector:
    """Tag ``__set_name__``-hook classes with ``semantic_role='set-name-hook'``."""

    name: str = "py-set-name-semantics"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        return tag_pyclass_by_method(store, _SET_NAME_METHOD, _ROLE)


__all__ = ["PySetNameSemanticsConnector"]

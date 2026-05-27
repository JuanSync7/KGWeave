"""``__init_subclass__`` protocol-hook semantic-role tagging for Python
classes (v1.10-#4).

PEP 487 introduced ``__init_subclass__(cls, **kwargs)`` as a
subclass-creation hook: the interpreter calls it on the parent class
every time a new subclass is created. Any class declaring
``__init_subclass__`` participates in the protocol.

This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "init-subclass-hook"``.

Detection rule (closed)
-----------------------
A ``PyClass`` qualifies iff at least one of its direct ``PyFunction``
children (via ``PARENT_OF``) is named exactly ``__init_subclass__``.
Inheritance is NOT chased — mirrors v1.9-#2's closed rule. The
``chase_bases`` extension is reserved for v1.11-#4.

Precedence
----------
``semantic_role`` is a single-valued payload field. Order from
most-specific to least-specific:

1. ``dataclass`` / ``property`` / ``fixture`` (decorator-driven,
   v1.7-#4 / v1.8-#1) — *explicit*.
2. ``descriptor`` (v1.8-#4) — structural ``__get__`` binding method.
3. ``set-name-hook`` (v1.9-#2) — structural ``__set_name__`` hook.
4. ``init-subclass-hook`` (this connector) — structural
   ``__init_subclass__`` hook. Lower precedence than descriptor /
   set-name-hook because those are more specific structural shapes.

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


_INIT_SUBCLASS_METHOD: str = "__init_subclass__"
_ROLE: str = "init-subclass-hook"


class PyInitSubclassSemanticsConnector:
    """Tag ``__init_subclass__``-hook classes with ``semantic_role='init-subclass-hook'``."""

    name: str = "py-init-subclass-semantics"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        return tag_pyclass_by_method(store, _INIT_SUBCLASS_METHOD, _ROLE)


__all__ = ["PyInitSubclassSemanticsConnector"]

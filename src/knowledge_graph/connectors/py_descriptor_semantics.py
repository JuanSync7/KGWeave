"""Descriptor-protocol semantic-role tagging for Python classes (v1.8-#4).

A *descriptor* is any class whose instances control attribute access
through one or more of the dunder methods ``__get__`` / ``__set__`` /
``__delete__``. Per the data model documented in
:pep:`252` / the Python data model reference, the binding method is
``__get__`` — a class is a descriptor as soon as it defines
``__get__``; the companion ``__set__`` and ``__delete__`` upgrade it
to a *data* descriptor but are not required for the basic protocol.
This connector tags every qualifying ``PyClass`` with
``payload['semantic_role'] = "descriptor"``.

Detection rule (closed)
-----------------------
A ``PyClass`` qualifies iff either:

* at least one of its direct ``PyFunction`` children (via
  ``PARENT_OF``) is named exactly ``__get__``; **or**
* (v1.9-#4) any class reachable by chasing ``payload['bases']``
  recursively — restricted to PyClass rows in the same corpus and
  matched by ``name`` — directly declares ``__get__``.

Bases not present in the corpus (typically ``object`` or stdlib
classes like ``typing.Generic``) are silently skipped — there is no
attempt to introspect external code.

Precedence vs PyDecoratorSemanticsConnector
-------------------------------------------
``semantic_role`` is a single-valued payload field. v1.7-#4 / v1.8-#1
already promote ``@dataclass`` to ``semantic_role='dataclass'`` on
PyClass. A class can in principle be both a ``@dataclass`` and a
descriptor (it defines ``__get__``). We pick **decorator-wins** as the
precedence policy: the decorator is explicit (user-typed) while
descriptor detection is structural (inferred from method shape).
Explicit beats inferred. The shared helper enforces this by skipping
any class whose ``semantic_role`` is already populated.

Implementation
--------------
v1.11-#2 collapsed the body to a single call into
:func:`knowledge_graph.connectors._py_class_tag.tag_pyclass_by_method`,
which centralises the PyClass walk, method indexing, in-corpus base
chasing, and precedence rule shared with the other PyClass tagging
connectors. The wrapper still exists as the public connector entry
point with its stable ``name`` / ``requires`` registration metadata.

Idempotence
-----------
Re-running the connector on a tagged store re-sets the same role on
the same rows and returns the same "rows touched" count.
"""

from __future__ import annotations

from knowledge_graph.connectors._py_class_tag import tag_pyclass_by_method


_DESCRIPTOR_BINDING_METHOD: str = "__get__"
_ROLE: str = "descriptor"


class PyDescriptorSemanticsConnector:
    """Tag descriptor-protocol classes with ``semantic_role='descriptor'``."""

    name: str = "py-descriptor-semantics"
    requires: list[str] = ["py"]

    def synthesize(self, store) -> int:
        return tag_pyclass_by_method(
            store,
            _DESCRIPTOR_BINDING_METHOD,
            _ROLE,
            chase_bases=True,
        )


__all__ = ["PyDescriptorSemanticsConnector"]

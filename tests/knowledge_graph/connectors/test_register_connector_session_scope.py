"""Session-scoped connector registration (v1.5-#5).

The connector registry stores instances by ``connector.name``. Two test
modules registering separate instances of the same connector class trip
:class:`BuilderConflict` because the registry uses identity (``is``) for
its no-op check.

The fix is two-fold and tested below:

1. The shared :func:`_register_sv_md_connector` fixture in this directory's
   ``conftest.py`` is session-scoped, so the registration happens **once**
   per pytest session even when multiple modules declare a dependency.
2. The registry treats a same-name, equal-class re-registration as
   idempotent (a structural equality check, not identity).

The session-scope move is the primary fix; the equality-based no-op is the
belt-and-braces guard for any test that constructs its own instance.
"""

from __future__ import annotations

import pytest

from knowledge_graph import (
    BuilderConflict,
    SvMarkdownReferenceConnector,
    register_connector,
)


def test_register_connector_idempotent_on_equal_instance() -> None:
    """Two separately-constructed instances of the same connector class
    must register as a no-op (not raise :class:`BuilderConflict`).

    This pins the cross-module behaviour: if one module's fixture ran
    before this one and registered its own instance, a fresh instance
    here must not collide.
    """
    a = SvMarkdownReferenceConnector()
    b = SvMarkdownReferenceConnector()
    # Sanity: distinct instances of the same class share the same .name.
    assert a is not b
    assert a.name == b.name
    register_connector(a)
    # The line below previously raised BuilderConflict; under the v1.5-#5
    # fix it must be a no-op.
    register_connector(b)


def test_register_connector_different_class_still_conflicts() -> None:
    """A *different* connector class re-using the same name must still
    raise -- we only relaxed the same-class case."""

    class _FakeConnector:
        name = SvMarkdownReferenceConnector().name
        requires = "sv"

        def run(self, store):  # pragma: no cover - never invoked
            return 0

    # Whether the canonical connector is already in the registry from a
    # previous test or fixture, the FakeConnector under the same name must
    # still raise -- we relaxed same-class only, not same-name.
    try:
        register_connector(SvMarkdownReferenceConnector())
    except BuilderConflict:  # pragma: no cover - state already populated
        pass
    with pytest.raises(BuilderConflict):
        register_connector(_FakeConnector())  # type: ignore[arg-type]

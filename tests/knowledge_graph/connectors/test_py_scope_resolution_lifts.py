"""Direct unit tests for ``_lift_to_module_import`` / ``_lift_to_cross_file`` (v1.13-#2).

These two lift helpers carry the closed-set widening (v1.10-#1 added
``module-import``; v1.10-#3 added star-import expansion feeding into
``cross-file-import``) and the cross-file index lookup. Prior to v1.13
they were exercised only through the end-to-end connector tests.

This module pins their contract at the helper boundary using fabricated
dict-shaped inputs — the helpers' current behaviour is the source of
truth, so these are pinning tests (test-only addition; no behaviour
change).

Helper signatures (read straight from the source):

* ``_lift_to_module_import(name, imports, corpus_modules, consuming_module="") -> (kind, origin_module|None)``
* ``_lift_to_cross_file(name, imports, module_exports, consuming_module="") -> (kind, origin_module|None)``

On a miss, both return ``(KIND_UNRESOLVED, None)`` — the caller
distinguishes hit vs miss by the ``kind`` string.
"""

from __future__ import annotations

from knowledge_graph.connectors.py_scope_resolution import (
    KIND_CROSS_FILE_IMPORT,
    KIND_MODULE_IMPORT,
    KIND_UNRESOLVED,
    _lift_to_cross_file,
    _lift_to_module_import,
)


# ---------------------------------------------------------------------------
# _lift_to_module_import
# ---------------------------------------------------------------------------


class TestLiftToModuleImport:
    """Pin ``_lift_to_module_import`` at the helper boundary."""

    def test_positive_bare_import_target_in_corpus(self) -> None:
        """``import pkg.mod`` with canonical resident in corpus_modules
        returns ``("module-import", canonical)``."""
        imports = {"pkg": "pkg.mod"}
        corpus_modules = {"pkg.mod", "pkg.other"}

        kind, origin = _lift_to_module_import("pkg", imports, corpus_modules)

        assert kind == KIND_MODULE_IMPORT
        assert origin == "pkg.mod"

    def test_positive_single_segment_module(self) -> None:
        """``import a`` shape — canonical ``a`` itself in corpus."""
        imports = {"a": "a"}
        corpus_modules = {"a"}

        kind, origin = _lift_to_module_import("a", imports, corpus_modules)

        assert kind == KIND_MODULE_IMPORT
        assert origin == "a"

    def test_negative_target_out_of_corpus(self) -> None:
        """Canonical not in ``corpus_modules`` — falls through to unresolved."""
        imports = {"ext": "external.lib"}
        corpus_modules = {"pkg.mod"}  # external.lib NOT in here

        kind, origin = _lift_to_module_import("ext", imports, corpus_modules)

        assert kind == KIND_UNRESOLVED
        assert origin is None

    def test_negative_name_not_in_imports(self) -> None:
        """``name`` absent from import table — unresolved."""
        imports = {"other": "pkg.other"}
        corpus_modules = {"pkg.other"}

        kind, origin = _lift_to_module_import("missing", imports, corpus_modules)

        assert kind == KIND_UNRESOLVED
        assert origin is None

    def test_negative_from_import_shape_rejected(self) -> None:
        """``from pkg.mod import leaf`` shape: canonical is ``pkg.mod.leaf``
        which is NOT a module qualname — corpus check rejects it. The
        two-lift architecture keeps module-import / cross-file-import
        disjoint, so this MUST miss here (the caller tries cross-file next).
        """
        imports = {"leaf": "pkg.mod.leaf"}
        corpus_modules = {"pkg.mod"}  # pkg.mod.leaf is a member, NOT a module

        kind, origin = _lift_to_module_import("leaf", imports, corpus_modules)

        assert kind == KIND_UNRESOLVED
        assert origin is None


# ---------------------------------------------------------------------------
# _lift_to_cross_file
# ---------------------------------------------------------------------------


class TestLiftToCrossFile:
    """Pin ``_lift_to_cross_file`` at the helper boundary."""

    def test_positive_from_import_corpus_member(self) -> None:
        """``from pkg.mod import leaf`` where pkg.mod exports leaf —
        returns ``("cross-file-import", "pkg.mod")``."""
        imports = {"leaf": "pkg.mod.leaf"}
        module_exports = {"pkg.mod": {"leaf", "other_sym"}}

        kind, origin = _lift_to_cross_file("leaf", imports, module_exports)

        assert kind == KIND_CROSS_FILE_IMPORT
        assert origin == "pkg.mod"

    def test_negative_origin_module_does_not_export_name(self) -> None:
        """Origin module exists in ``module_exports`` but the leaf is not
        in its export set — unresolved."""
        imports = {"leaf": "pkg.mod.leaf"}
        module_exports = {"pkg.mod": {"other_sym"}}  # ``leaf`` not exported

        kind, origin = _lift_to_cross_file("leaf", imports, module_exports)

        assert kind == KIND_UNRESOLVED
        assert origin is None

    def test_negative_name_not_in_imports(self) -> None:
        """Local name absent from the import table — unresolved."""
        imports = {"other": "pkg.mod.other"}
        module_exports = {"pkg.mod": {"leaf", "other"}}

        kind, origin = _lift_to_cross_file("leaf", imports, module_exports)

        assert kind == KIND_UNRESOLVED
        assert origin is None

    def test_negative_origin_module_absent_from_exports(self) -> None:
        """Origin module not present in ``module_exports`` at all
        (out-of-corpus origin) — unresolved."""
        imports = {"leaf": "external.mod.leaf"}
        module_exports = {"pkg.mod": {"leaf"}}  # external.mod NOT here

        kind, origin = _lift_to_cross_file("leaf", imports, module_exports)

        assert kind == KIND_UNRESOLVED
        assert origin is None

    def test_negative_plain_import_shape_rejected(self) -> None:
        """``import a`` canonical is ``a`` (no dot) — captures the module
        object itself, not a member; cross-file lift MUST decline so the
        two-lift architecture stays disjoint."""
        imports = {"a": "a"}
        module_exports = {"a": {"leaf"}}

        kind, origin = _lift_to_cross_file("a", imports, module_exports)

        assert kind == KIND_UNRESOLVED
        assert origin is None

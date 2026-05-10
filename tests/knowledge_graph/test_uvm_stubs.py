# @summary
# Regression guard for the UVM/dv_utils stub packages in data/sv_stubs/.
# These stubs allow aes_cov_if.sv (and similar OpenTitan DV files) to
# elaborate under slang without a full UVM compile. Tests verify: (1) the
# files exist and contain the expected package declarations, and (2) if
# pyslang is available, that slang parses both stubs without errors.
# @end-summary
"""Tests for UVM stub packages used in OpenTitan DV elaboration."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SV_STUBS_DIR = REPO / "data" / "sv_stubs"
UVM_STUB = SV_STUBS_DIR / "uvm_pkg.sv"
DV_UTILS_STUB = SV_STUBS_DIR / "dv_utils_pkg.sv"


class TestStubFilesExist:
    """Regression: stub files must exist and contain correct declarations."""

    def test_uvm_pkg_stub_exists(self):
        assert UVM_STUB.exists(), (
            f"uvm_pkg.sv stub missing at {UVM_STUB}; "
            "do not delete — slang elaboration of aes_cov_if.sv depends on it"
        )

    def test_dv_utils_pkg_stub_exists(self):
        assert DV_UTILS_STUB.exists(), (
            f"dv_utils_pkg.sv stub missing at {DV_UTILS_STUB}; "
            "do not delete — slang elaboration of aes_cov_if.sv depends on it"
        )

    def test_uvm_pkg_contains_package_declaration(self):
        text = UVM_STUB.read_text()
        assert "package uvm_pkg;" in text, (
            "uvm_pkg.sv must declare 'package uvm_pkg;' — "
            "slang uses it to resolve 'import uvm_pkg::*' in DV files"
        )

    def test_dv_utils_pkg_contains_package_declaration(self):
        text = DV_UTILS_STUB.read_text()
        assert "package dv_utils_pkg;" in text, (
            "dv_utils_pkg.sv must declare 'package dv_utils_pkg;' — "
            "slang uses it to resolve 'import dv_utils_pkg::*' in DV files"
        )


class TestStubsElaborateWithSlang:
    """If pyslang is available, stubs must parse without errors."""

    @pytest.fixture(autouse=True)
    def _require_pyslang(self):
        pytest.importorskip("pyslang", reason="pyslang not installed — skipping slang parse tests")

    def _parse_text(self, text: str) -> None:
        """Parse SV text via pyslang.SyntaxTree.fromText; raise on error."""
        import pyslang  # noqa: PLC0415

        tree = pyslang.SyntaxTree.fromText(text)
        assert tree is not None, "SyntaxTree.fromText returned None"
        # SyntaxTree.diagnostics() surfaces parse errors.
        diags = list(tree.diagnostics)
        errors = [d for d in diags if "error" in str(d).lower()]
        assert not errors, f"Slang reported parse errors: {errors}"

    def test_uvm_pkg_stub_parses(self):
        self._parse_text(UVM_STUB.read_text())

    def test_dv_utils_pkg_stub_parses(self):
        self._parse_text(DV_UTILS_STUB.read_text())

    def test_both_stubs_parse_together(self):
        """Both stubs can be added to a single Compilation without errors."""
        import pyslang  # noqa: PLC0415

        comp = pyslang.Compilation()
        for stub in (UVM_STUB, DV_UTILS_STUB):
            tree = pyslang.SyntaxTree.fromText(stub.read_text())
            comp.addSyntaxTree(tree)
        assert not comp.hasIssuedErrors, (
            "Slang compilation of combined stubs reported errors: "
            f"{list(comp.getAllDiagnostics())}"
        )

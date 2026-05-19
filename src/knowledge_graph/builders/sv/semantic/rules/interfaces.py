"""Interface rules — S11: interface + modport.

Owns the pyslang.SyntaxKind set for SystemVerilog interfaces and modports:

* InterfaceDeclaration
* ModportDeclaration
* ModportItem
* ModportNamedPort
* ModportExplicitPort
* ModportClockingPort
* ModportSubroutinePort
* ModportSimplePortList
* ModportSubroutinePortList

These are pass-1 declarative kinds — the actual walker logic lives in
``dispatch.promote``. The metadata stubs here exist so the registry records
the rule_id under every relevant pyslang SyntaxKind.
"""

from __future__ import annotations

import pyslang


def _s11_modport_explicit_port(*args, **kwargs):
    return


def _s11_modport_clocking_port(*args, **kwargs):
    return


def _s11_modport_subroutine_port(*args, **kwargs):
    return


def _s11_modport_simple_port_list(*args, **kwargs):
    return


def _s11_modport_subroutine_port_list(*args, **kwargs):
    return


def _s11_interface(*args, **kwargs):
    """InterfaceDeclaration — pass 1 (handled by the same module branch)."""
    return


def _s11_modport_decl(*args, **kwargs):
    """ModportDeclaration — pass 1."""
    return


def _s11_modport_item(*args, **kwargs):
    """ModportItem — pass 1."""
    return


def _s11_modport_named_port(*args, **kwargs):
    """ModportNamedPort — pass 1."""
    return


_s11_interface.__rule_id__ = "S11a"
_s11_modport_decl.__rule_id__ = "S11b"
_s11_modport_item.__rule_id__ = "S11b"
_s11_modport_named_port.__rule_id__ = "S11b"
_s11_modport_explicit_port.__rule_id__ = "S11b"
_s11_modport_clocking_port.__rule_id__ = "S11b"
_s11_modport_subroutine_port.__rule_id__ = "S11b"
_s11_modport_simple_port_list.__rule_id__ = "S11b"
_s11_modport_subroutine_port_list.__rule_id__ = "S11b"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.InterfaceDeclaration, _s11_interface),
    (pyslang.SyntaxKind.ModportDeclaration, _s11_modport_decl),
    (pyslang.SyntaxKind.ModportItem, _s11_modport_item),
    (pyslang.SyntaxKind.ModportNamedPort, _s11_modport_named_port),
    (pyslang.SyntaxKind.ModportExplicitPort, _s11_modport_explicit_port),
    (pyslang.SyntaxKind.ModportClockingPort, _s11_modport_clocking_port),
    (pyslang.SyntaxKind.ModportSubroutinePort, _s11_modport_subroutine_port),
    (pyslang.SyntaxKind.ModportSimplePortList, _s11_modport_simple_port_list),
    (pyslang.SyntaxKind.ModportSubroutinePortList, _s11_modport_subroutine_port_list),
]

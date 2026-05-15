"""Structure rules — S1 + S47: module decomposition and time-unit directives.

Owns the pyslang.SyntaxKind set for module/interface/program header structure:

* ModuleDeclaration
* ImplicitAnsiPort
* VariablePortHeader
* ParameterDeclaration
* Declarator

And time-unit directives (S47):

* TimeUnitsDeclaration

These are pass-1 declarative kinds — the actual walker logic lives in
``dispatch.promote``. The metadata stubs here exist so the registry records
the rule_id under every relevant pyslang SyntaxKind.
"""

from __future__ import annotations

import pyslang


def _s1_module_decl(*args, **kwargs):
    """Module/package/interface — promoted in pass 1 of the walker."""
    return


def _s1_port(*args, **kwargs):
    """Port — promoted in pass 1."""
    return


def _s1_param_decl(*args, **kwargs):
    """ParameterDeclaration — pass 1."""
    return


def _s1_variable_port_header(*args, **kwargs):
    """VariablePortHeader — sub-element of ImplicitAnsiPort handled in pass 1."""
    return


def _s1_declarator(*args, **kwargs):
    """Declarator — pass 1 (params/nets/enum-values bind here)."""
    return


def rule_s47(*args, **kwargs):
    """TimeUnitsDeclaration — promoted in pass 2.

    Promotes ``timeunit <lit>;`` and ``timeprecision <lit>;`` statements to
    role=time_units nodes.  Actual implementation lives in dispatch.promote.
    """
    return


_s1_module_decl.__rule_id__ = "S1"
_s1_port.__rule_id__ = "S1"
_s1_param_decl.__rule_id__ = "S1"
_s1_variable_port_header.__rule_id__ = "S1"
_s1_declarator.__rule_id__ = "S1"
rule_s47.__rule_id__ = "S47"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ModuleDeclaration, _s1_module_decl),
    (pyslang.SyntaxKind.ImplicitAnsiPort, _s1_port),
    (pyslang.SyntaxKind.VariablePortHeader, _s1_variable_port_header),
    (pyslang.SyntaxKind.ParameterDeclaration, _s1_param_decl),
    (pyslang.SyntaxKind.Declarator, _s1_declarator),
    (pyslang.SyntaxKind.TimeUnitsDeclaration, rule_s47),
]

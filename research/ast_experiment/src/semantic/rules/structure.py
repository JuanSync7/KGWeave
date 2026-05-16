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


def _s64_explicit_ansi_port(*args, **kwargs):
    """ExplicitAnsiPort — ``.name(expr)`` ANSI port form, promoted in pass 1.

    Sibling of S1 ImplicitAnsiPort. Lives only inside AnsiPortList (under the
    ModuleHeader of a Module / Interface / Program declaration). The leading
    direction token (input/output/inout/ref) is lifted onto the port node as
    the ``direction`` attribute; the connect expression stays a child blob.
    The empty-connect form ``.foo()`` (expr=None) is supported. Actual
    implementation lives in dispatch.promote (pass-1 branch).
    """
    return


def _s55_port_decl(*args, **kwargs):
    """PortDeclaration — non-ANSI port body decls, promoted in pass 1.

    Promotes ``input a;`` / ``output [7:0] b;`` / ``inout wire c;`` etc.
    inside a non-ANSI module body. Each Declarator under the
    PortDeclarationSyntax surfaces as role="port" with the direction attribute
    lifted from the parent Variable/Net/Interface PortHeader. Actual
    implementation lives in dispatch.promote (pass-1 branch).
    """
    return


_s1_module_decl.__rule_id__ = "S1"
_s1_port.__rule_id__ = "S1"
_s1_param_decl.__rule_id__ = "S1"
_s1_variable_port_header.__rule_id__ = "S1"
_s1_declarator.__rule_id__ = "S1"
rule_s47.__rule_id__ = "S47"
_s55_port_decl.__rule_id__ = "S55"
_s64_explicit_ansi_port.__rule_id__ = "S64"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ModuleDeclaration, _s1_module_decl),
    (pyslang.SyntaxKind.ImplicitAnsiPort, _s1_port),
    (pyslang.SyntaxKind.VariablePortHeader, _s1_variable_port_header),
    (pyslang.SyntaxKind.ParameterDeclaration, _s1_param_decl),
    (pyslang.SyntaxKind.Declarator, _s1_declarator),
    (pyslang.SyntaxKind.TimeUnitsDeclaration, rule_s47),
    (pyslang.SyntaxKind.PortDeclaration, _s55_port_decl),
    (pyslang.SyntaxKind.ExplicitAnsiPort, _s64_explicit_ansi_port),
]

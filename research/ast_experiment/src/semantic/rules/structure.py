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


def _s65_explicit_non_ansi_port(*args, **kwargs):
    """ExplicitNonAnsiPort — non-ANSI ``.name(expr)`` header port form.

    Sibling of S1 ImplicitAnsiPort and S64 ExplicitAnsiPort. Lives inside a
    NonAnsiPortList under the ModuleHeader: the header only carries the
    external port name + an optional internal connect expression; direction
    and type arrive separately via PortDeclaration statements in the module
    body (S55). The bare ``.b`` header form is also parsed as
    ExplicitNonAnsiPort with an empty connect expression. Actual
    implementation lives in dispatch.promote (pass-1 branch).
    """
    return


_s65_explicit_non_ansi_port.__rule_id__ = "S65"


def _s66_implicit_non_ansi_port(*args, **kwargs):
    """ImplicitNonAnsiPort — non-ANSI bare-name header port form.

    Sibling of S1 ImplicitAnsiPort, S64 ExplicitAnsiPort, and S65
    ExplicitNonAnsiPort. Lives inside a NonAnsiPortList under the
    ModuleHeader; the header carries only an identifier (or a port
    concatenation), and direction/type arrive via separate PortDeclaration
    statements in the module body (S55). The simple form is
    ``ImplicitNonAnsiPort(expr=PortReference(name=<ident>))`` — promoted as
    role="port" with path ``<module>.<name>``. The PortConcatenation form
    (``{a, b}`` as a header entry) has no single port name to key on and is
    intentionally skipped — a future rule may promote concatenations as a
    distinct artifact. Actual implementation lives in dispatch.promote
    (pass-1 branch).
    """
    return


_s66_implicit_non_ansi_port.__rule_id__ = "S66"


def _s67_port_reference(*args, **kwargs):
    """PortReference — sub-expression inside non-ANSI port lists.

    PortReferenceSyntax appears in three corpus contexts:

    1. As the ``expr`` child of an ``ImplicitNonAnsiPort`` (legacy bare-name
       form ``module m(a, b);``). S66 already promotes the enclosing port at
       path ``<module>.<name>``; S67 attaches role="port_reference" to the
       inner PortReference node using the SAME path (twin view — lesson-5
       flavor: the parent port node remains the canonical role=port, and the
       PortReference is queryable as a separate sub-node for callers who
       want to find the referenced-identifier sub-expression directly).
    2. As the connect expression inside an ``ExplicitNonAnsiPort`` (e.g.
       ``.a(p)``), where it names the internal signal. Path key is
       ``<module>.port_reference.<name>`` so it does not collide with S65's
       external-port node at ``<module>.<name>``.
    3. As an item inside a ``PortConcatenation`` (``{x, y}`` in a non-ANSI
       header — S68 future). Same path-key shape as case 2.

    Actual implementation lives in dispatch.promote (pass-1 branch). Path
    key is keyed off the parent SyntaxKind (`_cls` of the immediate parent
    in the walk stack) so the same PortReferenceSyntax class produces the
    right path key in each context.
    """
    return


_s67_port_reference.__rule_id__ = "S67"


def _s68_port_concatenation(*args, **kwargs):
    """PortConcatenation — ``{a, b}`` curly-grouped port entry in non-ANSI
    port lists.

    Sibling of S66 ImplicitNonAnsiPort: the PortConcatenation appears as the
    ``expr`` child of an ImplicitNonAnsiPortSyntax when the user writes
    ``module m({a, b}, c);``. The concatenation is one external port that
    bundles multiple internal nets (each net surfaces as a PortReference
    member promoted by S67 at ``<module>.port_reference.<name>``). S66
    intentionally skips emission for this expr-shape because there is no
    single port name to key on; S68 fills the gap by promoting the
    PortConcatenationSyntax itself as ``role=port_concat`` with a synthetic
    anonymous path ``<module>.__port_concat_<offset>__`` (per-module
    monotonically-increasing index, matching the S19/S20/S21 convention for
    nameless promotions).

    Edges:
      * ``(module) -[has_port]-> (port_concat)`` — the concat IS one
        external port externally.
      * ``(port_concat) -[groups_port_ref]-> (port_reference)`` — one edge
        per member PortReference. The member PortReferences keep their S67
        promotion (path key unchanged) so they remain queryable both
        directly and via the grouping edge.

    Actual implementation lives in dispatch.promote (pass-1 branch).
    """
    return


_s68_port_concatenation.__rule_id__ = "S68"


RULES: list[tuple] = [
    (pyslang.SyntaxKind.ModuleDeclaration, _s1_module_decl),
    (pyslang.SyntaxKind.ImplicitAnsiPort, _s1_port),
    (pyslang.SyntaxKind.VariablePortHeader, _s1_variable_port_header),
    (pyslang.SyntaxKind.ParameterDeclaration, _s1_param_decl),
    (pyslang.SyntaxKind.Declarator, _s1_declarator),
    (pyslang.SyntaxKind.TimeUnitsDeclaration, rule_s47),
    (pyslang.SyntaxKind.PortDeclaration, _s55_port_decl),
    (pyslang.SyntaxKind.ExplicitAnsiPort, _s64_explicit_ansi_port),
    (pyslang.SyntaxKind.ExplicitNonAnsiPort, _s65_explicit_non_ansi_port),
    (pyslang.SyntaxKind.ImplicitNonAnsiPort, _s66_implicit_non_ansi_port),
    (pyslang.SyntaxKind.PortReference, _s67_port_reference),
    (pyslang.SyntaxKind.PortConcatenation, _s68_port_concatenation),
]

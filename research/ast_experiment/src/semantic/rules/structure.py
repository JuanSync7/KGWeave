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


def _s85_interface_header(*args, **kwargs):
    """S85 — InterfaceHeader ownership-only marker.

    ``SyntaxKind.InterfaceHeader`` is the header portion of an
    ``InterfaceDeclaration`` — the ``interface [lifetime] <name>
    [#(parameter port list)] [(port list)] ;`` clause that precedes the
    interface body. pyslang reuses the single ``ModuleHeaderSyntax``
    Python class across the four header SyntaxKind variants
    (``ModuleHeader`` / ``InterfaceHeader`` / ``PackageHeader`` /
    ``ProgramHeader`` — lesson 1 shared class, discriminator on
    ``node.kind``).

    Semantic content already lifted onto the parent ``InterfaceDeclaration``
    semantic node (which is itself promoted by S1's ModuleDeclarationSyntax
    branch under the ``InterfaceDeclaration`` kind discriminator —
    ``dispatch.promote`` flips ``role="interface"`` and stamps ``name`` /
    ``path`` from the header's name token; parameters land via the
    existing ``ParameterDeclaration`` (S1) branch under the header's
    ``parameters`` subtree; ports land via the existing ``ImplicitAnsiPort``
    / ``ExplicitAnsiPort`` / ``ExplicitNonAnsiPort`` / ``ImplicitNonAnsiPort``
    (S1 / S64 / S65 / S66) branches under the header's ``ports``
    subtree). The ``lifetime`` token is the only header-local field that
    is not already lifted; the live corpus never exercises
    ``interface automatic foo`` / ``interface static foo`` so no
    attribute-lift is wired today — if a future iteration adds a
    lifetime-bearing interface, runtime lifting onto the parent
    interface node can be added without breaking this contract.

    Per ``CLAUDE.md`` lesson 5 (header ownership marker): we register an
    **ownership-only stub** so the Bucket-1 checklist marks
    ``InterfaceHeader`` as ``Sem ✅`` (owner S85) without adding a
    dispatch branch (which would double-promote the interface relative
    to S1's ``InterfaceDeclaration`` branch). Mirrors the S82 / S83
    attribute-only / ownership-only pattern.
    """
    return


_s85_interface_header.__rule_id__ = "S85"


def _s86_interface_port_header(*args, **kwargs):
    """S86 — InterfacePortHeader attribute-augmentation onto the S1 port node.

    ``SyntaxKind.InterfacePortHeader`` is the header form on an ANSI port
    declaration that uses an interface type as the port's data type, e.g.
    ``module m(bus_if.master b);`` — here ``bus_if.master`` is the
    InterfacePortHeader (interface name + optional modport). pyslang shapes
    it as ``InterfacePortHeaderSyntax(nameOrKeyword=<Identifier|InterfaceKeyword>,
    modport=DotMemberClauseSyntax|None)``; the bare ``interface c`` form is
    parsed as ``nameOrKeyword=InterfaceKeyword, modport=None``. When the
    interface name is referenced without a modport (``module m(bus_if c);``),
    pyslang routes the header through ``VariablePortHeaderSyntax`` with a
    NamedType child rather than InterfacePortHeader — the latter only
    appears when there is a modport dot-clause OR the literal ``interface``
    keyword.

    Per ``CLAUDE.md`` lesson 5 flavour (attribute-augmentation rather than a
    new top-level dispatch branch), S86 is implemented inline in S1's
    ``ImplicitAnsiPortSyntax`` dispatch branch: when the port's header is
    InterfacePortHeader the port is promoted with ``role="interface_port"``
    (instead of the default ``role="port"``), and two attributes are lifted
    onto the port semantic node:

    * ``interface_type`` — the interface identifier (``"bus_if"``) or the
      literal ``"interface"`` keyword text for the keyword form.
    * ``modport`` — the modport identifier (``"master"``) when a
      DotMemberClause is present; omitted from ``attributes`` when absent.

    The port name still comes from the sibling DeclaratorSyntax (same as S1).
    Path and ``has_port`` edge are unchanged from S1, so downstream queries
    that traverse ``has_port`` continue to find these ports; queries that
    filter on ``role`` get a distinct ``interface_port`` bucket. Actual
    implementation lives in dispatch.promote (pass-1 ImplicitAnsiPort
    branch). The metadata stub below exists so the registry records the
    rule_id under ``SyntaxKind.InterfacePortHeader``.
    """
    return


_s86_interface_port_header.__rule_id__ = "S86"


def _s87_module_header(*args, **kwargs):
    """S87 — ModuleHeader ownership-only marker.

    ``SyntaxKind.ModuleHeader`` is the header portion of a
    ``ModuleDeclaration`` — the ``module [lifetime] <name>
    [#(parameter port list)] [(port list)] ;`` clause that precedes the
    module body. pyslang reuses the single ``ModuleHeaderSyntax``
    Python class across the four header SyntaxKind variants
    (``ModuleHeader`` / ``InterfaceHeader`` / ``PackageHeader`` /
    ``ProgramHeader`` — lesson 1 shared class, discriminator on
    ``node.kind``). S87 mirrors S85 (InterfaceHeader) one-for-one.

    Semantic content already lifted onto the parent ``ModuleDeclaration``
    semantic node (which is itself promoted by S1's
    ``ModuleDeclarationSyntax`` branch under the ``ModuleDeclaration``
    kind discriminator — ``dispatch.promote`` flips ``role="module"`` and
    stamps ``name`` / ``path`` from the header's name token; parameters
    land via the existing ``ParameterDeclaration`` (S1) branch under the
    header's ``parameters`` subtree; ports land via the existing
    ``ImplicitAnsiPort`` / ``ExplicitAnsiPort`` / ``ExplicitNonAnsiPort`` /
    ``ImplicitNonAnsiPort`` (S1 / S64 / S65 / S66) branches under the
    header's ``ports`` subtree).

    Per ``CLAUDE.md`` lesson 5 (header ownership marker): we register an
    **ownership-only stub** so the Bucket-1 checklist marks
    ``ModuleHeader`` as ``Sem ✅`` (owner S87) without adding a
    dispatch branch (which would double-promote the module relative to
    S1's ``ModuleDeclaration`` branch). Mirrors the S85
    ownership-only pattern.
    """
    return


_s87_module_header.__rule_id__ = "S87"


def _s88_package_header(*args, **kwargs):
    """S88 — PackageHeader ownership-only marker.

    ``SyntaxKind.PackageHeader`` is the header portion of a
    ``PackageDeclaration`` — the ``package [lifetime] <name> ;`` clause
    that precedes the package body. pyslang reuses the single
    ``ModuleHeaderSyntax`` Python class across the four header
    SyntaxKind variants (``ModuleHeader`` / ``InterfaceHeader`` /
    ``PackageHeader`` / ``ProgramHeader`` — lesson 1 shared class,
    discriminator on ``node.kind``). S88 mirrors S85 (InterfaceHeader)
    and S87 (ModuleHeader) one-for-one.

    Semantic content already lifted onto the parent
    ``PackageDeclaration`` semantic node (which is itself promoted by
    S1's ``ModuleDeclarationSyntax`` branch under the
    ``PackageDeclaration`` kind discriminator — ``dispatch.promote``
    flips ``role="package"`` and stamps ``name`` / ``path`` from the
    header's name token). Packages typically have no parameters or
    ports in their header (the grammar still routes through the
    shared ``ModuleHeaderSyntax`` so the parameter/port subtrees are
    structurally present but empty); any parameters that do appear
    land via the existing ``ParameterDeclaration`` (S1) branch.

    Per ``CLAUDE.md`` lesson 5 (header ownership marker): we register an
    **ownership-only stub** so the Bucket-1 checklist marks
    ``PackageHeader`` as ``Sem ✅`` (owner S88) without adding a
    dispatch branch (which would double-promote the package relative
    to S1's ``PackageDeclaration`` branch). Mirrors the S85 / S87
    ownership-only pattern.
    """
    return


_s88_package_header.__rule_id__ = "S88"


def _s89_program_header(*args, **kwargs):
    """S89 — ProgramHeader ownership-only marker.

    ``SyntaxKind.ProgramHeader`` is the header portion of a
    ``ProgramDeclaration`` — the ``program [lifetime] <name>
    [#(parameter port list)] [(port list)] ;`` clause that precedes the
    program body. pyslang reuses the single ``ModuleHeaderSyntax``
    Python class across the four header SyntaxKind variants
    (``ModuleHeader`` / ``InterfaceHeader`` / ``PackageHeader`` /
    ``ProgramHeader`` — lesson 1 shared class, discriminator on
    ``node.kind``). S89 mirrors S85 / S87 / S88 one-for-one.

    Semantic content already lifted onto the parent ``ProgramDeclaration``
    semantic node (which is itself promoted by S1's
    ``ModuleDeclarationSyntax`` branch under the ``ProgramDeclaration``
    kind discriminator — ``dispatch.promote`` flips ``role="program"`` and
    stamps ``name`` / ``path`` from the header's name token; parameters
    land via the existing ``ParameterDeclaration`` (S1) branch under the
    header's ``parameters`` subtree; ports land via the existing
    ``ImplicitAnsiPort`` / ``ExplicitAnsiPort`` / ``ExplicitNonAnsiPort`` /
    ``ImplicitNonAnsiPort`` (S1 / S64 / S65 / S66) branches under the
    header's ``ports`` subtree). Per lesson 2 (subtler container-stack
    variant), programs already push onto ``state["module_stack"]`` at S30
    so the header itself carries no extra parent-resolution state.

    Per ``CLAUDE.md`` lesson 5 (header ownership marker): we register an
    **ownership-only stub** so the Bucket-1 checklist marks
    ``ProgramHeader`` as ``Sem ✅`` (owner S89) without adding a
    dispatch branch (which would double-promote the program relative
    to S1's ``ProgramDeclaration`` branch via S30). Mirrors the
    S85 / S87 / S88 ownership-only pattern.
    """
    return


_s89_program_header.__rule_id__ = "S89"


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
    (pyslang.SyntaxKind.InterfaceHeader, _s85_interface_header),
    (pyslang.SyntaxKind.InterfacePortHeader, _s86_interface_port_header),
    # Header ownership marker per lesson 5; semantic content already lifted
    # onto module nodes by S1. No dispatch branch.
    (pyslang.SyntaxKind.ModuleHeader, _s87_module_header),
    # Header ownership marker per lesson 5; semantic content lifted onto
    # S29 package nodes. No dispatch branch.
    (pyslang.SyntaxKind.PackageHeader, _s88_package_header),
    # Header ownership marker per lesson 5; semantic content lifted onto
    # S30 program nodes. No dispatch branch.
    (pyslang.SyntaxKind.ProgramHeader, _s89_program_header),
]

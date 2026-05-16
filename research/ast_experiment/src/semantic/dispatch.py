"""Dispatch walker — owns the two-pass DFS over the syntax tree and the
``RULE_TABLE``-driven projection.

The walker preserves the legacy guard machinery (``in_generate``, ``in_bind``,
function-body skip) as walker context — these are not the responsibility of
individual rule modules.

Pass 1 (declarative): promote modules / ports / params / nets / typedefs /
functions / modports / packages / interfaces. Builds the cross-file
``semantic_name_index``.

Pass 2 (dispatched): look up the active rule for each node's ``pyslang.kind``
in ``RULE_TABLE`` and invoke it. Rules whose ``__rule_id__`` is in {S1, S9*,
S10, S11*, S6/S7/S12 sub-elements} are no-ops at the dispatch site — their
work is already done in pass 1 or by an enclosing active rule.
"""

from __future__ import annotations

from typing import Any

from .common.graph import _add_edge, _has_edge, _mark
from .common.resolve import _all_module_scopes
from .common.tokens import (
    _CLASS_METHOD_QUALIFIER_KEYWORDS,
    _CLASS_PROPERTY_QUALIFIER_KEYWORDS,
    _CONSTRAINT_QUALIFIER_KEYWORDS,
    _constraint_name_of,
    _assertion_label_of,
    _checker_name_of,
    _checker_instance_name,
    _checker_instantiation_type_name,
    _class_method_name_and_kind,
    _class_modifiers_of,
    _class_name_of,
    _class_property_declarators,
    _class_ref_name_of,  # noqa: F401  (re-export-friendly; used by classes.py)
    _extends_clause_target,
    _implements_clause_targets,
    _clocking_modifier_of,
    _clocking_name_of,
    _cls,
    _qualifier_tokens_of,
    _cover_cross_members,
    _covergroup_has_clocking_event,
    _covergroup_name_of,
    _coverpoint_expression,
    _dpi_export_name_of,
    _dpi_export_spec_and_kind,
    _dpi_import_name_of,
    _dpi_import_spec_and_kind,
    _extern_decl_kind_of,
    _extern_decl_name_of,
    _extern_decl_ports,
    _extern_udp_decl_name_of,
    _extern_udp_decl_ports,
    _forward_typedef_name_of,
    _function_name_of,
    _function_proto_name_and_return,
    _identifier_tokens,
    _is_token,
    _lhs_target_name,
    _module_name_of,
    _named_label_of,
    _package_import_items_of,
    _property_name_of,
    _sequence_name_of,
    _struct_union_body_of,
    _struct_union_members_of,
    _struct_union_modifiers_of,
    _token_kind_name,
    _type_text_of,
    _typedef_name_of,
)
from .rules import RULE_TABLE
from .rules.dataflow import rule_s3_or_s8
from .rules.generate import rule_s12
from .rules.instantiation import rule_s6, rule_s13, rule_s33, rule_s43
from .rules.types import rule_s50, rule_s51, rule_s53


# S16 — concurrent assertion statement SyntaxKind → role kind label. The six
# kinds all surface as ``ConcurrentAssertionStatementSyntax`` instances; their
# ``.kind`` attribute discriminates the variant.
_ASSERTION_KIND_LABELS: dict[str, str] = {
    "AssertPropertyStatement": "assert",
    "AssumePropertyStatement": "assume",
    "CoverPropertyStatement": "cover",
    "CoverSequenceStatement": "cover_sequence",
    "RestrictPropertyStatement": "restrict",
    "ExpectPropertyStatement": "expect",
}


# S17 — immediate assertion statement SyntaxKind → role kind label. The three
# kinds surface as ``ImmediateAssertionStatementSyntax`` instances and live
# inside procedural blocks (the LRM forbids them at module top level except
# as ``ImmediateAssertionMember`` wrappers, which contain the same inner
# statement). The ``_immediate`` suffix differentiates from the S16
# concurrent labels.
_IMMEDIATE_ASSERTION_KIND_LABELS: dict[str, str] = {
    "ImmediateAssertStatement": "assert_immediate",
    "ImmediateAssumeStatement": "assume_immediate",
    "ImmediateCoverStatement": "cover_immediate",
}


def _has_deferred_modifier(node) -> bool:
    """True if ``node`` (an ImmediateAssert* statement) carries a
    ``DeferredAssertion`` child — i.e. it is written as ``assert #0 (...)``
    or ``assert final (...)``.

    Walks direct children only; ``DeferredAssertion`` is always a direct
    child of the immediate-assertion statement when present.
    """
    return _deferred_mode_of(node) is not None


def _deferred_mode_of(node):
    """Return ``"zero"`` for ``assert #0 (...)``, ``"final"`` for
    ``assert final (...)``, or ``None`` for a plain immediate assertion.

    Lesson-5 attribute-augmentation (S72): the ``DeferredAssertion``
    wrapper itself stays CONTAINER, but it carries the only attribute
    distinguishing the two deferral modes — so we lift that attribute
    onto the inner ImmediateAssert* node that S17 promotes. Walks direct
    children only; ``DeferredAssertion`` is always a direct child of the
    immediate-assertion statement when present. Discriminates via the
    structural ``finalKeyword`` / ``zero`` / ``hash`` data descriptors
    on ``DeferredAssertionSyntax`` (no token-text scan, no regex).
    """
    try:
        children = list(node)
    except TypeError:
        return None
    for ch in children:
        if ch is None or _is_token(ch):
            continue
        if _cls(ch) == "DeferredAssertionSyntax":
            # The pyslang data descriptors (``finalKeyword`` / ``hash`` /
            # ``zero``) always return a Token object; an absent token
            # surfaces as a ``Token(TokenKind.Unknown)`` sentinel rather
            # than ``None``. pyslang implements ``__bool__`` on Token so
            # the sentinel is falsy and a real token is truthy —
            # discriminate via plain truthiness rather than ``.kind``
            # (which returns the ``TokenKind.Unknown`` enum, also truthy
            # as an enum value).
            final_tok = getattr(ch, "finalKeyword", None)
            if final_tok:
                return "final"
            return "zero"
    return None


# Active pass-2 rules — these are the only RULE_TABLE entries whose callable
# actually has side effects on the graph. All others are metadata stubs.
_PASS2_ACTIVE: set = set()
# Populated lazily — we resolve by checking the function's __rule_id__ against
# a known-active set.
_ACTIVE_RULE_IDS = {"S2", "S3", "S4", "S5", "S6", "S8", "S12a", "S13", "S33", "S34", "S35", "S36", "S37", "S38", "S39", "S40", "S41", "S42", "S43", "S44", "S45", "S46", "S47", "S48", "S49", "S50", "S51", "S52", "S53", "S54", "S55", "S56", "S57", "S58", "S59", "S60", "S61", "S62", "S63", "S64", "S65", "S66", "S67", "S68", "S69", "S70", "S71", "S72", "S73", "S74", "S75", "S76", "S77", "S78", "S79", "S80", "S81", "S82", "S83"}


def _is_active(fn) -> bool:
    rid = getattr(fn, "__rule_id__", None)
    return rid in _ACTIVE_RULE_IDS


def promote(
    graph: dict[str, Any],
    syntax_tree: Any,
    compilation: Any,
    *,
    node_offset: int | None = None,
    phase: str | None = None,
) -> None:
    """Apply S1..S13 in a single two-pass DFS over the syntax tree."""
    nodes_list = graph["nodes"]
    if node_offset is None:
        node_offset = 0
    name_index: dict[str, str] = graph.setdefault("semantic_name_index", {})
    leaks: list[dict[str, str]] = graph.setdefault("semantic_leaks", [])

    module_scope_by_name: dict[str, Any] = {}
    try:
        for scope in _all_module_scopes(compilation):
            nm = getattr(scope, "name", "") or ""
            if nm and nm not in module_scope_by_name:
                module_scope_by_name[nm] = scope
    except Exception:
        pass

    port_names_by_module: dict[str, set[str]] = {}
    # S16: per-module monotonically-increasing counter for synthetic assertion
    # labels when the source omits ``label:``.
    assertion_counters: dict[str, int] = {}
    # S18: per-module counter for anonymous clocking blocks (rare; the LRM
    # requires an identifier, but synthesize a fallback for robustness).
    clocking_counters: dict[str, int] = {}
    # S19: per-module counter for procedural-assign / procedural-deassign
    # statements (these have no name in source; synthesize a path index).
    proc_assign_counters: dict[str, int] = {}
    # S20: per-module counter for procedural-force / procedural-release
    # statements (also nameless; synthesize a path index).
    proc_force_counters: dict[str, int] = {}
    # S21: per-module counter for named event-trigger statements
    # (-> ev / ->> ev). Nameless in source; synthesize a path index.
    event_trigger_counters: dict[str, int] = {}
    # S22: per-module counter for anonymous covergroups (LRM requires an
    # identifier, but synthesize a fallback for robustness).
    covergroup_counters: dict[str, int] = {}
    # S23: per-covergroup counters for anonymous coverpoints / crosses.
    # Keyed by the covergroup path so unnamed coverpoints inside two
    # different covergroups don't collide on ``coverpoint_0``.
    coverpoint_counters: dict[str, int] = {}
    cross_counters: dict[str, int] = {}
    # S68: per-module counter for anonymous PortConcatenation header entries
    # (``module m({a, b}, c);``). The concat has no source-level name; the
    # counter yields a synthetic ``__port_concat_<offset>__`` suffix that
    # makes the path key unique per module.
    port_concat_counters: dict[str, int] = {}
    # S29: deferred resolution of ``declares`` edges from extern decls to
    # the full module / interface / program declaration. Pass 1 visits in
    # source order; when the extern header precedes the body in the same
    # compilation we can't resolve at the extern's branch (the name index
    # doesn't yet contain the body). Collect (extern_gid, name, kind) and
    # resolve in a post-pass after pass 1 has populated the full index.
    extern_pending: list[tuple[str, str, str]] = []
    # S28 / S79: deferred ``of_checker`` resolution for procedural-scope
    # CheckerInstantiation nodes whose checker declaration is not yet in
    # name_index when the instance fires in pass-1 (the declaration
    # appears textually later in the source, e.g. at compilation-unit
    # scope after the instantiating module). Drained immediately after
    # visit_pass1 completes.
    checker_inst_pending: list[tuple[str, str]] = []
    state = {
        "idx": 0,
        "module_stack": [],
        "typedef_stack": [],
        # S23: covergroup_stack tracks the enclosing CovergroupDeclaration
        # so Coverpoint/CoverCross children can resolve their parent path
        # without a top-down rewalk. Entries are (gid, cgpath) tuples.
        "covergroup_stack": [],
        # S24: class_stack tracks the enclosing ClassDeclaration so future
        # S25 (Extends/Implements) and S26 (ClassMethod/ClassProperty)
        # children can resolve their parent path without a top-down rewalk.
        # Entries are (gid, class_path) tuples.
        "class_stack": [],
        # S41: coverpoint_stack tracks the enclosing Coverpoint (or CoverCross)
        # so CoverageBins children can resolve their parent path and gid without
        # a top-down rewalk. Entries are (gid, cp_path) tuples. Pushed when S23
        # successfully promotes a Coverpoint; popped on exit from that node.
        "coverpoint_stack": [],
        # S28: checker_stack tracks the enclosing CheckerDeclaration so its
        # internal property / sequence / assertion children resolve their
        # parent path against the checker (not against the surrounding
        # module). Entries are (gid, checker_path) tuples. The checker is
        # additionally pushed onto ``module_stack`` while active so the
        # existing S14/S15/S16 promote-against-cur_module logic attaches
        # them to the checker without further changes.
        "checker_stack": [],
        "in_param": 0,
        "in_data": 0,
        # S62: nonzero inside the subtree of a CheckerDataDeclarationSyntax.
        # The DataDeclaration child of that wrapper short-circuits its
        # ``pushed = "in_data"`` push when this is set, so the rand-prefixed
        # declarators don't double-surface as role=net under the checker —
        # they are promoted as role=checker_data by the S62 branch directly.
        "in_checker_data": 0,
        "in_port": 0,
        "in_typedef": 0,
        "in_function": 0,
        # S54: net_decl_stack tracks the enclosing NetDeclarationSyntax group
        # so that child Declarator promotions can emit ``groups_net`` edges
        # back to the group node. Entries are gid strings.
        "net_decl_stack": [],
        # S55: port_decl_stack tracks the enclosing PortDeclarationSyntax
        # (non-ANSI port body) so that child Declarator promotions surface as
        # role="port" with the direction attribute lifted from the parent
        # header (Variable/Net/Interface PortHeader). Entries are
        # ``{"direction": str}`` dicts.
        "port_decl_stack": [],
        # S56: extern_method_stack tracks the enclosing
        # ExternInterfaceMethodSyntax so that the child FunctionPrototypeSyntax
        # branch can emit a role="function_prototype" node + ``prototypes``
        # edge from the enclosing interface scope.  Entries are simple sentinel
        # booleans (we only need presence, not metadata — the FunctionPrototype
        # itself carries the name / return type / port count).  S26 owns
        # ClassMethodPrototype and S44 owns DPIImport — neither of those
        # contexts push this stack, so FunctionPrototype embedded inside them
        # is not double-promoted.
        "extern_method_stack": [],
        # S57: sva_decl_stack tracks the enclosing
        # ``PropertyDeclarationSyntax`` / ``SequenceDeclarationSyntax`` so
        # that LocalVariableDeclaration children promote against the
        # property / sequence as parent (not the module). Entries are
        # ``(parent_gid, parent_path)`` tuples — None gid is used when the
        # property / sequence itself wasn't promoted (e.g. nameless), which
        # makes the LVD branch silently no-op for that subtree.
        "sva_decl_stack": [],
        # S58: struct_union_stack tracks the enclosing typedef whose body is
        # a StructType / UnionType, so that StructUnionMember declarators
        # fan out as queryable role=struct_member / role=union_member nodes
        # attached to the typedef via has_member edges. Entries are
        # ``(typedef_gid, typedef_path, body_kind)`` tuples where body_kind
        # is "struct" or "union" (drives the role name and parent_kind attr).
        # A sentinel ``(None, "", "")`` is pushed when the typedef itself was
        # not promoted, keeping the pop-on-exit symmetric.
        "struct_union_stack": [],
        # S59: clocking_stack tracks the enclosing ClockingDeclaration so
        # that ClockingItem / DefaultSkewItem children can resolve their
        # parent clocking block, fan out per-identifier nodes, and attach
        # has_clocking_item edges. Entries are ``(clk_gid, clk_path)``
        # tuples; a sentinel ``(None, "")`` is pushed when the clocking
        # declaration itself was not promoted, keeping pop-on-exit symmetric.
        "clocking_stack": [],
        # S67: port_ref_parent_stack tracks the enclosing port-shaped
        # container that a PortReferenceSyntax sits inside. Pushed by S65
        # (ExplicitNonAnsiPort), S66 (ImplicitNonAnsiPort), and a future S68
        # (PortConcatenation) branch. Entries are
        # ``(parent_kind, port_path_or_none)`` where ``parent_kind`` is one
        # of ``"implicit_non_ansi"``, ``"explicit_non_ansi"``, or
        # ``"port_concatenation"`` and ``port_path_or_none`` is the path the
        # parent already promoted (S66 case — twin the PortReference at that
        # same path) or None (S65 / concatenation case — emit at
        # ``<module>.port_reference.<name>``).
        "port_ref_parent_stack": [],
        # S68: port_concat_stack tracks the enclosing PortConcatenationSyntax
        # (``{a, b}`` in a non-ANSI port list) so that PortReference children
        # — already promoted by S67 at ``<module>.port_reference.<name>`` —
        # also receive a ``groups_port_ref`` edge from the concat node.
        # Entries are ``concat_gid`` strings (or None when the concat itself
        # was not promoted — kept for symmetric pop). Pushed on entering a
        # PortConcatenationSyntax branch, popped on exit.
        "port_concat_stack": [],
        # S74: function_stack tracks the enclosing function / task / method
        # / extern-prototype scope so that FunctionPort children resolve
        # their parent path and gid without a top-down rewalk. Pushed by
        # FunctionDeclaration (S10/S33-bodied function), ClassMethodDeclaration
        # / ClassMethodPrototype (S26), and FunctionPrototype-when-extern
        # (S56). Entries are ``(parent_gid, parent_path)`` tuples; a
        # sentinel ``(None, "")`` frame is pushed on the un-promoted path so
        # pop-on-subtree-exit stays symmetric. The Subroutine name space
        # (TaskDeclaration without dispatch promotion yet) is not pushed —
        # task ports remain dormant until S10/S33's task-body branch lands.
        "function_stack": [],
    }

    def _cur_module():
        return state["module_stack"][-1] if state["module_stack"] else (None, "")

    def visit_pass1(node):
        idx = state["idx"]
        state["idx"] += 1
        c = _cls(node)
        gid = nodes_list[node_offset + idx]["id"]
        pushed = None
        popped_module = False
        pushed_covergroup = False
        pushed_class = False
        pushed_coverpoint = False
        pushed_struct_union = False
        pushed_clocking = False
        pushed_function = False

        if c == "ModuleDeclarationSyntax":
            kind_name = str(getattr(node, "kind", "")).rsplit(".", 1)[-1]
            mname = _module_name_of(node)
            # Capture the *parent* module-stack entry BEFORE pushing this
            # node; needed by S30 to decide whether to emit a has_program
            # containment edge for a nested program (rare).
            parent_for_program = state["module_stack"][-1] if state["module_stack"] else (None, "")
            state["module_stack"].append((gid, mname))
            popped_module = True
            # S1 / S30 — pyslang reuses ModuleDeclarationSyntax across
            # module / interface / package / program bodies. The dedicated
            # SyntaxKind enum value discriminates, so we dispatch role +
            # containment-edge type here. S30 owns ProgramDeclaration; the
            # program is pushed onto module_stack (above) so child rules
            # (S2/S10/S14/S16/S18/S22/S24...) attach to the program via
            # the standard _cur_module() lookup — same inheritance trick
            # S28 (CheckerDeclaration) uses.
            if kind_name == "PackageDeclaration":
                role_name = "package"
                key_prefix = "package:"
                _mark(nodes_list[node_offset + idx], role=role_name,
                      name=mname, path=mname)
            elif kind_name == "InterfaceDeclaration":
                role_name = "interface"
                key_prefix = "interface:"
                _mark(nodes_list[node_offset + idx], role=role_name,
                      name=mname, path=mname)
            elif kind_name == "ProgramDeclaration":
                # S30 — promote a full ``program ... endprogram`` body. The
                # ``ports`` attribute lists port names extracted from the
                # ProgramHeader child via the same structural scan used by
                # S29 for extern program headers; full port types / dirs
                # stay BLOB. A nested program (rare; LRM-non-conformant in
                # most cases) attaches to its enclosing module via a
                # ``has_program`` edge; cu-scope programs are root-anchored
                # mirroring how S1 handles top-level modules.
                role_name = "program"
                key_prefix = "program:"
                ports = _extern_decl_ports(node)
                _mark(nodes_list[node_offset + idx], role=role_name,
                      name=mname, path=mname,
                      attributes={"ports": list(ports)})
                parent_gid, _parent_mname = parent_for_program
                if parent_gid is not None:
                    _add_edge(graph, parent_gid, gid, "has_program")
            else:
                role_name = "module"
                key_prefix = "module:"
                _mark(nodes_list[node_offset + idx], role=role_name,
                      name=mname, path=mname)
            name_index[key_prefix + mname] = gid
            name_index[mname] = gid
            port_names_by_module.setdefault(mname, set())
        elif c == "AnonymousProgramSyntax":
            # S49 — promote ``program; ... endprogram`` unnamed program blocks
            # (SV §24.4). pyslang uses a dedicated ``AnonymousProgramSyntax``
            # class (no shared-class ambiguity with ModuleDeclarationSyntax).
            #
            # Semantics mirror S30 named programs — the container is
            # module-shaped (holds ports / initial blocks / instances exactly
            # like a module), so we use the lesson-2 subtler variant: push
            # onto ``module_stack``.  Existing S14/S15/S16/S18/S22/S24
            # branches that key on ``_cur_module()`` will automatically attach
            # child declarations to the anonymous program.
            #
            # Path key: ``__anon_program_<offset>__`` where <offset> is the
            # byte offset of the ``program`` keyword token — unique per
            # compilation unit even when multiple anonymous programs appear in
            # the same file.
            #
            # Attribute: ``anonymous=True`` distinguishes this node from S30
            # named programs so downstream queries can filter the two forms.
            kw_tok = getattr(node, "keyword", None)
            kw_offset = 0
            if kw_tok is not None:
                loc = getattr(kw_tok, "location", None)
                if loc is not None:
                    kw_offset = getattr(loc, "offset", 0) or 0
            aname = f"__anon_program_{kw_offset}__"
            _mark(nodes_list[node_offset + idx], role="program",
                  name=aname, path=aname,
                  attributes={"anonymous": True})
            name_index[aname] = gid
            # Push onto module_stack so child items (initial blocks, nets,
            # instances…) resolve _cur_module() to this anonymous program.
            state["module_stack"].append((gid, aname))
            popped_module = True
            # Containment edge: if there is an enclosing module/program on
            # the stack (the entry BEFORE this push), emit ``has_program``
            # mirroring the S30 nested-program handling.  We already popped
            # the parent off the snapshot taken before the push — re-read it
            # from the stack by looking one level below the top.
            if len(state["module_stack"]) >= 2:
                parent_gid_ap, _ = state["module_stack"][-2]
                if parent_gid_ap is not None:
                    _add_edge(graph, parent_gid_ap, gid, "has_program")
        elif c == "ModportItemSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                mport_name = None
                for ch in node:
                    if _is_token(ch) and _token_kind_name(ch) == "Identifier":
                        mport_name = ch.valueText
                        break
                if mport_name is not None:
                    mpath = f"{mname}.{mport_name}"
                    directions: dict[str, str] = {}
                    # Local descendants walk — avoids importing from common
                    # to keep the module slim.
                    def _desc(n):
                        yield n
                        if _is_token(n):
                            return
                        try:
                            kids = list(n)
                        except TypeError:
                            return
                        for x in kids:
                            yield from _desc(x)

                    for d in _desc(node):
                        if _cls(d) != "ModportSimplePortListSyntax":
                            continue
                        dir_tok = None
                        for ch in d:
                            if _is_token(ch) and _token_kind_name(ch) in {
                                "InputKeyword", "OutputKeyword", "InOutKeyword",
                                "RefKeyword",
                            }:
                                dir_tok = ch.valueText
                                break
                        for mnp in _desc(d):
                            if _cls(mnp) != "ModportNamedPortSyntax":
                                continue
                            toks = _identifier_tokens(mnp)
                            if toks and dir_tok is not None:
                                directions[toks[0].valueText] = dir_tok
                    _mark(nodes_list[node_offset + idx], role="modport",
                          name=mport_name, path=mpath, directions=directions)
                    _add_edge(graph, mod_gid, gid, "has_modport")
                    name_index[mpath] = gid
        elif c == "FunctionDeclarationSyntax":
            # S10 promotes a module-scope ``function/task`` as role="function".
            # When the FunctionDeclarationSyntax is the body of a
            # ClassMethodDeclarationSyntax, the class_stack is non-empty and
            # the enclosing S26 branch handles promotion as ``role=method``
            # against the class — skip the module-level promotion here to
            # avoid double-promoting the method under the package as a free
            # function.
            mod_gid, mname = _cur_module()
            # S74: only push a function_stack frame for module-scope
            # functions — class methods are owned by the outer
            # ClassMethodDeclaration branch (already pushed), so the inner
            # FunctionDeclaration would just shadow it with a sentinel
            # frame and hide the method path from FunctionPort children.
            if mod_gid is not None and not state["class_stack"]:
                fname = _function_name_of(node)
                fs_frame: tuple[str | None, str] = (None, "")
                if fname:
                    fpath = f"{mname}.{fname}"
                    _mark(nodes_list[node_offset + idx], role="function",
                          name=fname, path=fpath)
                    _add_edge(graph, mod_gid, gid, "has_function")
                    name_index[fpath] = gid
                    fs_frame = (gid, fpath)
                state["function_stack"].append(fs_frame)
                pushed_function = True
            pushed = "in_function"
        elif c == "PropertyDeclarationSyntax":
            mod_gid, mname = _cur_module()
            push_sva_frame: tuple | None = None
            if mod_gid is not None:
                pname = _property_name_of(node)
                if pname:
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[node_offset + idx], role="property",
                          name=pname, path=ppath)
                    _add_edge(graph, mod_gid, gid, "has_property")
                    name_index[ppath] = gid
                    # S57: expose this property as the enclosing scope for
                    # any LocalVariableDeclaration children. Frame is
                    # popped on subtree exit below.
                    push_sva_frame = (gid, ppath)
            if push_sva_frame is not None:
                state["sva_decl_stack"].append(push_sva_frame)
            else:
                # Push a sentinel frame even when promotion failed so the
                # pop-on-exit below is symmetric and LVD inside an
                # un-promoted property doesn't accidentally inherit an
                # outer sequence/property's scope.
                state["sva_decl_stack"].append((None, ""))
        elif c == "SequenceDeclarationSyntax":
            mod_gid, mname = _cur_module()
            push_sva_frame_s: tuple | None = None
            if mod_gid is not None:
                sname = _sequence_name_of(node)
                if sname:
                    spath = f"{mname}.{sname}"
                    _mark(nodes_list[node_offset + idx], role="sequence",
                          name=sname, path=spath)
                    _add_edge(graph, mod_gid, gid, "has_sequence")
                    name_index[spath] = gid
                    push_sva_frame_s = (gid, spath)
            if push_sva_frame_s is not None:
                state["sva_decl_stack"].append(push_sva_frame_s)
            else:
                state["sva_decl_stack"].append((None, ""))
        elif c == "LocalVariableDeclarationSyntax":
            # S57 — promote SVA-scope local variable declarations that
            # appear inside ``property`` / ``sequence`` bodies. pyslang
            # surfaces these as a dedicated ``LocalVariableDeclarationSyntax``
            # class (not shared with the procedural-scope DataDeclaration —
            # ``int x;`` inside ``initial begin ... end`` is
            # DataDeclarationSyntax instead). Layout (verified via SyntaxTree
            # probe):
            #
            #   SyntaxList                    -- leading attributes
            #   <type_node>                   -- IntType / BitType / LogicType / NamedType …
            #   SeparatedList(DeclaratorSyntax, comma, ...)
            #   Semicolon
            #
            # Parent is the enclosing property / sequence (the
            # ``sva_decl_stack`` top, pushed by the PropertyDeclaration /
            # SequenceDeclaration branches above). Fan-out: a single
            # ``int a, b, c;`` form yields three local_var nodes — the
            # canonical syntax node carries the first declarator and S38-
            # style synthetic sibling nodes carry the rest, so each name is
            # independently queryable via name_index.
            #
            # Token-only structural walk — no regex on source text.
            parent_gid: str | None = None
            parent_path = ""
            if state["sva_decl_stack"]:
                top_gid, top_path = state["sva_decl_stack"][-1]
                parent_gid = top_gid
                parent_path = top_path
            if parent_gid is not None:
                # Identify the type node and the declarator SeparatedList.
                # The first non-token, non-empty-SyntaxList, non-SeparatedList
                # child is the type. The SeparatedList child (recognised via
                # its ``.kind``, since pyslang wraps it as a generic
                # SyntaxNode) holds the comma-separated declarators.
                type_node = None
                decl_list = None
                for ch in node:
                    if ch is None or _is_token(ch):
                        continue
                    sub_kind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if sub_kind == "SyntaxList":
                        continue
                    if sub_kind == "SeparatedList":
                        decl_list = ch
                        continue
                    if type_node is None:
                        type_node = ch
                type_text = _type_text_of(type_node)
                # Collect (name, has_initializer) per Declarator child.
                declarators: list[tuple[str, bool]] = []
                if decl_list is not None:
                    try:
                        kids = list(decl_list)
                    except TypeError:
                        kids = []
                    for d in kids:
                        if d is None or _is_token(d):
                            continue
                        if _cls(d) != "DeclaratorSyntax":
                            continue
                        ids = _identifier_tokens(d)
                        if not ids:
                            continue
                        dname = ids[0].valueText
                        has_init = False
                        for dch in d:
                            if (dch is not None and not _is_token(dch)
                                    and _cls(dch) == "EqualsValueClauseSyntax"):
                                has_init = True
                                break
                        declarators.append((dname, has_init))
                if declarators:
                    first_name, first_init = declarators[0]
                    first_path = f"{parent_path}.{first_name}"
                    _mark(nodes_list[node_offset + idx], role="local_var",
                          name=first_name, path=first_path,
                          attributes={
                              "data_type": type_text,
                              "has_initializer": first_init,
                          })
                    _add_edge(graph, parent_gid, gid, "has_local_var")
                    name_index[first_path] = gid
                    # 2nd+ declarators get synthetic sibling nodes — same
                    # fan-out pattern S38 uses for ``genvar i, j, k;``.
                    for extra_name, extra_init in declarators[1:]:
                        extra_path = f"{parent_path}.{extra_name}"
                        extra_id = f"local_var:{extra_path}"
                        nodes_list.append({
                            "id": extra_id,
                            "type": "LocalVariableDeclarationSyntax",
                            "kind": "LocalVariableDeclaration",
                            "is_token": False,
                            "payload": {"synthetic": True},
                            "queryable": True,
                            "semantic": {
                                "role": "local_var",
                                "name": extra_name,
                                "path": extra_path,
                                "attributes": {
                                    "data_type": type_text,
                                    "has_initializer": extra_init,
                                },
                            },
                        })
                        _add_edge(graph, parent_gid, extra_id, "has_local_var")
                        name_index[extra_path] = extra_id
        elif c == "ConcurrentAssertionStatementSyntax":
            # S16 — promote assert / assume / cover / cover_sequence /
            # restrict / expect property statements as queryable nodes under
            # the enclosing module. Parent is the nearest module on the
            # module_stack (so assertions nested inside procedural blocks
            # still attach to the module, not the block).
            mod_gid, mname = _cur_module()
            kind_name = str(getattr(node, "kind", "")).rsplit(".", 1)[-1]
            kind_label = _ASSERTION_KIND_LABELS.get(kind_name)
            if mod_gid is not None and kind_label is not None:
                label = _assertion_label_of(node)
                if not label:
                    n_seen = assertion_counters.get(mname, 0)
                    label = f"{kind_label}_{n_seen}"
                    assertion_counters[mname] = n_seen + 1
                apath = f"{mname}.{label}"
                _mark(nodes_list[node_offset + idx], role="assertion",
                      name=label, path=apath,
                      attributes={"kind": kind_label})
                _add_edge(graph, mod_gid, gid, "has_assertion")
                name_index[apath] = gid
        elif c == "ImmediateAssertionStatementSyntax":
            # S17 — promote immediate assert / assume / cover statements as
            # queryable nodes under the enclosing module. Per LRM these live
            # inside procedural contexts (always / initial / final / function
            # / task) or wrapped by ImmediateAssertionMember at module scope;
            # in both cases we walk up to the nearest module on the stack.
            # Detect deferred (#0 or ``final``) by the presence of a
            # ``DeferredAssertionSyntax`` direct child — no regex on source.
            mod_gid, mname = _cur_module()
            kind_name = str(getattr(node, "kind", "")).rsplit(".", 1)[-1]
            kind_label = _IMMEDIATE_ASSERTION_KIND_LABELS.get(kind_name)
            if mod_gid is not None and kind_label is not None:
                label = _assertion_label_of(node)
                if not label:
                    n_seen = assertion_counters.get(mname, 0)
                    label = f"{kind_label}_{n_seen}"
                    assertion_counters[mname] = n_seen + 1
                apath = f"{mname}.{label}"
                # S17: ``deferred`` is the legacy boolean. S72 augments it
                # with ``defer_mode`` ("zero" for ``assert #0``, "final" for
                # ``assert final``) lifted off the DeferredAssertion wrapper
                # — the wrapper itself stays CONTAINER per lesson 5, but its
                # discriminating attribute rides onto the inner promoted
                # node. Plain immediate asserts have no ``defer_mode`` key.
                defer_mode = _deferred_mode_of(node)
                attrs = {"kind": kind_label, "deferred": defer_mode is not None}
                if defer_mode is not None:
                    attrs["defer_mode"] = defer_mode
                _mark(nodes_list[node_offset + idx], role="assertion",
                      name=label, path=apath,
                      attributes=attrs)
                _add_edge(graph, mod_gid, gid, "has_assertion")
                name_index[apath] = gid
        elif c == "MemberAccessExpressionSyntax":
            # S73 — ``obj.field`` member access. Edge-only per lesson 4: emit
            # a ``member_access`` edge from the closest enclosing queryable
            # container (class method via class_stack, else module/interface/
            # package/program/checker via module_stack) to a synthesized
            # ``<base>.<member>`` id. When the base resolves to a known entry
            # in ``semantic_name_index`` the edge points at that node and
            # carries ``payload["unresolved"]=False``; otherwise the dst is a
            # sentinel ``_unresolved.<base>.<member>`` and
            # ``payload["unresolved"]=True`` (mirrors the S25 / S32
            # unresolved-target convention).
            #
            # Reachability caveat: pyslang's *syntax* tree parses
            # ``obj.field`` as ``ScopedNameSyntax`` (Identifier Dot
            # Identifier), not as ``MemberAccessExpressionSyntax``. The
            # latter is a kind in the post-elaboration bound-expression tree,
            # which this dispatch walker does not currently traverse. The
            # branch is therefore dormant against the present corpus — kept
            # here so the future bound-tree lift drops in cleanly.
            src_gid: str | None = None
            if state["class_stack"]:
                src_gid = state["class_stack"][-1][0]
            elif state["module_stack"]:
                src_gid = state["module_stack"][-1][0]
            if src_gid is not None:
                left = getattr(node, "left", None)
                name_tok = getattr(node, "name", None)
                left_text = (str(left).strip() if left is not None else "") or ""
                member = ""
                if name_tok is not None:
                    member = (getattr(name_tok, "valueText", None)
                              or str(name_tok).strip()
                              or "")
                if member:
                    base_path = left_text
                    resolved_gid = name_index.get(base_path)
                    if resolved_gid is not None:
                        dst = resolved_gid
                        unresolved = False
                    else:
                        dst = f"_unresolved.{base_path}.{member}"
                        unresolved = True
                    _add_edge(
                        graph, src_gid, dst, "member_access",
                        base=base_path, member=member, unresolved=unresolved,
                    )
        elif c == "ClockingDeclarationSyntax":
            # S18 — promote ``clocking ... endclocking`` blocks (including
            # ``default clocking`` and ``global clocking`` forms) as queryable
            # nodes under the enclosing module/interface. Clocking items
            # (input/output direction declarations for signals) stay BLOB.
            # Detect ``default``/``global`` modifiers structurally via the
            # leading keyword token — no regex.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                cname = _clocking_name_of(node)
                if not cname:
                    n_seen = clocking_counters.get(mname, 0)
                    cname = f"clocking_{n_seen}"
                    clocking_counters[mname] = n_seen + 1
                cpath = f"{mname}.{cname}"
                modifier = _clocking_modifier_of(node)
                attrs = {
                    "default": modifier == "default",
                    "global": modifier == "global",
                }
                _mark(nodes_list[node_offset + idx], role="clocking",
                      name=cname, path=cpath, attributes=attrs)
                _add_edge(graph, mod_gid, gid, "has_clocking")
                name_index[cpath] = gid
                # S59: push the clocking block onto clocking_stack so that
                # ClockingItem / DefaultSkewItem children visited inside this
                # subtree resolve their parent clocking. Matched by the
                # pop-on-exit at the end of visit_pass1.
                state["clocking_stack"].append((gid, cpath))
                pushed_clocking = True
            else:
                # Unpromoted clocking (no enclosing module) — push a sentinel
                # so ClockingItem children silently skip without leaking the
                # stack frame.
                state["clocking_stack"].append((None, ""))
                pushed_clocking = True
        elif c == "ClockingItemSyntax":
            # S59 — fan out each direction-item identifier inside a clocking
            # block as its own role=clocking_item node. Parent clocking gid +
            # path ride on ``clocking_stack`` (pushed by the
            # ClockingDeclaration branch above). Structurally:
            #
            #   ClockingItemSyntax
            #     ClockingDirectionSyntax
            #       (InputKeyword | OutputKeyword | InOutKeyword)
            #       [ClockingSkewSyntax]          # optional
            #     SeparatedListSyntax
            #       AttributeSpecSyntax | DeclaratorSyntax (one per name)
            #
            # pyslang surfaces the per-signal items inside the SeparatedList
            # as AttributeSpec nodes (oddly named, but each carries one
            # leading Identifier token — the signal name). No regex.
            if state["clocking_stack"]:
                clk_gid, clk_path = state["clocking_stack"][-1]
            else:
                clk_gid, clk_path = None, ""
            if clk_gid is not None:
                direction = ""
                skew_text: str | None = None
                names: list[str] = []
                for ch in node:
                    if ch is None or _is_token(ch):
                        continue
                    sub_kind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if sub_kind == "ClockingDirection":
                        for sub in ch:
                            if sub is None:
                                continue
                            if _is_token(sub):
                                tk = _token_kind_name(sub)
                                if tk in ("InputKeyword", "OutputKeyword",
                                          "InOutKeyword"):
                                    direction = tk.replace(
                                        "Keyword", ""
                                    ).lower()
                                    if direction == "inout":
                                        direction = "inout"
                                continue
                            sub_k = str(
                                getattr(sub, "kind", "")
                            ).rsplit(".", 1)[-1]
                            if sub_k == "ClockingSkew":
                                skew_text = _type_text_of(sub)
                    elif sub_kind == "SeparatedList":
                        for d in ch:
                            if d is None or _is_token(d):
                                continue
                            ids = _identifier_tokens(d)
                            if ids:
                                names.append(ids[0].valueText)
                if names and direction:
                    first_name = names[0]
                    first_path = f"{clk_path}.{first_name}"
                    item_attrs = {
                        "direction": direction,
                        "skew": skew_text,
                    }
                    _mark(nodes_list[node_offset + idx], role="clocking_item",
                          name=first_name, path=first_path,
                          attributes=item_attrs)
                    _add_edge(graph, clk_gid, gid, "has_clocking_item")
                    name_index[first_path] = gid
                    # Multi-identifier fan-out (S38/S58-style synthetic
                    # siblings): each additional name gets its own
                    # queryable node with a stable synthetic id.
                    for extra_name in names[1:]:
                        extra_path = f"{clk_path}.{extra_name}"
                        extra_id = f"clocking_item:{extra_path}"
                        nodes_list.append({
                            "id": extra_id,
                            "type": "ClockingItemSyntax",
                            "kind": "ClockingItem",
                            "is_token": False,
                            "payload": {"synthetic": True},
                            "queryable": True,
                            "semantic": {
                                "role": "clocking_item",
                                "name": extra_name,
                                "path": extra_path,
                                "attributes": {
                                    "direction": direction,
                                    "skew": skew_text,
                                },
                            },
                        })
                        _add_edge(graph, clk_gid, extra_id,
                                  "has_clocking_item")
                        name_index[extra_path] = extra_id
        elif c == "DefaultSkewItemSyntax":
            # S59 — promote ``default input <skew> output <skew>;`` (and the
            # one-direction variants) as a single role=clocking_item node
            # under the enclosing clocking block. Path key
            # ``<clocking>.__default__`` (LRM allows one per clocking block).
            #
            # Structure:
            #   DefaultSkewItemSyntax
            #     DefaultKeyword
            #     ClockingDirectionSyntax
            #       [InputKeyword ClockingSkew]
            #       [OutputKeyword ClockingSkew]
            #     Semicolon
            #
            # Scan the ClockingDirection's direct children in document order;
            # the most-recent keyword token associates the following
            # ClockingSkew node as its skew. No regex.
            if state["clocking_stack"]:
                clk_gid, clk_path = state["clocking_stack"][-1]
            else:
                clk_gid, clk_path = None, ""
            if clk_gid is not None:
                input_skew: str | None = None
                output_skew: str | None = None
                for ch in node:
                    if ch is None or _is_token(ch):
                        continue
                    sub_kind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if sub_kind != "ClockingDirection":
                        continue
                    current_dir: str | None = None
                    for sub in ch:
                        if sub is None:
                            continue
                        if _is_token(sub):
                            tk = _token_kind_name(sub)
                            if tk == "InputKeyword":
                                current_dir = "input"
                            elif tk == "OutputKeyword":
                                current_dir = "output"
                            continue
                        sub_k = str(
                            getattr(sub, "kind", "")
                        ).rsplit(".", 1)[-1]
                        if sub_k == "ClockingSkew" and current_dir:
                            text = _type_text_of(sub)
                            if current_dir == "input":
                                input_skew = text
                            else:
                                output_skew = text
                dpath = f"{clk_path}.__default__"
                _mark(nodes_list[node_offset + idx], role="clocking_item",
                      name="__default__", path=dpath,
                      attributes={
                          "direction": "default",
                          "input_skew": input_skew,
                          "output_skew": output_skew,
                      })
                _add_edge(graph, clk_gid, gid, "has_clocking_item")
                name_index[dpath] = gid
        elif c == "DefaultDisableDeclarationSyntax":
            # S39 — promote ``default disable iff <expr>;`` as a queryable
            # node under the enclosing module / interface / checker / program.
            # The LRM allows at most one default disable declaration per scope;
            # we use the fixed path key ``<scope>.__default_disable__`` to
            # make this invariant queryable without collision.
            #
            # The disable expression is the child node that follows the
            # ``IffKeyword`` token — structurally a ParenthesizedExpression
            # (or any valid expr). We walk all descendant identifier tokens to
            # emit ``reads`` edges so downstream consumers can trace signal
            # dependencies without pattern-matching source text. No regex.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                dd_name = "__default_disable__"
                dd_path = f"{mname}.{dd_name}"
                _mark(nodes_list[node_offset + idx], role="default_disable",
                      name=dd_name, path=dd_path)
                _add_edge(graph, mod_gid, gid, "has_default_disable")
                name_index[dd_path] = gid
                # Emit reads edges for all identifier tokens in the disable
                # expression. Walk the full subtree below this node and
                # collect every Identifier token; resolve each against the
                # name index (qualified then bare) and emit reads edges.
                def _collect_ids(n):
                    if _is_token(n):
                        if _token_kind_name(n) == "Identifier":
                            yield n
                        return
                    try:
                        kids = list(n)
                    except TypeError:
                        return
                    for ch in kids:
                        if ch is not None:
                            yield from _collect_ids(ch)

                for id_tok in _collect_ids(node):
                    sig_name = id_tok.valueText
                    tgt_id = name_index.get(f"{mname}.{sig_name}")
                    if tgt_id is None:
                        tgt_id = name_index.get(sig_name)
                    if tgt_id is not None and tgt_id != gid:
                        if not _has_edge(graph, gid, tgt_id, "reads"):
                            _add_edge(graph, gid, tgt_id, "reads",
                                      name=sig_name)
        elif c == "DefaultClockingReferenceSyntax":
            # S40 — ``default clocking <name>;`` selects which named clocking
            # block is the implicit default for the enclosing scope.
            # Edge-only kind: no independent identity — purely a pointer.
            # Emit a ``default_clocking`` edge from the enclosing module /
            # interface / checker / program to the resolved clocking block.
            # Resolve the target via name_index; fall back to
            # ``_unresolved.<name>`` if the clocking block is not yet indexed
            # (forward reference or external scope — lesson 4 of CLAUDE.md).
            # The Identifier token carrying the clocking block name is the
            # direct child that follows the ``ClockingKeyword`` token —
            # detected structurally, no regex.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                ref_name = ""
                saw_clocking_kw = False
                for ch in node:
                    if _is_token(ch):
                        tk = _token_kind_name(ch)
                        if tk == "ClockingKeyword":
                            saw_clocking_kw = True
                            continue
                        if saw_clocking_kw and tk == "Identifier":
                            ref_name = ch.valueText
                            break
                if ref_name:
                    tgt_gid = name_index.get(f"{mname}.{ref_name}")
                    if tgt_gid is None:
                        tgt_gid = name_index.get(ref_name)
                    if tgt_gid is None:
                        tgt_gid = f"_unresolved.{ref_name}"
                    _add_edge(graph, mod_gid, tgt_gid, "default_clocking",
                              name=ref_name)
        elif c in ("ProceduralAssignStatementSyntax",
                   "ProceduralDeassignStatementSyntax"):
            # S19/S20 — promote procedural-continuous-drive statements that
            # appear inside procedural blocks (always / initial). These are
            # distinct from S2's module-level ContinuousAssign — they override
            # / release procedural drivers (S19: assign/deassign; S20:
            # force/release — stronger, overrides continuous drivers too).
            #
            # pyslang surfaces both pairs with the same syntax class — the
            # variant is discriminated by ``.kind`` only:
            #
            #   class=ProceduralAssignStatementSyntax    kind={Assign,Force}
            #   class=ProceduralDeassignStatementSyntax  kind={Deassign,Release}
            #
            # Parent is the nearest enclosing module (NOT the always block).
            # The LHS target is extracted structurally via
            # ``_lhs_target_name`` (first Identifier token under the
            # statement) — no regex on source text. If the LHS resolves to a
            # known net via the shared name index, emit an optional
            # ``drives`` edge; otherwise skip silently.
            mod_gid, mname = _cur_module()
            kind_name = str(getattr(node, "kind", "")).rsplit(".", 1)[-1]
            _PROC_DRIVE_VARIANTS = {
                "ProceduralAssignStatement": (
                    "procedural_assign", "proc_assign", "has_procedural_assign",
                    proc_assign_counters,
                ),
                "ProceduralDeassignStatement": (
                    "procedural_deassign", "proc_assign", "has_procedural_assign",
                    proc_assign_counters,
                ),
                "ProceduralForceStatement": (
                    "procedural_force", "proc_force", "has_procedural_force",
                    proc_force_counters,
                ),
                "ProceduralReleaseStatement": (
                    "procedural_release", "proc_force", "has_procedural_force",
                    proc_force_counters,
                ),
            }
            variant = _PROC_DRIVE_VARIANTS.get(kind_name)
            if mod_gid is not None and variant is not None:
                role_label, name_prefix, edge_type, counters = variant
                n_seen = counters.get(mname, 0)
                proc_name = f"{name_prefix}_{n_seen}"
                counters[mname] = n_seen + 1
                ppath = f"{mname}.{proc_name}"
                lhs_name = _lhs_target_name(node) or ""
                _mark(nodes_list[node_offset + idx], role=role_label,
                      name=proc_name, path=ppath,
                      attributes={"lhs": lhs_name})
                _add_edge(graph, mod_gid, gid, edge_type)
                name_index[ppath] = gid
                # Optional drives edge — only if the LHS resolves to an
                # existing semantic node in the shared name index. We try
                # the qualified path first (mname.lhs), then the bare name
                # (cross-scope fallback). If neither resolves, skip.
                if lhs_name:
                    tgt_id = name_index.get(f"{mname}.{lhs_name}")
                    if tgt_id is None:
                        tgt_id = name_index.get(lhs_name)
                    if tgt_id is not None and tgt_id != gid:
                        _add_edge(graph, gid, tgt_id, "drives")
        elif c == "EventTriggerStatementSyntax":
            # S21 — promote named event-trigger statements that appear inside
            # procedural blocks:
            #
            #   -> ev;    → BlockingEventTriggerStatement
            #   ->> ev;   → NonblockingEventTriggerStatement
            #
            # pyslang surfaces both variants with a single shared syntax class
            # ``EventTriggerStatementSyntax`` — only ``.kind`` discriminates.
            # Parent is the nearest enclosing module/interface/program (NOT the
            # always block). The event identifier is extracted structurally via
            # the first Identifier token under the statement (the ``-> ev``
            # grammar guarantees the only Identifier child is the event name).
            # If the name resolves via the shared name index we emit an
            # optional ``triggers`` edge to the corresponding event-typed
            # declaration; otherwise we skip silently.
            mod_gid, mname = _cur_module()
            kind_name = str(getattr(node, "kind", "")).rsplit(".", 1)[-1]
            _EVENT_TRIGGER_VARIANTS = {
                "BlockingEventTriggerStatement": True,
                "NonblockingEventTriggerStatement": False,
            }
            blocking = _EVENT_TRIGGER_VARIANTS.get(kind_name)
            if mod_gid is not None and blocking is not None:
                n_seen = event_trigger_counters.get(mname, 0)
                tname = f"trigger_{n_seen}"
                event_trigger_counters[mname] = n_seen + 1
                tpath = f"{mname}.{tname}"
                ev_name = _lhs_target_name(node) or ""
                _mark(nodes_list[node_offset + idx], role="event_trigger",
                      name=tname, path=tpath,
                      attributes={"blocking": blocking,
                                  "event_name": ev_name})
                _add_edge(graph, mod_gid, gid, "has_event_trigger")
                name_index[tpath] = gid
                # Optional triggers edge — resolve event_name against the
                # name index. Try qualified path first, then bare name.
                if ev_name:
                    tgt_id = name_index.get(f"{mname}.{ev_name}")
                    if tgt_id is None:
                        tgt_id = name_index.get(ev_name)
                    if tgt_id is not None and tgt_id != gid:
                        _add_edge(graph, gid, tgt_id, "triggers")
        elif c == "CovergroupDeclarationSyntax":
            # S22 — promote ``covergroup ... endgroup`` blocks as queryable
            # nodes under the enclosing module/interface/class. Coverpoint and
            # CoverCross sub-elements stay BLOB for S22; S23 will promote
            # them. The clocking-event clause (``@(posedge clk)``) is
            # surfaced as a single boolean attribute — the actual event
            # details live in the BLOB form. Detect the event structurally
            # by walking direct children for an EventControl* node; no regex.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                cgname = _covergroup_name_of(node)
                if not cgname:
                    n_seen = covergroup_counters.get(mname, 0)
                    cgname = f"covergroup_{n_seen}"
                    covergroup_counters[mname] = n_seen + 1
                cgpath = f"{mname}.{cgname}"
                has_event = _covergroup_has_clocking_event(node)
                _mark(nodes_list[node_offset + idx], role="covergroup",
                      name=cgname, path=cgpath,
                      attributes={"clocking_event": has_event})
                _add_edge(graph, mod_gid, gid, "has_covergroup")
                name_index[cgpath] = gid
                state["covergroup_stack"].append((gid, cgpath))
                pushed_covergroup = True
        elif c == "CoverpointSyntax":
            # S23 — promote ``[label:] coverpoint <expr> ...;`` items inside
            # a covergroup body. Parent is the enclosing covergroup (NOT the
            # module); the covergroup_stack maintained alongside module_stack
            # supplies the parent gid + hierarchical path without a top-down
            # rewalk. If the walk somehow reaches a Coverpoint outside any
            # covergroup, fall back to the module and record a leak so the
            # corpus can flag it. The expression text is extracted only for
            # the simple ``coverpoint <identifier>;`` case; richer
            # expressions (concatenations, ranges, with-clauses) stay BLOB
            # via ``expr_blob=True`` so we don't dump arbitrary token text.
            mod_gid, mname = _cur_module()
            if state["covergroup_stack"]:
                cg_gid, cgpath = state["covergroup_stack"][-1]
                parent_gid = cg_gid
                parent_path = cgpath
                edge_type = "has_coverpoint"
            elif mod_gid is not None:
                parent_gid = mod_gid
                parent_path = mname
                edge_type = "has_coverpoint"
                leaks.append({
                    "rule": "S23",
                    "kind": "CoverpointSyntax",
                    "reason": "coverpoint outside covergroup; fell back to module",
                    "path": mname,
                })
            else:
                parent_gid = None
                parent_path = ""
                edge_type = "has_coverpoint"
            if parent_gid is not None:
                cp_name = _named_label_of(node)
                if not cp_name:
                    key = parent_path
                    n_seen = coverpoint_counters.get(key, 0)
                    cp_name = f"coverpoint_{n_seen}"
                    coverpoint_counters[key] = n_seen + 1
                cp_path = f"{parent_path}.{cp_name}"
                expr_text, expr_blob = _coverpoint_expression(node)
                attrs: dict[str, Any] = {}
                if expr_blob:
                    attrs["expr_blob"] = True
                else:
                    attrs["expr_text"] = expr_text
                _mark(nodes_list[node_offset + idx], role="coverpoint",
                      name=cp_name, path=cp_path, attributes=attrs)
                _add_edge(graph, parent_gid, gid, edge_type)
                name_index[cp_path] = gid
                # S41: push coverpoint_stack so CoverageBins children can
                # resolve their parent without a top-down rewalk.
                state["coverpoint_stack"].append((gid, cp_path))
                pushed_coverpoint = True
        elif c == "CoverCrossSyntax":
            # S23 — promote ``[label:] cross <cp_a>, <cp_b> ...;`` items.
            # Same parent-resolution policy as CoverpointSyntax above; the
            # ``members`` attribute is the ordered list of coverpoint names
            # referenced by the cross (extracted from the SeparatedList of
            # IdentifierName children that follow the ``CrossKeyword``).
            mod_gid, mname = _cur_module()
            if state["covergroup_stack"]:
                cg_gid, cgpath = state["covergroup_stack"][-1]
                parent_gid = cg_gid
                parent_path = cgpath
            elif mod_gid is not None:
                parent_gid = mod_gid
                parent_path = mname
                leaks.append({
                    "rule": "S23",
                    "kind": "CoverCrossSyntax",
                    "reason": "cross outside covergroup; fell back to module",
                    "path": mname,
                })
            else:
                parent_gid = None
                parent_path = ""
            if parent_gid is not None:
                cx_name = _named_label_of(node)
                if not cx_name:
                    key = parent_path
                    n_seen = cross_counters.get(key, 0)
                    cx_name = f"cross_{n_seen}"
                    cross_counters[key] = n_seen + 1
                cx_path = f"{parent_path}.{cx_name}"
                members = _cover_cross_members(node)
                _mark(nodes_list[node_offset + idx], role="cross",
                      name=cx_name, path=cx_path,
                      attributes={"members": members})
                _add_edge(graph, parent_gid, gid, "has_cross")
                name_index[cx_path] = gid
        elif c == "CoverageBinsSyntax":
            # S41 — promote ``bins <name> = {...};`` / ``bins <name>[] = ...;``
            # / ``illegal_bins <name> = ...;`` / ``ignore_bins <name> = ...;``
            # declarations inside a coverpoint body. Parent is the enclosing
            # Coverpoint (coverpoint_stack top). If somehow reached outside any
            # coverpoint, silently skip — the LRM forbids this and the corpus
            # won't synthesise it.
            #
            # bins_kind is discriminated by the leading keyword token's kind:
            #   BinsKeyword       → "bins"
            #   IllegalBinsKeyword → "illegal_bins"
            #   IgnoreBinsKeyword  → "ignore_bins"
            # The identifier (bins name) is the token immediately following the
            # keyword. array_form is detected by the presence of a
            # CoverageBinsArraySizeSyntax child.
            if state["coverpoint_stack"]:
                cp_gid, cp_path = state["coverpoint_stack"][-1]
                # Extract leading keyword and bins name from direct children.
                bins_keyword = ""
                bins_name = ""
                has_array_form = False
                expect_name = False
                for ch in node:
                    if _is_token(ch):
                        tkind = _token_kind_name(ch)
                        if tkind in {"BinsKeyword", "IllegalBinsKeyword", "IgnoreBinsKeyword"}:
                            bins_keyword = ch.valueText  # "bins", "illegal_bins", "ignore_bins"
                            expect_name = True
                        elif expect_name and tkind == "Identifier":
                            bins_name = ch.valueText
                            expect_name = False
                    elif _cls(ch) == "CoverageBinsArraySizeSyntax":
                        has_array_form = True
                if bins_name:
                    bins_path = f"{cp_path}.{bins_name}"
                    attrs: dict = {"bins_kind": bins_keyword}
                    if has_array_form:
                        attrs["array_form"] = True
                    _mark(nodes_list[node_offset + idx], role="coverage_bins",
                          name=bins_name, path=bins_path, attributes=attrs)
                    _add_edge(graph, cp_gid, gid, "has_bins")
                    name_index[bins_path] = gid
        elif c == "ClassDeclarationSyntax":
            # S24 — promote ``[virtual|interface] [final] class <name>
            # [#(params)] [extends ...] [implements ...] ; <items> endclass``
            # as a queryable node. Parent is the enclosing module / package /
            # interface (the ``module_stack`` top). Compilation-unit-scope
            # classes (no enclosing scope) become root-anchored: path is the
            # bare class name and no containment edge is emitted, mirroring
            # how top-level modules / packages are handled by S1.
            #
            # Modifiers (virtual / interface_class / final / parameterized)
            # are detected structurally via direct-child Token / SyntaxNode
            # scanning — no regex on source text. Class body (members,
            # methods, properties, extends/implements clauses) stays BLOB
            # at S24; S25 and S26 will promote those sub-elements.
            #
            # ``class_stack`` is pushed unconditionally so S25/S26 children
            # can resolve their enclosing class without a top-down rewalk,
            # even for cu-scope classes that have no module parent.
            cname = _class_name_of(node)
            if cname:
                mod_gid, mname = _cur_module()
                if mod_gid is not None:
                    cpath = f"{mname}.{cname}"
                else:
                    cpath = cname
                attrs = _class_modifiers_of(node)
                # S25 — scan the ClassDeclarationSyntax's direct children for
                # ExtendsClauseSyntax (at most one, per LRM) and
                # ImplementsClauseSyntax (at most one, holding a
                # comma-separated list of interface-class refs). Capture the
                # parent / interface names structurally so we can both stamp
                # them as attributes here and emit the cross-cut
                # ``extends`` / ``implements`` edges below. Edge target
                # resolution uses the shared semantic_name_index: try the
                # qualified ``<owner>.<ref>`` path first, then the bare ref
                # for cross-scope visibility, then fall back to a synthetic
                # placeholder ``_unresolved.<ref>`` with payload
                # ``unresolved=True`` so downstream queries can still see the
                # edge even when the target is a forward / external ref.
                extends_name = ""
                extends_params = False
                implements_names: list[str] = []
                for cch in node:
                    if _is_token(cch):
                        continue
                    cch_cls = _cls(cch)
                    if cch_cls == "ExtendsClauseSyntax":
                        en, ep = _extends_clause_target(cch)
                        if en:
                            extends_name = en
                            extends_params = ep
                    elif cch_cls == "ImplementsClauseSyntax":
                        implements_names = _implements_clause_targets(cch)
                if extends_name:
                    attrs["extends_name"] = extends_name
                if implements_names:
                    attrs["implements_names"] = list(implements_names)
                _mark(nodes_list[node_offset + idx], role="class",
                      name=cname, path=cpath, attributes=attrs)
                if mod_gid is not None:
                    _add_edge(graph, mod_gid, gid, "has_class")
                name_index[cpath] = gid

                def _resolve_class_ref(ref: str) -> tuple[str, bool]:
                    """Return (target_gid, unresolved) for a class/interface
                    name reference. Qualified path first, bare name fallback,
                    then synthesize ``_unresolved.<ref>``."""
                    tid = None
                    if mod_gid is not None:
                        tid = name_index.get(f"{mname}.{ref}")
                    if tid is None:
                        tid = name_index.get(ref)
                    if tid is not None and tid != gid:
                        return tid, False
                    return f"_unresolved.{ref}", True

                if extends_name:
                    tgt, unresolved = _resolve_class_ref(extends_name)
                    payload: dict[str, Any] = {
                        "params": "overrides" if extends_params else None,
                        "name": extends_name,
                    }
                    if unresolved:
                        payload["unresolved"] = True
                    _add_edge(graph, gid, tgt, "extends", **payload)
                for iref in implements_names:
                    tgt, unresolved = _resolve_class_ref(iref)
                    payload = {"name": iref}
                    if unresolved:
                        payload["unresolved"] = True
                    _add_edge(graph, gid, tgt, "implements", **payload)

                state["class_stack"].append((gid, cpath))
                pushed_class = True
        elif c in ("ClassMethodDeclarationSyntax",
                   "ClassMethodPrototypeSyntax"):
            # S26 — promote class methods (function/task bodies inside a
            # class) and method prototypes (pure-virtual / extern declarations
            # surfaced as ClassMethodPrototypeSyntax). Parent is the
            # enclosing class (``class_stack`` top); fall back to a silent
            # skip if somehow reached outside a class.
            #
            # Modifiers (``virtual``/``pure``/``extern``/``static``/
            # ``protected``/``local``) are detected structurally by walking
            # the direct-child TokenList. The method name and return type
            # come from the inner FunctionPrototypeSyntax — the helper
            # disambiguates constructor (``new``) / task / function and
            # extracts the return-type text only for functions.
            # S74: push a function_stack frame (sentinel by default, real
            # when promotion succeeds) so FunctionPort children of the
            # method body / prototype attach to the method.
            cm_frame: tuple[str | None, str] = (None, "")
            if state["class_stack"]:
                cls_gid, cls_path = state["class_stack"][-1]
                name, kind_label, return_type = _class_method_name_and_kind(node)
                if name:
                    is_prototype = (c == "ClassMethodPrototypeSyntax")
                    quals = _qualifier_tokens_of(node, _CLASS_METHOD_QUALIFIER_KEYWORDS)
                    pure_virtual = quals["pure"] and quals["virtual"]
                    attrs: dict[str, Any] = {
                        "kind": "prototype" if is_prototype else kind_label,
                        "static": quals["static"],
                        "virtual": quals["virtual"],
                        "pure_virtual": pure_virtual,
                        "extern": quals["extern"],
                        "protected": quals["protected"],
                        "local": quals["local"],
                        "return_type": return_type,
                        "prototype": is_prototype,
                    }
                    mpath = f"{cls_path}.{name}"
                    role_label = "method_prototype" if is_prototype else "method"
                    _mark(nodes_list[node_offset + idx], role=role_label,
                          name=name, path=mpath, attributes=attrs)
                    _add_edge(graph, cls_gid, gid, "has_method")
                    name_index[mpath] = gid
                    cm_frame = (gid, mpath)
            state["function_stack"].append(cm_frame)
            pushed_function = True
        elif c == "ClassPropertyDeclarationSyntax":
            # S26 — promote class data members. The declaration may carry
            # multiple comma-separated declarators (``int a, b, c;``); we
            # emit one ``class_property`` node per declarator. Parent is the
            # enclosing class (``class_stack`` top).
            #
            # We attach the role marker + has_class_property edge to the
            # outermost ClassPropertyDeclarationSyntax (one node per
            # declaration), and ALSO emit a separate marker on each inner
            # DeclaratorSyntax — but the canonical promoted node is the
            # ClassPropertyDeclaration itself (one per source declaration).
            #
            # Declarator fan-out rule: when the SeparatedList contains more
            # than one DeclaratorSyntax, the ClassPropertyDeclaration node
            # itself carries the FIRST declarator's name; the remaining
            # declarators are stamped on their own DeclaratorSyntax nodes
            # below via a deferred re-promotion in the Declarator branch.
            # We use a per-declaration "declarator_names" attribute to
            # surface the full list to consumers.
            if state["class_stack"]:
                cls_gid, cls_path = state["class_stack"][-1]
                quals = _qualifier_tokens_of(node, _CLASS_PROPERTY_QUALIFIER_KEYWORDS)
                declarators = _class_property_declarators(node)
                names: list[str] = []
                for d in declarators:
                    ids = _identifier_tokens(d)
                    if ids:
                        names.append(ids[0].valueText)
                # Stash the declarator metadata on the per-declaration node
                # so DeclaratorSyntax children can emit per-name property
                # nodes when they are visited next.
                state["class_property_pending"] = {
                    "cls_gid": cls_gid,
                    "cls_path": cls_path,
                    "quals": quals,
                    "decl_gid": gid,
                    "names": set(names),
                }
                if names:
                    first = names[0]
                    attrs = {
                        "static": quals["static"],
                        "const": quals["const"],
                        "rand": quals["rand"],
                        "randc": quals["randc"],
                        "protected": quals["protected"],
                        "local": quals["local"],
                        "declarator_names": list(names),
                    }
                    ppath = f"{cls_path}.{first}"
                    _mark(nodes_list[node_offset + idx], role="class_property",
                          name=first, path=ppath, attributes=attrs)
                    _add_edge(graph, cls_gid, gid, "has_class_property")
                    name_index[ppath] = gid
        elif c in ("ConstraintDeclarationSyntax",
                   "ConstraintPrototypeSyntax"):
            # S27 — promote class constraint blocks (with body) and constraint
            # prototypes (``extern constraint c_name;`` / ``pure constraint
            # c_name;``). Parent is the enclosing class (``class_stack``
            # top); fall back to a silent skip if reached outside any class.
            #
            # Qualifier keywords (``static`` / ``pure`` / ``extern``) live in
            # a TokenList direct child before the ``ConstraintKeyword`` —
            # ``_qualifier_tokens_of`` walks both loose tokens and one level
            # into the TokenList wrapper to detect them structurally. No
            # regex on source text. The constraint body (ConstraintBlock and
            # its ExpressionConstraint / ImplicationConstraint /
            # SolveBeforeConstraint / DistConstraintList / etc. children)
            # stays BLOB — only the declaration-level node is promoted.
            if state["class_stack"]:
                cls_gid, cls_path = state["class_stack"][-1]
                cname = _constraint_name_of(node)
                if cname:
                    is_prototype = (c == "ConstraintPrototypeSyntax")
                    quals = _qualifier_tokens_of(
                        node, _CONSTRAINT_QUALIFIER_KEYWORDS)
                    cpath = f"{cls_path}.{cname}"
                    attrs = {
                        "static": quals["static"],
                        "pure": quals["pure"],
                        "extern": quals["extern"],
                        "prototype": is_prototype,
                    }
                    _mark(nodes_list[node_offset + idx], role="constraint",
                          name=cname, path=cpath, attributes=attrs)
                    _add_edge(graph, cls_gid, gid, "has_constraint")
                    name_index[cpath] = gid
        elif c == "ConstraintBlockSyntax":
            # S52 — promote a ``ConstraintBlock`` that appears as the inline
            # constraint argument to ``obj.randomize() with { <expr>; ... }``.
            #
            # A ConstraintBlock appears in two structural positions:
            #   1. As the body child of ConstraintDeclaration / ConstraintPrototype
            #      (S27 already covers the parent; the block itself stays BLOB).
            #   2. Directly inside ArrayOrRandomizeMethodExpression — the ``with
            #      { ... }`` inline form (SV §18.12).  This second form has no
            #      named declaration wrapping it and is independently queryable.
            #
            # We discriminate via the pyslang ``.parent`` attribute (available on
            # all SyntaxNode objects).  Only form 2 gets promoted.
            #
            # Path: ``<scope>.__inline_constraint_<offset>__`` where <offset> is
            # the byte offset of the opening brace token — unique per
            # compilation unit even when multiple inline constraints appear in
            # the same file.  The name is the same synthetic key.
            #
            # Edge: ``has_inline_constraint`` from the enclosing module / class /
            # package (whichever is on the ``module_stack`` top, mirroring how
            # S28/S29 attach checker-scope items).
            parent_node = getattr(node, "parent", None)
            parent_cls = _cls(parent_node) if parent_node is not None else ""
            if parent_cls == "ArrayOrRandomizeMethodExpressionSyntax":
                mod_gid, mname = _cur_module()
                if mod_gid is not None:
                    # Byte offset of the ``{`` token for a stable unique key.
                    try:
                        open_tok = node.getFirstToken()
                        loc = getattr(open_tok, "location", None)
                        cb_offset = getattr(loc, "offset", 0) or 0
                    except Exception:
                        cb_offset = 0
                    cb_name = f"__inline_constraint_{cb_offset}__"
                    cb_path = f"{mname}.{cb_name}"
                    _mark(nodes_list[node_offset + idx],
                          role="inline_constraint_block",
                          name=cb_name, path=cb_path)
                    _add_edge(graph, mod_gid, gid, "has_inline_constraint")
                    name_index[cb_path] = gid
        elif c == "CheckerDeclarationSyntax":
            # S28 — promote ``checker <name> [(ports)]; <items> endchecker``
            # as a queryable node. Parent is the enclosing module / package /
            # interface (the ``module_stack`` top). Compilation-unit-scope
            # checkers (no enclosing scope) become root-anchored: path is the
            # bare checker name and no containment edge is emitted, mirroring
            # how cu-scope classes are handled by S24.
            #
            # ``checker_stack`` is pushed for symmetry with class_stack /
            # covergroup_stack so future S-rules can resolve the enclosing
            # checker without a top-down rewalk. The checker is ALSO pushed
            # onto ``module_stack`` while active so the existing S14
            # (Property), S15 (Sequence), S16 (ConcurrentAssertion), and S18
            # (Clocking) pass-1 branches — which all key off ``_cur_module()``
            # — attach property / sequence / assertion / clocking children
            # to the checker by hierarchical path, e.g. ``c_mutex.p_mutex``.
            chk_name = _checker_name_of(node)
            if chk_name:
                mod_gid, mname = _cur_module()
                if mod_gid is not None:
                    cpath = f"{mname}.{chk_name}"
                else:
                    cpath = chk_name
                _mark(nodes_list[node_offset + idx], role="checker",
                      name=chk_name, path=cpath)
                if mod_gid is not None:
                    _add_edge(graph, mod_gid, gid, "has_checker")
                # Register both the qualified path and a ``checker:<name>``
                # key so S6 in pass-2 can distinguish checker types from
                # module / interface types when resolving an instantiation.
                name_index[cpath] = gid
                name_index["checker:" + chk_name] = gid
                state["checker_stack"].append((gid, cpath))
                # Push as a synthetic module-scope so child SVA / clocking
                # items attach with the checker as parent.
                state["module_stack"].append((gid, cpath))
                popped_module = True
        elif c == "CheckerInstantiationSyntax":
            # S28 — promote a checker instantiation that surfaces with its own
            # dedicated SyntaxKind (the procedural-context form, wrapped by
            # CheckerInstanceStatementSyntax). The module-body form parses as
            # a HierarchyInstantiationSyntax and is reclassified by rule_s6 in
            # pass-2 against the checker name index.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                ctype = _checker_instantiation_type_name(node)
                iname = _checker_instance_name(node)
                if iname and ctype:
                    ipath = f"{mname}.{iname}"
                    _mark(nodes_list[node_offset + idx], role="checker_instance",
                          name=iname, path=ipath,
                          attributes={"checker_name": ctype})
                    _add_edge(graph, mod_gid, gid, "has_checker_instance")
                    name_index[ipath] = gid
                    # Optional of_checker edge — resolve against the
                    # checker-prefixed name-index entry registered by the
                    # CheckerDeclaration branch. Try in-line first; if the
                    # checker declaration appears textually AFTER the
                    # instantiation (legal: checkers may be declared at
                    # compilation-unit scope below the instantiating
                    # module), defer to the pass-1 post-pass which runs
                    # after the full name_index is populated.
                    tgt = name_index.get("checker:" + ctype)
                    if tgt is not None and tgt != gid:
                        _add_edge(graph, gid, tgt, "of_checker",
                                  name=ctype)
                    else:
                        checker_inst_pending.append((gid, ctype))
        elif c == "ExternModuleDeclSyntax":
            # S29 — promote ``extern module|interface|program <name> [#(...)]
            # [(ports)] ;`` headers. pyslang reuses the single SyntaxKind
            # ``ExternModuleDecl`` and the single class ``ExternModuleDeclSyntax``
            # for all three forms; the discriminator is ``header.kind``
            # (ModuleHeader / InterfaceHeader / ProgramHeader). Read it via
            # ``_extern_decl_kind_of`` and stamp it as the ``kind`` attribute.
            #
            # Parent resolution mirrors S24 (ClassDeclaration) and S28
            # (CheckerDeclaration): if there is an enclosing module-stack
            # entry, attach via ``has_extern_decl``; otherwise the decl is
            # compilation-unit-scoped and we root-anchor it with the bare
            # name as the path and no containment edge.
            #
            # We do NOT push the extern decl onto module_stack — its body is
            # only a header (no nested items), so there's nothing to attach
            # to it. Port declarators under the header land in the existing
            # DeclaratorSyntax / ImplicitAnsiPortSyntax branches; at cu-scope
            # those branches no-op (no module_gid), and at nested scope they
            # would attach to the enclosing module which is the wrong
            # semantics — but extern decls inside another module are
            # vanishingly rare and LRM-non-conformant in most cases. The
            # ``ports`` attribute carries the port-name list extracted
            # structurally via ``_extern_decl_ports`` so consumers don't need
            # to descend into the header subtree.
            ext_name = _extern_decl_name_of(node)
            if ext_name:
                ext_kind = _extern_decl_kind_of(node)
                ports = _extern_decl_ports(node)
                mod_gid, mname = _cur_module()
                if mod_gid is not None:
                    epath = f"{mname}.{ext_name}"
                else:
                    epath = ext_name
                _mark(nodes_list[node_offset + idx], role="extern_decl",
                      name=ext_name, path=epath,
                      attributes={"kind": ext_kind, "ports": list(ports)})
                if mod_gid is not None:
                    _add_edge(graph, mod_gid, gid, "has_extern_decl")
                name_index[epath] = gid
                # Optional ``declares`` edge: defer to a post-pass — the
                # extern header typically precedes the full body in source
                # order, so the name index does not yet contain the body
                # gid at this point. ``extern_pending`` is drained after
                # visit_pass1 completes (see below).
                extern_pending.append((gid, ext_name, ext_kind))
        elif c == "ExternUdpDeclSyntax":
            # S81 — promote ``extern primitive <name> ( <udp_ports> ) ;``
            # headers. pyslang surfaces this as the dedicated SyntaxKind
            # ``ExternUdpDecl`` (one class, one kind — no sharing). The
            # extern primitive prototype is the structural+semantic peer
            # of S29's extern module/interface/program: it declares the
            # contract (name + port list) without supplying the UDP body
            # (which lives in a ``primitive ... endprimitive`` block
            # elsewhere, and which the elaborator treats as out-of-scope
            # for most analyses — but the prototype itself is a first-class
            # declaration we can query against).
            #
            # Parent resolution mirrors S29 / S24 / S28: if an enclosing
            # module-stack entry exists, attach via ``has_extern_udp_decl``;
            # otherwise the decl is compilation-unit-scoped and we
            # root-anchor it with the bare name as the path and no
            # containment edge.
            #
            # We do NOT push the extern UDP decl onto module_stack — the
            # body is a header only, so there are no nested members to
            # attribute to it. Port names are extracted structurally via
            # ``_extern_udp_decl_ports`` so consumers don't need to descend
            # into either of the two UDP-port-list variants
            # (``AnsiUdpPortList`` / ``NonAnsiUdpPortList``).
            ext_name = _extern_udp_decl_name_of(node)
            if ext_name:
                ports = _extern_udp_decl_ports(node)
                mod_gid, mname = _cur_module()
                if mod_gid is not None:
                    epath = f"{mname}.{ext_name}"
                else:
                    epath = ext_name
                _mark(nodes_list[node_offset + idx], role="extern_udp",
                      name=ext_name, path=epath,
                      attributes={"ports": list(ports)})
                if mod_gid is not None:
                    _add_edge(graph, mod_gid, gid, "has_extern_udp_decl")
                name_index[epath] = gid
        elif c == "DPIImportSyntax":
            # S44 — promote ``import "DPI-C" function|task <name> (...);``
            # declarations as queryable nodes under the enclosing module or
            # package.  DPI imports are declaration-like (they introduce a
            # callable into the current scope) but carry no body — they are
            # extern-style in spirit.  Unlike extern module/interface (S29),
            # DPI imports are always nested inside a module or package (LRM
            # §35.5.1 forbids them at the compilation-unit level); so we
            # always attach to the current module_stack top.
            #
            # Attributes extracted structurally — no regex on source text:
            #   spec        — string-literal value stripped of quotes
            #                 ("DPI-C" or "DPI")
            #   import_kind — "function" or "task" from the FunctionKeyword /
            #                 TaskKeyword token inside FunctionPrototypeSyntax
            #
            # Name index: registers ``<scope>.<function_name>`` so callers
            # can resolve a DPI-imported function the same way they resolve
            # module-defined functions.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                fn_name = _dpi_import_name_of(node)
                if fn_name:
                    spec, import_kind = _dpi_import_spec_and_kind(node)
                    dpath = f"{mname}.{fn_name}"
                    _mark(nodes_list[node_offset + idx], role="dpi_import",
                          name=fn_name, path=dpath,
                          attributes={"spec": spec,
                                      "import_kind": import_kind})
                    _add_edge(graph, mod_gid, gid, "has_dpi_import")
                    name_index[dpath] = gid
        elif c == "DPIExportSyntax":
            # S45 — edge-only: ``export "DPI-C" function|task <name> ;``
            # A DPI export has no independent identity — it is a pointer-like
            # directive that marks an existing SV function/task as callable
            # from C.  Representation: a ``dpi_exports`` edge from the
            # enclosing module/package to the target function node.
            #
            # Target resolution via name_index (``<scope>.<fn_name>``).  If
            # the target is not present (forward-declared, or a different
            # compilation unit), emit the edge with
            # ``dst="_unresolved.<name>"`` and ``payload["unresolved"]=True``.
            #
            # Attributes:
            #   spec        — DPI spec string, quotes stripped ("DPI-C"/"DPI")
            #   export_kind — "function" or "task"
            #
            # No new node is created; node["semantic"] is left as-is (this
            # stays BLOB in the Bucket-1 sense — no role is stamped on the
            # DPIExportSyntax node itself).
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                exp_name = _dpi_export_name_of(node)
                if exp_name:
                    spec, export_kind = _dpi_export_spec_and_kind(node)
                    target_path = f"{mname}.{exp_name}"
                    target_gid = name_index.get(target_path)
                    if target_gid is not None:
                        _add_edge(graph, mod_gid, target_gid, "dpi_exports",
                                  spec=spec, export_kind=export_kind)
                    else:
                        _add_edge(graph, mod_gid,
                                  f"_unresolved.{exp_name}", "dpi_exports",
                                  spec=spec, export_kind=export_kind,
                                  unresolved=True)
        elif c == "NetAliasSyntax":
            # S46 — edge-only: ``alias a = b = c;`` (SV §10.11)
            # A net alias declares bidirectional equivalence between nets; it
            # has no independent identity.  Representation: consecutive-pairs
            # ``aliases`` edges between each adjacent identifier pair in the
            # alias chain, each pair bidirectional (a→b, b→a, b→c, c→b for a
            # three-name chain).  Full-product (a↔c) is NOT emitted — callers
            # that need transitivity should close over the relation.
            #
            # The identifier sequence lives in the SeparatedList child of
            # NetAliasSyntax (child index 2): IdentifierName Equals
            # IdentifierName Equals ...
            #
            # Resolution: ``<scope>.<name>`` via name_index; fallback to
            # ``_unresolved.<name>`` with unresolved=True.
            #
            # No new node is created; the NetAliasSyntax node stays BLOB in
            # the Bucket-1 sense.
            _mod_gid, mname = _cur_module()
            if _mod_gid is not None:
                sep_list = next(
                    (ch for ch in node
                     if not _is_token(ch)
                     and str(getattr(ch, "kind", "")).endswith("SeparatedList")),
                    None,
                )
                if sep_list is not None:
                    alias_names: list[str] = []
                    try:
                        for ch in sep_list:
                            if _is_token(ch):
                                continue
                            toks = _identifier_tokens(ch)
                            if toks:
                                alias_names.append(toks[0].valueText)
                    except TypeError:
                        pass
                    for i in range(len(alias_names) - 1):
                        a_name = alias_names[i]
                        b_name = alias_names[i + 1]
                        a_path = f"{mname}.{a_name}"
                        b_path = f"{mname}.{b_name}"
                        a_gid = name_index.get(a_path, f"_unresolved.{a_name}")
                        b_gid = name_index.get(b_path, f"_unresolved.{b_name}")
                        a_unres = isinstance(a_gid, str) and a_gid.startswith("_unresolved.")
                        b_unres = isinstance(b_gid, str) and b_gid.startswith("_unresolved.")
                        extra: dict[str, Any] = {}
                        if a_unres or b_unres:
                            extra["unresolved"] = True
                        _add_edge(graph, a_gid, b_gid, "aliases", **extra)
                        _add_edge(graph, b_gid, a_gid, "aliases", **extra)
        elif c == "TimeUnitsDeclarationSyntax":
            # S47 — promote ``timeunit <lit>;`` and ``timeprecision <lit>;``
            # (SV §22.7 time-unit / time-precision directive).
            #
            # Each statement is a separate TimeUnitsDeclaration node carrying
            # either a TimeUnitKeyword or TimePrecisionKeyword child, followed
            # by a TimeLiteral token.  The combined form ``timeunit <lit> /
            # <prec>;`` has a DividerClause child after the first literal.
            #
            # Promotion strategy:
            #   - role: "time_units"
            #   - name: "__timeunits__"
            #   - path: "<scope>.__timeunits__"  (scope from module_stack; if
            #     empty, use "__compilation__")
            #   - attributes["unit"]: TimeLiteral text (timeunit stmt only)
            #   - attributes["precision"]: TimeLiteral text (timeprecision stmt
            #     or the DividerClause literal of the combined form)
            #   - edge: has_timeunits from enclosing scope to this node
            #
            # Token traversal — no regex (lesson 4 of CLAUDE.md §6).
            mod_gid, mname = _cur_module()
            scope = mname if mname else "__compilation__"
            tpath = f"{scope}.__timeunits__"
            attrs: dict[str, Any] = {}
            # Walk direct children to classify keyword and extract literals.
            kw_kind: str | None = None
            unit_lit: str | None = None
            prec_lit: str | None = None
            try:
                children_seq = list(node)
            except TypeError:
                children_seq = []
            for ch in children_seq:
                if ch is None:
                    continue
                if _is_token(ch):
                    tok_kind = _token_kind_name(ch)
                    if tok_kind == "TimeUnitKeyword":
                        kw_kind = "timeunit"
                    elif tok_kind == "TimePrecisionKeyword":
                        kw_kind = "timeprecision"
                    elif tok_kind == "TimeLiteral" and unit_lit is None:
                        unit_lit = ch.valueText
                else:
                    # DividerClauseSyntax — combined ``timeunit X / P;``
                    div_kind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if div_kind == "DividerClause":
                        try:
                            for dch in ch:
                                if dch is not None and _is_token(dch):
                                    if _token_kind_name(dch) == "TimeLiteral":
                                        prec_lit = dch.valueText
                        except TypeError:
                            pass
            if kw_kind == "timeunit" and unit_lit is not None:
                attrs["unit"] = unit_lit
                if prec_lit is not None:
                    attrs["precision"] = prec_lit
            elif kw_kind == "timeprecision" and unit_lit is not None:
                attrs["precision"] = unit_lit
            if attrs:
                _mark(nodes_list[node_offset + idx], role="time_units",
                      name="__timeunits__", path=tpath, attributes=attrs)
                if mod_gid is not None:
                    _add_edge(graph, mod_gid, gid, "has_timeunits")
                name_index[tpath] = gid
        elif c == "TypedefDeclarationSyntax":
            mod_gid, mname = _cur_module()
            # S58: pushed_struct_union flips to True if the body is a
            # StructType / UnionType (push handled below); the matching pop
            # at end-of-subtree only fires when we pushed.
            if mod_gid is not None:
                tname = _typedef_name_of(node)
                if tname:
                    tpath = f"{mname}.{tname}"
                    # S31 — discriminate the typedef body. EnumType keeps the
                    # legacy enum-value declarator fan-out (S9c). StructType /
                    # UnionType enrich the typedef with structural attributes
                    # and must NOT push in_typedef (the inner declarators are
                    # struct members, not enum values). Other body kinds
                    # (named-type aliases, integer types) fall through with
                    # body_kind=None so consumers can still filter.
                    su_body = _struct_union_body_of(node)
                    attrs: dict[str, Any] = {}
                    is_struct_union = False
                    if su_body is not None:
                        body_kind_name = str(
                            getattr(su_body, "kind", "")
                        ).rsplit(".", 1)[-1]
                        if body_kind_name in {"StructType", "UnionType"}:
                            is_struct_union = True
                            mods = _struct_union_modifiers_of(su_body)
                            members = _struct_union_members_of(su_body)
                            attrs["body_kind"] = (
                                "struct" if body_kind_name == "StructType"
                                else "union"
                            )
                            attrs["packed"] = mods["packed"]
                            attrs["tagged"] = mods["tagged"]
                            attrs["members"] = members
                    if attrs:
                        _mark(nodes_list[node_offset + idx], role="typedef",
                              name=tname, path=tpath, attributes=attrs)
                    else:
                        _mark(nodes_list[node_offset + idx], role="typedef",
                              name=tname, path=tpath)
                    _add_edge(graph, mod_gid, gid, "has_typedef")
                    name_index[tpath] = gid
                    # Only the enum body needs the in_typedef stack — enum
                    # value declarators promote via the Declarator branch.
                    # Struct / union member declarators must stay BLOB.
                    if not is_struct_union:
                        state["typedef_stack"].append((gid, tname, tpath))
                        pushed = "in_typedef"
                    else:
                        # S58: push the struct/union typedef as the enclosing
                        # parent for fan-out of StructUnionMember declarators
                        # visited inside this subtree.
                        state["struct_union_stack"].append(
                            (gid, tpath, attrs["body_kind"])
                        )
                        pushed_struct_union = True
        elif c == "StructUnionMemberSyntax":
            # S58 — fan out struct/union body fields as queryable nodes.
            # Each StructUnionMember row carries one shared data-type prefix
            # plus a SeparatedList(Declarator, ...) (one per name in
            # ``logic [7:0] a, b, c;``). The enclosing typedef gid + path +
            # body_kind ride on ``struct_union_stack`` (pushed by the
            # TypedefDeclaration branch above when the typedef body is a
            # StructType / UnionType). Anonymous inline struct / union types
            # have no typedef parent — the stack is empty there, so we skip.
            #
            # Token-only structural walk — no regex on source text. The first
            # non-token, non-SyntaxList, non-SeparatedList child is the
            # data-type node (matches IntegerType / LogicType / NamedType
            # without depending on a specific class name); the SeparatedList
            # holds the comma-separated Declarators.
            if state["struct_union_stack"]:
                td_gid, td_path, body_kind = state["struct_union_stack"][-1]
            else:
                td_gid, td_path, body_kind = None, "", ""
            if td_gid is not None:
                type_node = None
                decl_list = None
                for ch in node:
                    if ch is None or _is_token(ch):
                        continue
                    sub_kind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if sub_kind == "SyntaxList":
                        continue
                    if sub_kind == "SeparatedList":
                        decl_list = ch
                        continue
                    if type_node is None:
                        type_node = ch
                type_text = _type_text_of(type_node)
                # Per-Declarator names. _identifier_tokens picks the leading
                # identifier of each DeclaratorSyntax (matches the
                # _struct_union_members_of helper exactly).
                names: list[str] = []
                if decl_list is not None:
                    try:
                        kids = list(decl_list)
                    except TypeError:
                        kids = []
                    for d in kids:
                        if d is None or _is_token(d):
                            continue
                        if _cls(d) != "DeclaratorSyntax":
                            continue
                        ids = _identifier_tokens(d)
                        if ids:
                            names.append(ids[0].valueText)
                if names:
                    role_name = (
                        "struct_member" if body_kind == "struct"
                        else "union_member"
                    )
                    first_name = names[0]
                    first_path = f"{td_path}.{first_name}"
                    attrs_member = {
                        "data_type": type_text,
                        "parent_kind": body_kind,
                    }
                    _mark(nodes_list[node_offset + idx], role=role_name,
                          name=first_name, path=first_path,
                          attributes=attrs_member)
                    _add_edge(graph, td_gid, gid, "has_member")
                    name_index[first_path] = gid
                    # Multi-declarator fan-out (S38-style synthetic siblings).
                    for extra_name in names[1:]:
                        extra_path = f"{td_path}.{extra_name}"
                        extra_id = f"{role_name}:{extra_path}"
                        nodes_list.append({
                            "id": extra_id,
                            "type": "StructUnionMemberSyntax",
                            "kind": "StructUnionMember",
                            "is_token": False,
                            "payload": {"synthetic": True},
                            "queryable": True,
                            "semantic": {
                                "role": role_name,
                                "name": extra_name,
                                "path": extra_path,
                                "attributes": {
                                    "data_type": type_text,
                                    "parent_kind": body_kind,
                                },
                            },
                        })
                        _add_edge(graph, td_gid, extra_id, "has_member")
                        name_index[extra_path] = extra_id
        elif c == "VirtualInterfaceTypeSyntax":
            # S60 — VirtualInterfaceType is an *edge-only* kind (lesson 4):
            # the type-expression form ``virtual <iface> [#(...)] [.<modport>]``
            # has no independent semantic identity, it links the enclosing
            # declarator (class property / function port / data declaration)
            # to the referenced interface.
            #
            # Children layout (verified via probe in iter-078 task):
            #   TokenKind.VirtualKeyword
            #   TokenKind.Identifier            — interface name
            #   [ParameterValueAssignmentSyntax] — optional ``#(...)``
            #   [DotMemberClauseSyntax]          — optional ``.<modport>``
            #     ├─ TokenKind.Dot
            #     └─ TokenKind.Identifier        — modport name
            #
            # Source endpoint resolution (declarator-first, then fall back):
            #   1. Inside a ClassPropertyDeclaration → the class_property node
            #      (``class_property_pending["decl_gid"]``).
            #   2. Else inside a class → the enclosing class node
            #      (``class_stack[-1]``).
            #   3. Else → the enclosing module / package node.
            iface_name: str | None = None
            modport_name: str | None = None
            for ch in node:
                if ch is None:
                    continue
                if _is_token(ch):
                    if (_token_kind_name(ch) == "Identifier"
                            and iface_name is None):
                        iface_name = ch.valueText
                else:
                    sub_kind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if sub_kind == "DotMemberClause":
                        for dch in ch:
                            if dch is None or not _is_token(dch):
                                continue
                            if _token_kind_name(dch) == "Identifier":
                                modport_name = dch.valueText
                                break

            if iface_name:
                # Determine source endpoint.
                src_gid: str | None = None
                pending = state.get("class_property_pending")
                if pending is not None:
                    src_gid = pending.get("decl_gid")
                if src_gid is None and state["class_stack"]:
                    src_gid, _ = state["class_stack"][-1]
                if src_gid is None:
                    mod_gid_s60, _ = _cur_module()
                    src_gid = mod_gid_s60

                # Cross-file resolution: the referenced interface may live
                # in a tree whose pass1 hasn't run yet (build_kg interleaves
                # files by parse order, not declaration-vs-reference order).
                # Defer dst resolution to the post-pass1 sweep below by
                # stashing the (src_gid, iface_name, modport_name) tuple on
                # the graph; pass1's final loop walks it and emits the
                # actual edges once name_index is fully populated.
                if src_gid is not None:
                    graph.setdefault("_s60_pending", []).append(
                        (src_gid, iface_name, modport_name)
                    )
        elif c == "ForwardTypedefDeclarationSyntax":
            # S31 — promote a bare ``typedef <name>;`` forward declaration as
            # its own node. Reuses the ``has_typedef`` edge type so existing
            # queries that list a package's typedefs see both full and forward
            # declarations; the ``forward`` attribute discriminates.
            #
            # S63 — ForwardTypeRestriction: optional restriction tag on the
            # forward decl (``typedef enum my_e;`` / ``typedef struct my_s;``
            # / ``typedef union my_u;`` / ``typedef class my_c;`` /
            # ``typedef interface class my_ic;``). The tag is surfaced as an
            # attribute on this same node — it's a property of the forward
            # decl, not an independent entity (lesson 4 attribute augmenta-
            # tion). Walk direct children for a ForwardTypeRestrictionSyntax
            # child and read its keyword token(s):
            #   EnumKeyword       -> "enum"
            #   StructKeyword     -> "struct"
            #   UnionKeyword      -> "union"
            #   ClassKeyword      -> "class"
            #   InterfaceKeyword + ClassKeyword -> "interface_class"
            # No restriction child -> restriction=None.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                fname = _forward_typedef_name_of(node)
                if fname:
                    restriction: str | None = None
                    for ch in node:
                        if ch is None or _is_token(ch):
                            continue
                        if _cls(ch) != "ForwardTypeRestrictionSyntax":
                            continue
                        kw_kinds: list[str] = []
                        for tch in ch:
                            if tch is None or not _is_token(tch):
                                continue
                            kw_kinds.append(_token_kind_name(tch))
                        if "InterfaceKeyword" in kw_kinds and "ClassKeyword" in kw_kinds:
                            restriction = "interface_class"
                        elif "EnumKeyword" in kw_kinds:
                            restriction = "enum"
                        elif "StructKeyword" in kw_kinds:
                            restriction = "struct"
                        elif "UnionKeyword" in kw_kinds:
                            restriction = "union"
                        elif "ClassKeyword" in kw_kinds:
                            restriction = "class"
                        break
                    fpath = f"{mname}.{fname}"
                    _mark(nodes_list[node_offset + idx], role="typedef_forward",
                          name=fname, path=fpath,
                          attributes={"forward": True,
                                      "restriction": restriction})
                    _add_edge(graph, mod_gid, gid, "has_typedef")
                    name_index[fpath] = gid
        elif c == "TypeParameterDeclarationSyntax":
            # S48 — promote ``parameter type T = int;`` / ``parameter type
            # DATA_T = logic [7:0];`` type parameters declared in module /
            # class / interface parameter-port lists.
            #
            # A single TypeParameterDeclarationSyntax may contain multiple
            # TypeAssignment children when written as
            # ``parameter type A = int, B = bit;`` (one keyword, two names).
            # Mirror S1's Declarator multi-name pattern: the canonical syntax
            # node gets the first name; each additional name gets a synthetic
            # sibling node appended to nodes_list (same pattern as S38 genvar).
            #
            # Parent resolution: prefer class_stack (class type parameters)
            # over module_stack (module / interface / package type parameters).
            # This is correct because TypeParameterDeclarationSyntax is always
            # visited inside the ClassDeclarationSyntax / ModuleDeclarationSyntax
            # subtree AFTER the parent has been pushed onto its respective stack.
            #
            # Default type: walk the EqualsTypeClauseSyntax child of each
            # TypeAssignmentSyntax and collect all token valueTexts to form a
            # whitespace-joined type string. Absent when no ``= <type>`` clause
            # exists (``parameter type T;`` without default).
            #
            # No regex on source text — all extraction via token kind / node
            # class inspection (CLAUDE.md invariant 4).
            if state["class_stack"]:
                scope_gid, scope_path = state["class_stack"][-1]
            else:
                scope_gid, scope_path = _cur_module()
            if scope_gid is not None:
                # Collect all TypeAssignment children from the SeparatedList.
                # Structure: TypeParameterDeclarationSyntax
                #   Token [ParameterKeyword]
                #   Token [TypeKeyword]
                #   SyntaxNode [SeparatedList]   ← walk this
                #     TypeAssignmentSyntax …
                #     Token [Comma]
                #     TypeAssignmentSyntax …
                type_assignments: list[tuple[str, str | None]] = []
                for ch in node:
                    if ch is None or _is_token(ch):
                        continue
                    # SeparatedList wrapper — one level down
                    try:
                        for item in ch:
                            if item is None or _is_token(item):
                                continue
                            if _cls(item) == "TypeAssignmentSyntax":
                                # First direct token child is the Identifier.
                                tpname = ""
                                default_type: str | None = None
                                for sub in item:
                                    if sub is None:
                                        continue
                                    if _is_token(sub):
                                        tkind = _token_kind_name(sub)
                                        if tkind == "Identifier" and not tpname:
                                            tpname = sub.valueText
                                    else:
                                        # EqualsTypeClauseSyntax — collect all
                                        # token valueTexts from the type part
                                        # (skip the leading '=' token).
                                        sub_kind = str(
                                            getattr(sub, "kind", "")
                                        ).rsplit(".", 1)[-1]
                                        if sub_kind == "EqualsTypeClause":
                                            # Walk EqualsTypeClause children
                                            # skipping the leading '=' token,
                                            # then recursively collect all
                                            # remaining token valueTexts.
                                            def _collect_toks(
                                                n: Any,
                                                out: list[str],
                                            ) -> None:
                                                try:
                                                    for t in n:
                                                        if t is None:
                                                            continue
                                                        if _is_token(t):
                                                            v = t.valueText
                                                            if v:
                                                                out.append(v)
                                                        else:
                                                            _collect_toks(t, out)
                                                except TypeError:
                                                    pass
                                            pieces: list[str] = []
                                            saw_eq = False
                                            for eq_child in sub:
                                                if eq_child is None:
                                                    continue
                                                if _is_token(eq_child):
                                                    if not saw_eq:
                                                        saw_eq = True
                                                        # skip the '=' token
                                                    else:
                                                        v = eq_child.valueText
                                                        if v:
                                                            pieces.append(v)
                                                else:
                                                    _collect_toks(eq_child, pieces)
                                            default_type = " ".join(pieces) if pieces else None
                                if tpname:
                                    type_assignments.append((tpname, default_type))
                    except TypeError:
                        pass
                # Promote: canonical node gets first assignment, synthetic
                # nodes carry the remaining ones (mirrors S38 genvar).
                for assign_idx, (tpname, default_type) in enumerate(type_assignments):
                    tppath = f"{scope_path}.{tpname}"
                    attrs: dict[str, Any] = {}
                    if default_type:
                        attrs["default_type"] = default_type
                    if assign_idx == 0:
                        # Canonical node — mark the existing graph node.
                        if attrs:
                            _mark(nodes_list[node_offset + idx],
                                  role="type_param", name=tpname, path=tppath,
                                  attributes=attrs)
                        else:
                            _mark(nodes_list[node_offset + idx],
                                  role="type_param", name=tpname, path=tppath)
                        _add_edge(graph, scope_gid, gid, "has_type_param")
                        name_index[tppath] = gid
                    else:
                        # Synthetic sibling node for 2nd+ assignments.
                        syn_id = f"type_param:{tppath}"
                        syn_node: dict[str, Any] = {
                            "id": syn_id,
                            "type": "TypeParameterDeclarationSyntax",
                            "kind": "TypeParameterDeclaration",
                            "is_token": False,
                            "payload": {"synthetic": True},
                            "queryable": True,
                            "semantic": {
                                "role": "type_param",
                                "name": tpname,
                                "path": tppath,
                            },
                        }
                        if attrs:
                            syn_node["semantic"]["attributes"] = attrs
                        nodes_list.append(syn_node)
                        _add_edge(graph, scope_gid, syn_id, "has_type_param")
                        name_index[tppath] = syn_id
        elif c in ("PackageImportDeclarationSyntax",
                   "PackageExportDeclarationSyntax"):
            # S32 — package import / export declarations. We do NOT promote
            # the declaration itself to a node; instead we emit one
            # cross-cutting edge per imported / exported item from the
            # enclosing module / interface / package / program (the
            # ``module_stack`` top) to the referenced package node, mirroring
            # the S25 extends/implements edge-only pattern.
            #
            # ``import pkg::A, pkg::B;`` therefore fans out into two
            # ``imports`` edges. Wildcard ``::*`` is captured as
            # ``payload["item"] = "*"``.
            #
            # Resolution: the package name is looked up in the shared
            # ``semantic_name_index`` under the ``package:`` prefix and then
            # bare. If unresolved (external package), the edge points at the
            # synthetic ``_unresolved.<pkg>`` placeholder with
            # ``payload["unresolved"] = True`` — same convention as S25.
            #
            # Compilation-unit-scope imports (no enclosing module/package)
            # have no parent; we skip the edge and record a leak entry so
            # the loss is auditable.
            is_export = (c == "PackageExportDeclarationSyntax")
            edge_type = "exports" if is_export else "imports"
            items = _package_import_items_of(node)
            mod_gid, mname = _cur_module()
            for pkg_name, item_label in items:
                if mod_gid is None:
                    leaks.append({
                        "kind": c,
                        "reason": "cu-scope package import/export skipped",
                        "package": pkg_name,
                        "item": item_label,
                        "edge_type": edge_type,
                    })
                    continue
                tgt_id = name_index.get(f"package:{pkg_name}")
                if tgt_id is None:
                    tgt_id = name_index.get(pkg_name)
                unresolved = False
                if tgt_id is None:
                    tgt_id = f"_unresolved.{pkg_name}"
                    unresolved = True
                payload: dict[str, Any] = {
                    "package": pkg_name,
                    "item": item_label,
                }
                if unresolved:
                    payload["unresolved"] = True
                _add_edge(graph, mod_gid, tgt_id, edge_type, **payload)
        elif c == "ImplicitAnsiPortSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                decl = next((ch for ch in node if _cls(ch) == "DeclaratorSyntax"), None)
                ids = _identifier_tokens(decl) if decl is not None else []
                if ids:
                    pname = ids[0].valueText
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[node_offset + idx], role="port", name=pname, path=ppath)
                    _add_edge(graph, mod_gid, gid, "has_port")
                    name_index[ppath] = gid
                    port_names_by_module.setdefault(mname, set()).add(pname)
            pushed = "in_port"
        elif c == "ExplicitAnsiPortSyntax":
            # S64 — ``.name(expr)`` ANSI port form (sibling of S1
            # ImplicitAnsiPort). The leading direction keyword
            # (input/output/inout/ref) is the first non-attribute Token among
            # the node's children; the port name is the Identifier token
            # immediately following the ``.`` (Dot) token. The connect
            # expression — if present — stays a child blob (graph-as-index,
            # blob-as-detail). Empty-connect form ``.foo()`` is legal and
            # surfaces as expr=None on the syntax object; we still promote.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                direction = ""
                pname = ""
                saw_dot = False
                for ch in node:
                    if ch is None or not _is_token(ch):
                        continue
                    tk = _token_kind_name(ch)
                    if tk in {"InputKeyword", "OutputKeyword",
                              "InOutKeyword", "RefKeyword"}:
                        if not direction:
                            direction = ch.valueText
                    elif tk == "Dot":
                        saw_dot = True
                    elif saw_dot and tk == "Identifier" and not pname:
                        pname = ch.valueText
                        break
                if pname:
                    ppath = f"{mname}.{pname}"
                    attrs: dict[str, Any] = {}
                    if direction:
                        attrs["direction"] = direction
                    _mark(nodes_list[node_offset + idx], role="port",
                          name=pname, path=ppath, attributes=attrs)
                    _add_edge(graph, mod_gid, gid, "has_port")
                    name_index[ppath] = gid
                    port_names_by_module.setdefault(mname, set()).add(pname)
            pushed = "in_port"
        elif c == "ExplicitNonAnsiPortSyntax":
            # S65 — legacy non-ANSI ``.name(expr)`` header port form. Lives
            # inside a NonAnsiPortList (no direction keyword on the header —
            # direction arrives via separate ``input``/``output`` statements
            # in the body, owned by S55 PortDeclaration). The header carries
            # only the external port name (the Identifier after the ``.``)
            # and an optional internal connect expression
            # (PortReferenceSyntax). The bare ``.b`` header form surfaces as
            # ExplicitNonAnsiPort with an empty connect (no PortReference
            # child), which still promotes — we only need the name token.
            # Path key follows the sibling S1/S64 convention
            # (``<module>.<port_name>``); the body S55 Declarator may also
            # bind a port node at the same path with the direction attribute
            # — both nodes coexist in queryable_nodes (header view + body
            # view of the same logical port).
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                pname = ""
                saw_dot = False
                for ch in node:
                    if ch is None or not _is_token(ch):
                        continue
                    tk = _token_kind_name(ch)
                    if tk == "Dot":
                        saw_dot = True
                    elif saw_dot and tk == "Identifier" and not pname:
                        pname = ch.valueText
                        break
                if pname:
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[node_offset + idx], role="port",
                          name=pname, path=ppath)
                    _add_edge(graph, mod_gid, gid, "has_port")
                    name_index[ppath] = gid
                    port_names_by_module.setdefault(mname, set()).add(pname)
            # S67: push parent-context frame so any PortReferenceSyntax
            # child (the internal-signal name in ``.a(p)``) promotes at a
            # distinct path (``<module>.port_reference.<name>``) — the
            # external port name lives at ``<module>.<external_name>``
            # already, and overlaying them would collide.
            state["port_ref_parent_stack"].append(("explicit_non_ansi", None))
            pushed = "in_port"
        elif c == "ImplicitNonAnsiPortSyntax":
            # S66 — legacy non-ANSI bare-name header port form. Lives inside
            # a NonAnsiPortList under the ModuleHeader; the header carries
            # only an identifier (the ``a`` in ``module m(a, b);``) and
            # directions/types arrive via separate input/output statements
            # in the body, owned by S55 PortDeclaration. The pyslang shape is
            # ImplicitNonAnsiPort(expr=PortReferenceSyntax(name=<token>))
            # for the simple form; the PortConcatenation form
            # (``module m({a,b}, c);``) wraps a PortConcatenationSyntax
            # instead — we intentionally skip emission for that variant
            # (no single name to key on). Path key follows the sibling S1
            # /S64/S65 convention (``<module>.<port_name>``). The body S55
            # Declarator may also bind a port node at the same path with
            # the direction attribute — both nodes coexist in
            # queryable_nodes (header view + body view of the same logical
            # port).
            mod_gid, mname = _cur_module()
            twin_path: str | None = None
            if mod_gid is not None:
                pname = ""
                expr = getattr(node, "expr", None)
                if expr is not None and _cls(expr) == "PortReferenceSyntax":
                    name_tok = getattr(expr, "name", None)
                    if name_tok is not None and _is_token(name_tok):
                        if _token_kind_name(name_tok) == "Identifier":
                            pname = name_tok.valueText
                if pname:
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[node_offset + idx], role="port",
                          name=pname, path=ppath)
                    _add_edge(graph, mod_gid, gid, "has_port")
                    name_index[ppath] = gid
                    port_names_by_module.setdefault(mname, set()).add(pname)
                    twin_path = ppath
            # S67: push parent-context frame. For the simple form (PortRef
            # naming the bare port name) twin_path holds the path S66 just
            # bound — the PortReference child gets role=port_reference at
            # the SAME path (twin view, not a new port). For the
            # PortConcatenation form twin_path is None — the PortReference
            # items inside surface at ``<module>.port_reference.<name>``.
            state["port_ref_parent_stack"].append(
                ("implicit_non_ansi", twin_path))
            pushed = "in_port"
        elif c == "PortReferenceSyntax":
            # S67 — promote the PortReference sub-expression inside non-ANSI
            # port lists as a queryable ``role=port_reference`` node. The
            # parent context (pushed by S65 / S66 / future S68) tells us
            # which path-key convention to use:
            #
            # * ``implicit_non_ansi`` w/ twin_path (S66 simple form): the
            #   enclosing port has already been promoted at the same name
            #   we'd choose — twin the PortReference at that same path
            #   (queryable_nodes will surface both the port node and the
            #   port_reference node; callers querying for PortReference
            #   sub-shapes find this one). NO new edge, NO name_index
            #   rebind (S66's port owns the path).
            # * ``implicit_non_ansi`` w/o twin_path (S66 PortConcatenation
            #   case — future S68 home), or ``explicit_non_ansi`` (S65
            #   internal-signal name): emit at
            #   ``<module>.port_reference.<name>`` — a distinct sub-namespace
            #   that cannot collide with S65's external port name at
            #   ``<module>.<name>``. Register in name_index under this
            #   distinct key so downstream resolvers can find the internal
            #   signal reference without disturbing the external port.
            #
            # Dedup: idempotent on path key — re-emission for the same path
            # is a no-op (the _mark call is the only side effect for the
            # twin case; for the standalone case the name_index assignment
            # is also idempotent). PortReferences outside any tracked
            # parent context (defensive: should not arise in current
            # corpus) silently no-op.
            mod_gid, mname = _cur_module()
            if (mod_gid is not None
                    and state["port_ref_parent_stack"]):
                parent_kind, twin = state["port_ref_parent_stack"][-1]
                name_tok = getattr(node, "name", None)
                pref_name = ""
                if (name_tok is not None
                        and _is_token(name_tok)
                        and _token_kind_name(name_tok) == "Identifier"):
                    pref_name = name_tok.valueText
                if pref_name:
                    if twin is not None:
                        # S66 simple-form twin: share the port's path key.
                        pref_path = twin
                    else:
                        pref_path = (
                            f"{mname}.port_reference.{pref_name}")
                    _mark(nodes_list[node_offset + idx],
                          role="port_reference",
                          name=pref_name,
                          path=pref_path,
                          parent_kind=parent_kind)
                    if twin is None:
                        # Only register the standalone path; never overwrite
                        # the S66 port entry already at ``<module>.<name>``.
                        name_index.setdefault(pref_path, gid)
                    # S68: if this PortReference sits inside a
                    # PortConcatenation, the concat groups it. Emit one
                    # ``groups_port_ref`` edge per member so callers can walk
                    # from the concat down to its constituent PortReferences.
                    if state["port_concat_stack"]:
                        concat_gid = state["port_concat_stack"][-1]
                        if concat_gid is not None:
                            _add_edge(graph, concat_gid, gid,
                                      "groups_port_ref")
        elif c == "PortConcatenationSyntax":
            # S68 — ``{a, b}`` curly-grouped port entry inside a non-ANSI
            # port list. Sits as the ``expr`` child of an
            # ImplicitNonAnsiPortSyntax (S66 intentionally skips emission
            # for this expr-shape — no single name to key on). The concat
            # IS one external port externally that bundles multiple
            # internal nets; each internal net surfaces as a PortReference
            # member promoted by S67 at
            # ``<module>.port_reference.<name>``. Path key for the concat
            # itself is anonymous-synthetic — ``<module>.__port_concat_N__``
            # — following the S19/S20/S21 convention for nameless
            # promotions. Edges: ``has_port`` from the module (the concat
            # is a port) and ``groups_port_ref`` to each member (emitted
            # from the PortReference branch above when port_concat_stack is
            # non-empty).
            mod_gid, mname = _cur_module()
            concat_gid: str | None = None
            if mod_gid is not None:
                n_idx = port_concat_counters.get(mname, 0)
                port_concat_counters[mname] = n_idx + 1
                cpath = f"{mname}.__port_concat_{n_idx}__"
                _mark(nodes_list[node_offset + idx], role="port_concat",
                      name=f"__port_concat_{n_idx}__", path=cpath)
                _add_edge(graph, mod_gid, gid, "has_port")
                name_index.setdefault(cpath, gid)
                concat_gid = gid
            state["port_concat_stack"].append(concat_gid)
            pushed = "in_port"
        elif c == "GenvarDeclarationSyntax":
            # S38 — promote ``genvar <id1>, <id2>, ...;`` declarations.
            # A single GenvarDeclarationSyntax may declare multiple identifiers
            # (``genvar i, j, k;``). We promote one queryable ``genvar`` node
            # per identifier: the canonical syntax node gets the first name,
            # and synthetic nodes (appended to nodes_list — same pattern used
            # by S12 for elaborated GenerateBlock entries) carry the remaining
            # names. Each node gets a ``has_genvar`` edge from the enclosing
            # module and is registered in the name_index so that for-generate
            # loops and elaboration can resolve the genvar by path.
            #
            # Identifier extraction: walk direct children for
            # ``IdentifierNameSyntax`` nodes and collect the ``valueText`` of
            # their ``Identifier`` token child. The SeparatedList interleaves
            # commas (Token) with IdentifierNameSyntax nodes; we skip tokens.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                genvar_names: list[str] = []
                for ch in node:
                    if _is_token(ch):
                        continue
                    if _cls(ch) == "IdentifierNameSyntax":
                        for tok in ch:
                            if _is_token(tok) and _token_kind_name(tok) == "Identifier":
                                genvar_names.append(tok.valueText)
                                break
                    elif _cls(ch) == "SyntaxNode":
                        # SeparatedList wrapper — descend one level
                        try:
                            for item in ch:
                                if _is_token(item):
                                    continue
                                if _cls(item) == "IdentifierNameSyntax":
                                    for tok in item:
                                        if (_is_token(tok)
                                                and _token_kind_name(tok) == "Identifier"):
                                            genvar_names.append(tok.valueText)
                                            break
                        except TypeError:
                            pass
                # First name goes on the canonical syntax node.
                if genvar_names:
                    first = genvar_names[0]
                    first_path = f"{mname}.{first}"
                    _mark(nodes_list[node_offset + idx], role="genvar",
                          name=first, path=first_path)
                    _add_edge(graph, mod_gid, gid, "has_genvar")
                    name_index[first_path] = gid
                    # 2nd+ names get synthetic sibling nodes so each genvar
                    # identifier is independently queryable by path.
                    for extra_name in genvar_names[1:]:
                        extra_path = f"{mname}.{extra_name}"
                        extra_id = f"genvar:{extra_path}"
                        nodes_list.append({
                            "id": extra_id,
                            "type": "GenvarDeclarationSyntax",
                            "kind": "GenvarDeclaration",
                            "is_token": False,
                            "payload": {"synthetic": True},
                            "queryable": True,
                            "semantic": {
                                "role": "genvar",
                                "name": extra_name,
                                "path": extra_path,
                            },
                        })
                        _add_edge(graph, mod_gid, extra_id, "has_genvar")
                        name_index[extra_path] = extra_id
        elif c == "LetDeclarationSyntax":
            # S42 — promote ``let <name>[(ports)] = <expr>;`` declarations as
            # queryable nodes under the enclosing module / checker / package
            # (the ``module_stack`` top, subtler variant from lesson 2).
            #
            # Name extraction: walk direct children for Token nodes; the
            # Identifier token immediately following the LetKeyword is the
            # let name. Port count extraction: walk the
            # AssertionItemPortListSyntax child and count
            # AssertionItemPortSyntax nodes inside the SeparatedList wrapper.
            # The body expression stays BLOB — graph-as-index, blob-as-detail.
            # No regex on source text.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                saw_let_kw = False
                let_name = ""
                port_count = 0
                for ch in node:
                    if ch is None:
                        continue
                    if _is_token(ch):
                        tkind = _token_kind_name(ch)
                        if tkind == "LetKeyword":
                            saw_let_kw = True
                        elif saw_let_kw and tkind == "Identifier" and not let_name:
                            let_name = ch.valueText
                    elif _cls(ch) == "AssertionItemPortListSyntax":
                        for pch in ch:
                            if pch is None or _is_token(pch):
                                continue
                            if _cls(pch) == "AssertionItemPortSyntax":
                                port_count += 1
                            else:
                                # SeparatedList wrapper
                                try:
                                    for gch in pch:
                                        if (gch is not None
                                                and not _is_token(gch)
                                                and _cls(gch) == "AssertionItemPortSyntax"):
                                            port_count += 1
                                except TypeError:
                                    pass
                push_sva_frame_let: tuple | None = None
                if let_name:
                    lpath = f"{mname}.{let_name}"
                    _mark(nodes_list[node_offset + idx], role="let_decl",
                          name=let_name, path=lpath,
                          attributes={"port_count": port_count})
                    _add_edge(graph, mod_gid, gid, "has_let")
                    name_index[lpath] = gid
                    # S77: expose this let as the enclosing scope for any
                    # AssertionItemPort children. Frame is popped on subtree
                    # exit below. Pattern mirrors PropertyDeclaration /
                    # SequenceDeclaration push above.
                    push_sva_frame_let = (gid, lpath)
                if push_sva_frame_let is not None:
                    state["sva_decl_stack"].append(push_sva_frame_let)
                else:
                    # Symmetric sentinel push so the pop-on-exit below is
                    # always balanced regardless of name extraction success.
                    state["sva_decl_stack"].append((None, ""))
            else:
                # Even when mod_gid is None we still need a sentinel push so
                # the LetDeclaration pop on exit stays balanced.
                state["sva_decl_stack"].append((None, ""))
        elif c == "DefParamAssignmentSyntax":
            # S43 — ``defparam <inst>.<param> = <expr>;`` legacy override.
            # Edge-only (lesson 4): emit ``defparam_override`` from the
            # enclosing module to the target parameter, with payload
            # ``{"hier_path": "<lhs>", "value": "<rhs_text>"}``.
            # Delegate to rule_s43 which carries the full structural walk.
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                rule_s43(
                    graph=graph,
                    node=node,
                    gid=gid,
                    gnode=nodes_list[node_offset + idx],
                    scope=None,
                    name_index=name_index,
                    leaks=leaks,
                    scope_path=mname,
                    module_gid=mod_gid,
                )
        elif c == "ParameterDeclarationSyntax":
            pushed = "in_param"
        elif c == "CheckerDataDeclarationSyntax":
            # S62 — promote ``rand <type> <name>[, <name>...];`` declarations
            # that appear inside a checker body. pyslang surfaces these as a
            # dedicated ``CheckerDataDeclarationSyntax`` whose direct children
            # are ``[SyntaxList(attrs), RandKeyword, DataDeclarationSyntax]``
            # (verified via SyntaxTree probe). Non-rand checker-local decls
            # (``logic x;`` / ``bit [3:0] cnt;``) parse as plain
            # DataDeclarationSyntax and stay on the in_data → net path that
            # the checker_stack-augmented module_stack already supports.
            #
            # Strategy mirrors S57 (LocalVariableDeclaration): fan-out one
            # ``checker_data`` node per Declarator under the inner
            # DataDeclaration's SeparatedList. Canonical syntax node carries
            # the first name; 2nd+ get S38-style synthetic sibling nodes
            # appended to nodes_list. Each emits ``has_checker_data`` from
            # the enclosing checker.
            #
            # Parent resolution: the CheckerDeclaration branch pushes the
            # checker onto both checker_stack and module_stack; we read the
            # top of checker_stack so the parent path is unambiguously the
            # checker even if a nested rule had layered another module_stack
            # frame on top (none today, but defensive).
            #
            # Suppression: push ``in_checker_data`` for the duration of this
            # subtree so the inner DataDeclarationSyntax does NOT set
            # ``pushed = "in_data"`` — without this, every rand declarator
            # would also surface as role=net under the same path.
            parent_gid: str | None = None
            parent_path = ""
            if state["checker_stack"]:
                parent_gid, parent_path = state["checker_stack"][-1]
            if parent_gid is not None:
                # Find the inner DataDeclarationSyntax wrapper. Its kind is
                # ``DataDeclaration`` regardless of nesting (lesson 1: kind
                # discriminator, not class identity).
                inner_dd = None
                for ch in node:
                    if ch is None or _is_token(ch):
                        continue
                    ck = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if ck == "DataDeclaration":
                        inner_dd = ch
                        break
                type_node = None
                decl_list = None
                if inner_dd is not None:
                    for sub in inner_dd:
                        if sub is None or _is_token(sub):
                            continue
                        sk = str(getattr(sub, "kind", "")).rsplit(".", 1)[-1]
                        if sk in ("SyntaxList", "TokenList"):
                            continue
                        if sk == "SeparatedList":
                            decl_list = sub
                            continue
                        if type_node is None:
                            type_node = sub
                type_text = _type_text_of(type_node)
                declarators: list[tuple[str, bool]] = []
                if decl_list is not None:
                    try:
                        kids = list(decl_list)
                    except TypeError:
                        kids = []
                    for d in kids:
                        if d is None or _is_token(d):
                            continue
                        if _cls(d) != "DeclaratorSyntax":
                            continue
                        ids = _identifier_tokens(d)
                        if not ids:
                            continue
                        dname = ids[0].valueText
                        has_init = False
                        for dch in d:
                            if (dch is not None and not _is_token(dch)
                                    and _cls(dch) == "EqualsValueClauseSyntax"):
                                has_init = True
                                break
                        declarators.append((dname, has_init))
                if declarators:
                    first_name, first_init = declarators[0]
                    first_path = f"{parent_path}.{first_name}"
                    _mark(nodes_list[node_offset + idx],
                          role="checker_data",
                          name=first_name, path=first_path,
                          attributes={
                              "data_type": type_text,
                              "has_initializer": first_init,
                              "is_rand": True,
                          })
                    _add_edge(graph, parent_gid, gid, "has_checker_data")
                    name_index[first_path] = gid
                    # S38-style synthetic siblings for the 2nd+ declarators.
                    for extra_name, extra_init in declarators[1:]:
                        extra_path = f"{parent_path}.{extra_name}"
                        extra_id = f"checker_data:{extra_path}"
                        nodes_list.append({
                            "id": extra_id,
                            "type": "CheckerDataDeclarationSyntax",
                            "kind": "CheckerDataDeclaration",
                            "is_token": False,
                            "payload": {"synthetic": True},
                            "queryable": True,
                            "semantic": {
                                "role": "checker_data",
                                "name": extra_name,
                                "path": extra_path,
                                "attributes": {
                                    "data_type": type_text,
                                    "has_initializer": extra_init,
                                    "is_rand": True,
                                },
                            },
                        })
                        _add_edge(graph, parent_gid, extra_id,
                                  "has_checker_data")
                        name_index[extra_path] = extra_id
            pushed = "in_checker_data"
        elif c == "DataDeclarationSyntax":
            # S62: when wrapped by a CheckerDataDeclarationSyntax (rand
            # checker-local data decl), suppress the in_data push so the
            # inner Declarators don't re-promote as role=net — they were
            # already surfaced as role=checker_data by the S62 branch above.
            if state["in_checker_data"] > 0:
                pass
            else:
                pushed = "in_data"
        elif c == "NetDeclarationSyntax":
            # S54 — promote NetDeclaration as a group node (role="net_decl")
            # carrying net_type + signed attributes, with a ``has_net_decl``
            # edge from the enclosing module. Per-net Declarator children fall
            # through to the existing in_data branch below (we push in_data
            # for the duration of this subtree) so each net surfaces as a
            # role="net" queryable node — identical convention to S1's logic-
            # net path under DataDeclarationSyntax. The group also emits
            # ``groups_net`` edges to each child Declarator gid via
            # net_decl_stack (consulted from the Declarator branch).
            #
            # Layout (verified via SyntaxTree probe):
            #   SyntaxList                    -- leading attributes
            #   <NetType>Keyword              -- wire / tri / supply0 / ...
            #   ImplicitTypeSyntax            -- optional signing + dims
            #     [SignedKeyword | UnsignedKeyword]
            #     SyntaxList(VariableDimensionSyntax*)
            #   SeparatedList(DeclaratorSyntax, comma, ...)
            #   Semicolon
            #
            # Token-only traversal — no regex (lesson 6).
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                _NET_TYPE_TOKENS = {
                    "WireKeyword": "wire",
                    "TriKeyword": "tri",
                    "Tri0Keyword": "tri0",
                    "Tri1Keyword": "tri1",
                    "TriAndKeyword": "triand",
                    "TriOrKeyword": "trior",
                    "TriRegKeyword": "trireg",
                    "WAndKeyword": "wand",
                    "WOrKeyword": "wor",
                    "Supply0Keyword": "supply0",
                    "Supply1Keyword": "supply1",
                    "UWireKeyword": "uwire",
                }
                net_type: str | None = None
                signed_attr = False
                # Walk direct children: classify net-type keyword, then peek
                # into ImplicitType for SignedKeyword.
                for ch in node:
                    if ch is None:
                        continue
                    if _is_token(ch):
                        tk = _token_kind_name(ch)
                        if net_type is None and tk in _NET_TYPE_TOKENS:
                            net_type = _NET_TYPE_TOKENS[tk]
                    else:
                        ckind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                        if ckind == "ImplicitType":
                            try:
                                for sub in ch:
                                    if sub is None or not _is_token(sub):
                                        continue
                                    if _token_kind_name(sub) == "SignedKeyword":
                                        signed_attr = True
                                        break
                            except TypeError:
                                pass
                if net_type is not None:
                    # Path: <module>.__net_decl_<offset>__ — offset on the
                    # net-type keyword token makes the path stable + unique
                    # across multiple NetDeclarations in the same module.
                    kw_off = 0
                    for ch in node:
                        if (ch is not None and _is_token(ch)
                                and _token_kind_name(ch) in _NET_TYPE_TOKENS):
                            loc = getattr(ch, "location", None)
                            if loc is not None:
                                kw_off = getattr(loc, "offset", 0) or 0
                            break
                    grp_name = f"__net_decl_{kw_off}__"
                    grp_path = f"{mname}.{grp_name}"
                    _mark(nodes_list[node_offset + idx], role="net_decl",
                          name=grp_name, path=grp_path,
                          attributes={"net_type": net_type,
                                      "signed": signed_attr})
                    _add_edge(graph, mod_gid, gid, "has_net_decl")
                    name_index[grp_path] = gid
                    state["net_decl_stack"].append(gid)
                    # The visitor below pushes ``in_data`` to surface child
                    # Declarators as role="net" (mirroring DataDeclaration).
                    pushed = "in_data"
        elif c == "ExternInterfaceMethodSyntax":
            # S56 — mark that the next FunctionPrototypeSyntax descendant is
            # an interface-scope extern method declaration so the
            # FunctionPrototype branch promotes it (the class-scope and
            # DPI-scope wrappers, ClassMethodPrototype and DPIImport, are
            # owned by S26 and S44 respectively and do NOT push this stack —
            # FunctionPrototype nested in them is silently passed through).
            #
            # S80 — the ExternInterfaceMethodSyntax wrapper itself carries one
            # attribute that the inner FunctionPrototype does NOT capture:
            # the optional ``forkjoin`` keyword (LRM 25.10 — ``extern forkjoin
            # task`` denotes a task whose body, when later supplied via an
            # ``import`` statement, must be fork/join-decoupled).  Per lesson 5
            # we do not register the wrapper as its own queryable node; instead
            # the stack frame carries the ``forkjoin`` discriminator and the
            # FunctionPrototype branch lifts it onto the S56 attributes dict.
            # Popped on subtree exit below.
            fj_flag = False
            try:
                fj_tok = node.forkJoin
                if fj_tok is not None:
                    # Present-and-valid forkjoin keyword surfaces as
                    # TokenKind.ForkJoinKeyword; an absent slot surfaces as a
                    # placeholder Token with TokenKind.Unknown and empty
                    # valueText.
                    if _token_kind_name(fj_tok) == "ForkJoinKeyword":
                        fj_flag = True
            except Exception:
                fj_flag = False
            state["extern_method_stack"].append({"forkjoin": fj_flag})
        elif c == "FunctionPrototypeSyntax":
            # S56 — promote a FunctionPrototype whose enclosing wrapper is an
            # ExternInterfaceMethod (i.e. ``extern function|task <name>(...);``
            # inside an interface body).  Other wrapper contexts
            # (ClassMethodPrototype → S26, DPIImport → S44) do not push
            # ``extern_method_stack`` so this branch is silently inert there;
            # this satisfies lesson 5 (no double-promotion with the owners of
            # the wrapping SyntaxKind).
            #
            # Attributes:
            #   name         — identifier extracted structurally from the name
            #                  child (IdentifierName / KeywordName / ScopedName).
            #   return_type  — for ``function``: return-type text via the same
            #                  structural walk that S26 uses
            #                  (_function_proto_name_and_return).  For
            #                  ``task``: None (tasks have no return type).
            #   port_count   — number of FunctionPortSyntax entries in the
            #                  FunctionPortList; 0 when the port list is empty
            #                  or absent.
            #   kind         — "function" or "task", discriminated by the
            #                  leading FunctionKeyword / TaskKeyword token.
            #   is_extern    — True for the ExternInterfaceMethod path (the
            #                  only path that reaches this branch today).
            # The path key is ``<interface>.<name>``; the edge type is
            # ``prototypes`` from the enclosing module_stack top (interface).
            if state["extern_method_stack"]:
                mod_gid, mname = _cur_module()
                if mod_gid is not None:
                    # Discriminate function vs task by the first keyword token.
                    proto_kind = "function"
                    for ch in node:
                        if ch is None or not _is_token(ch):
                            continue
                        tk = _token_kind_name(ch)
                        if tk == "FunctionKeyword":
                            proto_kind = "function"
                            break
                        if tk == "TaskKeyword":
                            proto_kind = "task"
                            break
                    if proto_kind == "function":
                        fp_name, fp_rt = _function_proto_name_and_return(node)
                    else:
                        # Tasks: walk past the TaskKeyword, the next non-token
                        # non-empty-SyntaxList child is the name (no return
                        # type for tasks).
                        fp_name = ""
                        fp_rt = None
                        saw_kw = False
                        for ch in node:
                            if ch is None:
                                continue
                            if _is_token(ch):
                                if _token_kind_name(ch) == "TaskKeyword":
                                    saw_kw = True
                                continue
                            if not saw_kw:
                                continue
                            cn = _cls(ch)
                            if cn == "SyntaxNode":
                                try:
                                    kids = list(ch)
                                except TypeError:
                                    kids = []
                                if not kids:
                                    continue
                            if cn == "FunctionPortListSyntax":
                                break
                            toks = _identifier_tokens(ch)
                            if toks:
                                fp_name = toks[0].valueText
                                break
                    # Port count: count FunctionPortSyntax under the
                    # FunctionPortList child.
                    port_count = 0
                    for ch in node:
                        if ch is None or _is_token(ch):
                            continue
                        if _cls(ch) == "FunctionPortListSyntax":
                            for sub in ch:
                                if sub is None or _is_token(sub):
                                    continue
                                if _cls(sub) == "SyntaxNode":
                                    for gc in sub:
                                        if (gc is not None
                                                and not _is_token(gc)
                                                and _cls(gc) == "FunctionPortSyntax"):
                                            port_count += 1
                                elif _cls(sub) == "FunctionPortSyntax":
                                    port_count += 1
                            break
                    if fp_name:
                        fp_path = f"{mname}.{fp_name}"
                        # S80: lift the wrapper-level ``forkjoin`` flag onto
                        # this S56 node. The discriminator is set by the
                        # ExternInterfaceMethodSyntax push above; defaults to
                        # False when the wrapper omits the keyword (the common
                        # case — only ``extern forkjoin task`` flips it).
                        fj_attr = False
                        ems_top = state["extern_method_stack"][-1]
                        if isinstance(ems_top, dict):
                            fj_attr = bool(ems_top.get("forkjoin", False))
                        _mark(nodes_list[node_offset + idx],
                              role="function_prototype",
                              name=fp_name, path=fp_path,
                              attributes={
                                  "return_type": fp_rt,
                                  "port_count": port_count,
                                  "is_extern": True,
                                  "kind": proto_kind,
                                  "forkjoin": fj_attr,
                              })
                        _add_edge(graph, mod_gid, gid, "prototypes")
                        name_index[fp_path] = gid
                        # S74: expose this prototype as the function_stack
                        # parent so FunctionPort children attach to it.
                        state["function_stack"].append((gid, fp_path))
                        pushed_function = True
        elif c == "FunctionPortSyntax":
            # S74 — promote one argument of a function/task/method signature
            # as role="function_port".  Parent is the enclosing function /
            # method / extern-prototype scope on ``function_stack`` (pushed
            # by FunctionDeclaration, ClassMethodDeclaration /
            # ClassMethodPrototype, or the extern-FunctionPrototype branch
            # in S56). Layout (verified via SyntaxTree probe):
            #
            #   SyntaxList                     -- leading attributes
            #   [Direction keyword token]      -- Input/Output/InOut/Ref
            #   [const/var/static keywords]    -- optional storage qualifiers
            #   <dataType>                     -- IntegerTypeSyntax / NamedType /
            #                                     ImplicitTypeSyntax / …
            #   <DeclaratorSyntax>             -- carries the port name
            #
            # Direction is captured via TokenKind.* (no regex on source);
            # an absent direction surfaces as the empty string (matches the
            # pyslang convention — ``n.direction.valueText == ''`` when the
            # parser doesn't see a leading direction keyword).
            if state["function_stack"]:
                parent_gid, parent_path = state["function_stack"][-1]
            else:
                parent_gid, parent_path = None, ""
            if parent_gid is not None:
                direction = ""
                try:
                    dir_tok = node.direction
                    if dir_tok is not None:
                        dv = dir_tok.valueText
                        if dv:
                            direction = dv
                except Exception:
                    direction = ""
                # Data type via the structural helper (handles dims/signing).
                dt_text = ""
                try:
                    dt_node = node.dataType
                    if dt_node is not None:
                        dt_text = _type_text_of(dt_node).strip()
                except Exception:
                    dt_text = ""
                # Port name via the declarator's identifier token.
                port_name = ""
                try:
                    decl = node.declarator
                    if decl is not None:
                        toks = _identifier_tokens(decl)
                        if toks:
                            port_name = toks[0].valueText
                except Exception:
                    port_name = ""
                if port_name:
                    fp_path = f"{parent_path}.{port_name}"
                    _mark(nodes_list[node_offset + idx],
                          role="function_port",
                          name=port_name, path=fp_path,
                          attributes={
                              "direction": direction,
                              "data_type": dt_text,
                              "name": port_name,
                          })
                    _add_edge(graph, parent_gid, gid, "has_function_port")
                    # Intentionally NOT registered in name_index — port
                    # names collide across functions (``add.a`` vs
                    # ``sub.a``) and the cross-file index keys on bare
                    # path. Traversal via has_function_port edges is the
                    # supported query path.
        elif c == "AssertionItemPortSyntax":
            # S77 — promote one entry of the port-formal list of a
            # parameterised ``property`` / ``sequence`` / ``let`` as
            # role="assertion_item_port".  Parent is the enclosing
            # property / sequence / let scope on ``sva_decl_stack``
            # (pushed by the PropertyDeclaration / SequenceDeclaration /
            # LetDeclaration branches above).
            #
            # Layout (verified via SyntaxTree probe — pyslang exposes
            # data descriptors directly on AssertionItemPortSyntax):
            #
            #   .local         -- LocalKeyword token (empty when absent)
            #   .direction     -- Input/Output/InOut/Ref token (empty when
            #                     absent — many properties omit direction)
            #   .type          -- a SyntaxNode describing the data type
            #   .name          -- Identifier token carrying the port name
            #   .defaultValue  -- optional EqualsValueClause-style child
            #                     ("= <expr>") or None
            #
            # Direction is captured via the token's ``valueText`` (no regex
            # on source); ``local`` collapses to a boolean. ``has_default``
            # is the boolean presence of ``defaultValue``. The default
            # expression body itself stays in the BLOB stream (graph-as-
            # index, blob-as-detail).
            if state["sva_decl_stack"]:
                parent_gid, parent_path = state["sva_decl_stack"][-1]
            else:
                parent_gid, parent_path = None, ""
            if parent_gid is not None:
                # Direction token (Unknown / empty when absent).
                direction = ""
                try:
                    dir_tok = node.direction
                    if dir_tok is not None:
                        dv = dir_tok.valueText
                        if dv:
                            direction = dv
                except Exception:
                    direction = ""
                # Local qualifier — token is always present but valueText
                # is empty (kind == TokenKind.Unknown) when the source did
                # not write ``local``. Lift to a clean boolean.
                is_local = False
                try:
                    loc_tok = node.local
                    if loc_tok is not None and loc_tok.valueText == "local":
                        is_local = True
                except Exception:
                    is_local = False
                # Data type via the structural helper (handles dims/signing).
                dt_text = ""
                try:
                    type_node = node.type
                    if type_node is not None:
                        dt_text = _type_text_of(type_node).strip()
                except Exception:
                    dt_text = ""
                # Port name — pyslang surfaces ``.name`` directly as a
                # Token (not wrapped in a Declarator).
                port_name = ""
                try:
                    name_tok = node.name
                    if name_tok is not None:
                        port_name = name_tok.valueText
                except Exception:
                    port_name = ""
                # Default value presence.
                has_default = False
                try:
                    dv_node = node.defaultValue
                    if dv_node is not None:
                        has_default = True
                except Exception:
                    has_default = False
                if port_name:
                    aip_path = f"{parent_path}.{port_name}"
                    _mark(nodes_list[node_offset + idx],
                          role="assertion_item_port",
                          name=port_name, path=aip_path,
                          attributes={
                              "direction": direction,
                              "data_type": dt_text,
                              "name": port_name,
                              "local": is_local,
                              "has_default": has_default,
                          })
                    _add_edge(graph, parent_gid, gid,
                              "has_assertion_item_port")
                    # Intentionally NOT registered in name_index — port
                    # names collide across properties / sequences / lets
                    # (``p1.x`` vs ``p2.x``); traversal via the
                    # has_assertion_item_port edge is the supported query
                    # path.
        elif c == "PortDeclarationSyntax":
            # S55 — promote non-ANSI port body declarations
            # (``module m(a,b); input a; output [7:0] b; ...``). Distinct from
            # S1 ImplicitAnsiPort, which handles the ANSI inline form. Layout
            # (verified via SyntaxTree probe):
            #   SyntaxList                       -- leading attributes
            #   <Variable|Net|Interface>PortHeader
            #     <Input|Output|InOut|Ref>Keyword  (direction)
            #     [WireKeyword | NetType ...]
            #     ImplicitTypeSyntax / DataTypeSyntax (type + signing + dims)
            #   SeparatedList(DeclaratorSyntax, comma, ...)
            #   Semicolon
            #
            # Strategy: extract the direction token from the header, push a
            # frame onto ``port_decl_stack``; the DeclaratorSyntax branch
            # below consumes the frame to emit role="port" with the direction
            # attribute and a ``has_port`` edge from the enclosing module.
            # Registering each port name in ``port_names_by_module`` keeps the
            # in_data Declarator branch from re-promoting these as nets and
            # provides a stable guard for any future Declarator visitor.
            mod_gid, mname = _cur_module()
            direction: str | None = None
            if mod_gid is not None:
                _DIRECTION_TOKENS = {
                    "InputKeyword": "input",
                    "OutputKeyword": "output",
                    "InOutKeyword": "inout",
                    "RefKeyword": "ref",
                }
                for ch in node:
                    if ch is None or _is_token(ch):
                        continue
                    chkind = str(getattr(ch, "kind", "")).rsplit(".", 1)[-1]
                    if chkind not in {
                        "VariablePortHeader", "NetPortHeader",
                        "InterfacePortHeader", "InterconnectPortHeader",
                    }:
                        continue
                    for sub in ch:
                        if (sub is not None and _is_token(sub)
                                and _token_kind_name(sub) in _DIRECTION_TOKENS):
                            direction = _DIRECTION_TOKENS[_token_kind_name(sub)]
                            break
                    break
                state["port_decl_stack"].append({"direction": direction or ""})
        elif c == "DeclaratorSyntax":
            mod_gid, mname = _cur_module()
            ids = _identifier_tokens(node)
            # S55: when this Declarator is a child of a PortDeclaration
            # (non-ANSI port body), promote it as role="port" with the
            # direction attribute from the parent header. Register the name
            # in ``port_names_by_module`` so the in_data fall-through in the
            # net branch below excludes these names from net-promotion (the
            # same guard S1 ImplicitAnsiPort uses).
            if (state["port_decl_stack"] and mod_gid is not None and ids
                    and not state["class_stack"]):
                pname = ids[0].valueText
                ppath = f"{mname}.{pname}"
                frame = state["port_decl_stack"][-1]
                attrs = {"direction": frame["direction"]} if frame["direction"] else {}
                _mark(nodes_list[node_offset + idx], role="port",
                      name=pname, path=ppath,
                      attributes=attrs)
                _add_edge(graph, mod_gid, gid, "has_port")
                name_index[ppath] = gid
                port_names_by_module.setdefault(mname, set()).add(pname)
            # S26 declarator fan-out: when this Declarator is the 2nd+ name
            # under a ClassPropertyDeclaration (``int a, b, c;``), emit a
            # separate class_property node + has_class_property edge so each
            # variable name surfaces as a distinct queryable node. The first
            # declarator name is already promoted by the enclosing
            # ClassPropertyDeclaration branch above (canonical node).
            pending = state.get("class_property_pending")
            if (pending is not None
                    and ids
                    and ids[0].valueText in pending["names"]
                    and gid != pending["decl_gid"]):
                dname = ids[0].valueText
                # First declarator in the source order is the canonical node
                # already promoted on the ClassPropertyDeclaration itself;
                # skip it here to avoid duplicating the (cls_path).first edge.
                # We detect "first" by removing the name from the pending set
                # the first time we see it (the canonical promotion already
                # consumed it implicitly — track via a "seen" sub-set).
                seen = pending.setdefault("_seen", set())
                if dname not in seen:
                    seen.add(dname)
                    if len(seen) > 1:
                        # 2nd+ declarator: emit a sibling class_property node.
                        quals = pending["quals"]
                        attrs = {
                            "static": quals["static"],
                            "const": quals["const"],
                            "rand": quals["rand"],
                            "randc": quals["randc"],
                            "protected": quals["protected"],
                            "local": quals["local"],
                        }
                        ppath = f"{pending['cls_path']}.{dname}"
                        _mark(nodes_list[node_offset + idx],
                              role="class_property", name=dname, path=ppath,
                              attributes=attrs)
                        _add_edge(graph, pending["cls_gid"], gid,
                                  "has_class_property")
                        name_index[ppath] = gid
                # In either case the Declarator inside a class belongs to a
                # class property — do NOT fall through to net/param promotion.
            elif mod_gid is not None and not state["class_stack"]:
                if ids and state["in_port"] == 0:
                    dname = ids[0].valueText
                    dpath = f"{mname}.{dname}"
                    if state["in_typedef"] > 0 and state["typedef_stack"]:
                        td_gid, tname, tpath = state["typedef_stack"][-1]
                        epath = f"{tpath}.{dname}"
                        _mark(nodes_list[node_offset + idx], role="enum_value",
                              name=dname, path=epath)
                        _add_edge(graph, td_gid, gid, "has_enum_value",
                                  name=dname, typedef=tpath)
                        name_index[epath] = gid
                    elif state["in_param"] > 0 and state["in_function"] == 0:
                        _mark(nodes_list[node_offset + idx], role="param", name=dname, path=dpath)
                        _add_edge(graph, mod_gid, gid, "has_param")
                        name_index[dpath] = gid
                    elif (state["in_data"] > 0
                          and state["in_function"] == 0
                          and dname not in port_names_by_module.get(mname, set())):
                        _mark(nodes_list[node_offset + idx], role="net", name=dname, path=dpath)
                        _add_edge(graph, mod_gid, gid, "has_net")
                        name_index[dpath] = gid
                        # S54: when this Declarator is a child of a
                        # NetDeclaration, emit a ``groups_net`` edge from the
                        # net_decl group node to this net.
                        if state["net_decl_stack"]:
                            _add_edge(graph, state["net_decl_stack"][-1],
                                      gid, "groups_net")

        if pushed is not None:
            state[pushed] += 1
        # S26: scope ``class_property_pending`` to this declaration's subtree.
        pending_snapshot = None
        if c == "ClassPropertyDeclarationSyntax":
            pending_snapshot = state.get("class_property_pending")
        if not _is_token(node):
            try:
                children = list(node)
            except TypeError:
                children = []
            for ch in children:
                visit_pass1(ch)
        if c == "ClassPropertyDeclarationSyntax":
            # Restore (or clear) the pending pointer to whatever it was before
            # this declaration so nested class declarations do not leak
            # qualifier metadata to sibling subtrees.
            if pending_snapshot is None:
                state.pop("class_property_pending", None)
            else:
                state["class_property_pending"] = pending_snapshot
        if pushed is not None:
            state[pushed] -= 1
        if pushed == "in_typedef" and state["typedef_stack"]:
            state["typedef_stack"].pop()
        if pushed_covergroup and state["covergroup_stack"]:
            state["covergroup_stack"].pop()
        # S41: pop the coverpoint_stack entry pushed by the S23 Coverpoint branch.
        if pushed_coverpoint and state["coverpoint_stack"]:
            state["coverpoint_stack"].pop()
        if pushed_class and state["class_stack"]:
            state["class_stack"].pop()
        # S28: pop the checker_stack entry the CheckerDeclaration branch
        # pushed. ``popped_module`` was set True alongside the checker push,
        # so the module_stack pop below removes the synthetic checker scope.
        if c == "CheckerDeclarationSyntax" and state["checker_stack"]:
            state["checker_stack"].pop()
        # S54: pop net_decl_stack alongside its in_data push (only when the
        # NetDeclaration branch actually appended a group node — detected by
        # ``pushed == "in_data"`` *and* the kind being NetDeclarationSyntax).
        if c == "NetDeclarationSyntax" and pushed == "in_data" and state["net_decl_stack"]:
            state["net_decl_stack"].pop()
        # S55: pop port_decl_stack frame pushed by the PortDeclarationSyntax
        # branch above so the frame is scoped to this declaration's subtree.
        if c == "PortDeclarationSyntax" and state["port_decl_stack"]:
            state["port_decl_stack"].pop()
        # S56: pop extern_method_stack frame pushed by the
        # ExternInterfaceMethodSyntax branch so the marker is scoped to its
        # own subtree (the FunctionPrototype child is visited *before* this
        # pop runs because the recursion above already returned).
        if c == "ExternInterfaceMethodSyntax" and state["extern_method_stack"]:
            state["extern_method_stack"].pop()
        # S57: pop sva_decl_stack frame pushed by the Property /
        # Sequence declaration branches so that LocalVariableDeclaration
        # children of these constructs resolve their parent against the
        # correct enclosing scope and sibling subtrees do not leak.
        # S77 extends this to LetDeclarationSyntax so that AssertionItemPort
        # children of a parameterised let also resolve their parent against
        # the let's path.
        if (c in ("PropertyDeclarationSyntax", "SequenceDeclarationSyntax",
                  "LetDeclarationSyntax")
                and state["sva_decl_stack"]):
            state["sva_decl_stack"].pop()
        # S58: pop struct_union_stack frame pushed by the TypedefDeclaration
        # branch when its body is a StructType / UnionType. The local
        # ``pushed_struct_union`` flag is True only on that path, keeping the
        # pop symmetric with the push.
        if (c == "TypedefDeclarationSyntax"
                and pushed_struct_union
                and state["struct_union_stack"]):
            state["struct_union_stack"].pop()
        # S59: pop clocking_stack frame pushed by the ClockingDeclaration
        # branch above. The local ``pushed_clocking`` flag is True only on
        # that path (including the sentinel push when the clocking itself
        # was not promoted), keeping the pop symmetric with the push.
        if (c == "ClockingDeclarationSyntax"
                and pushed_clocking
                and state["clocking_stack"]):
            state["clocking_stack"].pop()
        # S67: pop port_ref_parent_stack frame pushed by S65
        # ExplicitNonAnsiPort or S66 ImplicitNonAnsiPort branches above.
        # The push is unconditional in those branches, so the pop is too.
        if (c in ("ExplicitNonAnsiPortSyntax", "ImplicitNonAnsiPortSyntax")
                and state["port_ref_parent_stack"]):
            state["port_ref_parent_stack"].pop()
        # S68: pop port_concat_stack frame pushed by PortConcatenation
        # branch above. The push is unconditional in that branch, so the
        # pop is too.
        if (c == "PortConcatenationSyntax"
                and state["port_concat_stack"]):
            state["port_concat_stack"].pop()
        # S74: pop function_stack frame pushed by the FunctionDeclaration
        # (module-scope only), ClassMethodDeclaration / ClassMethodPrototype,
        # or extern-FunctionPrototype (S56) branches above. The local
        # ``pushed_function`` flag is True only on those paths, so the pop
        # stays symmetric with the push.
        if pushed_function and state["function_stack"]:
            state["function_stack"].pop()
        if popped_module:
            state["module_stack"].pop()

    if phase in (None, "pass1"):
        visit_pass1(syntax_tree.root)
        # S29 post-pass: resolve deferred ``declares`` edges from extern
        # decls to the full module / interface / program body using the
        # now-complete name_index. Skip entries whose target doesn't exist
        # (the body is in a different compilation, or simply absent).
        for ext_gid, ext_name, ext_kind in extern_pending:
            tgt = name_index.get(ext_name)
            if tgt is not None and tgt != ext_gid:
                _add_edge(graph, ext_gid, tgt, "declares", name=ext_name,
                          kind=ext_kind)
        # S28 / S79 post-pass: drain deferred ``of_checker`` edges for
        # procedural-scope CheckerInstantiation entries whose checker
        # declaration was not yet in name_index at instantiation time.
        for inst_gid, ctype in checker_inst_pending:
            tgt = name_index.get("checker:" + ctype)
            if tgt is not None and tgt != inst_gid:
                _add_edge(graph, inst_gid, tgt, "of_checker", name=ctype)
    if phase == "pass1":
        return

    # S60 post-pass1 drain — resolve VirtualInterfaceType references now that
    # every tree has finished pass1 (so name_index has every interface and
    # modport registered, including cross-file ones). Drain the pending list
    # so subsequent pass2 calls (one per tree in build_kg) don't re-emit.
    s60_pending = graph.pop("_s60_pending", None)
    if s60_pending:
        for src_gid, iface_name, modport_name in s60_pending:
            unresolved = False
            if modport_name is not None:
                mport_path = f"{iface_name}.{modport_name}"
                tgt_id = name_index.get(mport_path)
                if tgt_id is None:
                    tgt_id = (name_index.get(f"interface:{iface_name}")
                              or name_index.get(iface_name))
                    if tgt_id is None:
                        tgt_id = f"_unresolved.{iface_name}"
                        unresolved = True
            else:
                tgt_id = (name_index.get(f"interface:{iface_name}")
                          or name_index.get(iface_name))
                if tgt_id is None:
                    tgt_id = f"_unresolved.{iface_name}"
                    unresolved = True
            payload: dict = {"modport": modport_name}
            if unresolved:
                payload["unresolved"] = True
            _add_edge(graph, src_gid, tgt_id, "references_interface", **payload)

    # Pass 2: rule dispatch via RULE_TABLE.
    state2 = {"idx": 0, "module_stack": [], "in_function": 0,
              "in_generate": 0, "in_bind": 0}

    def _cur_module2():
        return state2["module_stack"][-1] if state2["module_stack"] else (None, "")

    def visit_pass2(node):
        idx = state2["idx"]
        state2["idx"] += 1
        c = _cls(node)
        gid = nodes_list[node_offset + idx]["id"]
        popped = False
        entered_fn = False
        entered_gen = False
        if c == "ModuleDeclarationSyntax":
            mname = _module_name_of(node)
            state2["module_stack"].append((gid, mname))
            popped = True
        elif c == "AnonymousProgramSyntax":
            # S49 — mirror pass-1 push so pass-2 child rules (S6/S33/etc.)
            # see the anonymous program as their enclosing module scope.
            kw_tok2 = getattr(node, "keyword", None)
            kw_off2 = 0
            if kw_tok2 is not None:
                loc2 = getattr(kw_tok2, "location", None)
                if loc2 is not None:
                    kw_off2 = getattr(loc2, "offset", 0) or 0
            aname2 = f"__anon_program_{kw_off2}__"
            state2["module_stack"].append((gid, aname2))
            popped = True
        if c == "FunctionDeclarationSyntax":
            state2["in_function"] += 1
            entered_fn = True
        if c == "LoopGenerateSyntax":
            entered_gen = True
        entered_bind = False
        if c == "BindDirectiveSyntax":
            entered_bind = True
        mod_gid, mname = _cur_module2()
        scope = module_scope_by_name.get(mname)
        scope_path = mname
        if state2["in_function"] == 0:
            # Look up the active rule by the node's pyslang kind. Only nodes
            # whose kind has an entry in RULE_TABLE are dispatched; the rule
            # function itself decides whether to act (active rules) or no-op
            # (metadata stubs).
            kind = getattr(node, "kind", None)
            fn = RULE_TABLE.get(kind) if kind is not None else None
            if fn is not None and _is_active(fn):
                # Walker-context guards: S6 must not fire inside generate or
                # bind subtrees; S6 also gets module_gid as the parent.
                if fn is rule_s6:
                    if state2["in_generate"] == 0 and state2["in_bind"] == 0:
                        fn(graph, node, gid, nodes_list[node_offset + idx],
                           scope, name_index, leaks, scope_path, module_gid=mod_gid)
                elif fn is rule_s12:
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path, module_gid=mod_gid)
                elif fn is rule_s13:
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path)
                elif fn is rule_s33:
                    # S33 — gate-level primitive instantiation. Mirrors S6's
                    # walker-context guards: skip inside generate / bind
                    # subtrees, pass module_gid as the containment parent.
                    if state2["in_generate"] == 0 and state2["in_bind"] == 0:
                        fn(graph, node, gid, nodes_list[node_offset + idx],
                           scope, name_index, leaks, scope_path,
                           module_gid=mod_gid)
                elif fn is rule_s50:
                    # S50 — PackageImportItem needs the enclosing module gid
                    # to emit the imports_item edge from the correct source.
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path, module_gid=mod_gid)
                elif fn is rule_s51:
                    # S51 — PackageExportAllDeclaration (export *::*;) emits a
                    # self-loop exports_all edge from the enclosing scope.
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path, module_gid=mod_gid)
                elif fn is rule_s53:
                    # S53 — NetTypeDeclaration needs the enclosing module/package
                    # gid and scope_path to emit the has_nettype edge and build
                    # the path key.
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path, module_gid=mod_gid)
                elif fn is rule_s3_or_s8 or getattr(fn, "__rule_id__", None) == "S8":
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path)
                else:
                    fn(graph, node, gid, nodes_list[node_offset + idx],
                       scope, name_index, leaks, scope_path)
        if entered_gen:
            state2["in_generate"] += 1
        if entered_bind:
            state2["in_bind"] += 1
        if not _is_token(node):
            try:
                children = list(node)
            except TypeError:
                children = []
            for ch in children:
                visit_pass2(ch)
        if entered_gen:
            state2["in_generate"] -= 1
        if entered_bind:
            state2["in_bind"] -= 1
        if entered_fn:
            state2["in_function"] -= 1
        if popped:
            state2["module_stack"].pop()

    visit_pass2(syntax_tree.root)
    graph["semantic_name_index"] = name_index

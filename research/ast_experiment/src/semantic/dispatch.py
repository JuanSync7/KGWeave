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
    _assertion_label_of,
    _class_modifiers_of,
    _class_name_of,
    _clocking_modifier_of,
    _clocking_name_of,
    _cls,
    _cover_cross_members,
    _covergroup_has_clocking_event,
    _covergroup_name_of,
    _coverpoint_expression,
    _function_name_of,
    _identifier_tokens,
    _is_token,
    _lhs_target_name,
    _module_name_of,
    _named_label_of,
    _property_name_of,
    _sequence_name_of,
    _token_kind_name,
    _typedef_name_of,
)
from .rules import RULE_TABLE
from .rules.dataflow import rule_s3_or_s8
from .rules.generate import rule_s12
from .rules.instantiation import rule_s6, rule_s13


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
    try:
        children = list(node)
    except TypeError:
        return False
    for ch in children:
        if ch is None or _is_token(ch):
            continue
        if _cls(ch) == "DeferredAssertionSyntax":
            return True
    return False


# Active pass-2 rules — these are the only RULE_TABLE entries whose callable
# actually has side effects on the graph. All others are metadata stubs.
_PASS2_ACTIVE: set = set()
# Populated lazily — we resolve by checking the function's __rule_id__ against
# a known-active set.
_ACTIVE_RULE_IDS = {"S2", "S3", "S4", "S5", "S6", "S8", "S12a", "S13"}


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
        "in_param": 0,
        "in_data": 0,
        "in_port": 0,
        "in_typedef": 0,
        "in_function": 0,
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

        if c == "ModuleDeclarationSyntax":
            kind_name = str(getattr(node, "kind", "")).rsplit(".", 1)[-1]
            mname = _module_name_of(node)
            state["module_stack"].append((gid, mname))
            popped_module = True
            if kind_name == "PackageDeclaration":
                role_name = "package"
                key_prefix = "package:"
            elif kind_name == "InterfaceDeclaration":
                role_name = "interface"
                key_prefix = "interface:"
            else:
                role_name = "module"
                key_prefix = "module:"
            _mark(nodes_list[node_offset + idx], role=role_name, name=mname, path=mname)
            name_index[key_prefix + mname] = gid
            name_index[mname] = gid
            port_names_by_module.setdefault(mname, set())
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
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                fname = _function_name_of(node)
                if fname:
                    fpath = f"{mname}.{fname}"
                    _mark(nodes_list[node_offset + idx], role="function",
                          name=fname, path=fpath)
                    _add_edge(graph, mod_gid, gid, "has_function")
                    name_index[fpath] = gid
            pushed = "in_function"
        elif c == "PropertyDeclarationSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                pname = _property_name_of(node)
                if pname:
                    ppath = f"{mname}.{pname}"
                    _mark(nodes_list[node_offset + idx], role="property",
                          name=pname, path=ppath)
                    _add_edge(graph, mod_gid, gid, "has_property")
                    name_index[ppath] = gid
        elif c == "SequenceDeclarationSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                sname = _sequence_name_of(node)
                if sname:
                    spath = f"{mname}.{sname}"
                    _mark(nodes_list[node_offset + idx], role="sequence",
                          name=sname, path=spath)
                    _add_edge(graph, mod_gid, gid, "has_sequence")
                    name_index[spath] = gid
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
                deferred = _has_deferred_modifier(node)
                _mark(nodes_list[node_offset + idx], role="assertion",
                      name=label, path=apath,
                      attributes={"kind": kind_label, "deferred": deferred})
                _add_edge(graph, mod_gid, gid, "has_assertion")
                name_index[apath] = gid
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
                _mark(nodes_list[node_offset + idx], role="class",
                      name=cname, path=cpath, attributes=attrs)
                if mod_gid is not None:
                    _add_edge(graph, mod_gid, gid, "has_class")
                name_index[cpath] = gid
                state["class_stack"].append((gid, cpath))
                pushed_class = True
        elif c == "TypedefDeclarationSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                tname = _typedef_name_of(node)
                if tname:
                    tpath = f"{mname}.{tname}"
                    _mark(nodes_list[node_offset + idx], role="typedef",
                          name=tname, path=tpath)
                    _add_edge(graph, mod_gid, gid, "has_typedef")
                    name_index[tpath] = gid
                    state["typedef_stack"].append((gid, tname, tpath))
                    pushed = "in_typedef"
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
        elif c == "ParameterDeclarationSyntax":
            pushed = "in_param"
        elif c == "DataDeclarationSyntax":
            pushed = "in_data"
        elif c == "DeclaratorSyntax":
            mod_gid, mname = _cur_module()
            if mod_gid is not None:
                ids = _identifier_tokens(node)
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

        if pushed is not None:
            state[pushed] += 1
        if not _is_token(node):
            try:
                children = list(node)
            except TypeError:
                children = []
            for ch in children:
                visit_pass1(ch)
        if pushed is not None:
            state[pushed] -= 1
        if pushed == "in_typedef" and state["typedef_stack"]:
            state["typedef_stack"].pop()
        if pushed_covergroup and state["covergroup_stack"]:
            state["covergroup_stack"].pop()
        if pushed_class and state["class_stack"]:
            state["class_stack"].pop()
        if popped_module:
            state["module_stack"].pop()

    if phase in (None, "pass1"):
        visit_pass1(syntax_tree.root)
    if phase == "pass1":
        return

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

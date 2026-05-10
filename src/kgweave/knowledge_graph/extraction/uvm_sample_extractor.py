# @summary
# Parser-only UVM .sample() callsite + wrapper extractor. Walks SystemVerilog
# files under a directory using pyslang's SyntaxTree (NOT elaboration — UVM
# testbench files extend uvm_pkg classes that aren't in our parse set, so
# elaboration would fail). Two passes: (1) discover wrapper functions
# `cg_X_sample(...)` whose body invokes `<cg>_inst.sample(...)`, binding
# wrapper-name -> covergroup-name. (2) discover callsites of
# `<inst>.<wrapper>(...)` or direct `<cg>_inst.sample(...)`. Closes the
# RTL -> Covergroup_SV -> sample callsite audit chain.
# Exports: UVMSampleExtractor, UVM_SAMPLE_SOURCE
# Deps: pathlib, typing, pyslang, kgweave.knowledge_graph.common
# @end-summary
"""UVM sample-callsite extractor.

Phase-1 audit hop: every Covergroup_SV must have at least one ``samples_covergroup``
edge from a discovered ``UVMSampleCallsite`` (or via a ``UVMSampleWrapper``)
or it is an orphan covergroup that is structurally dead in the testbench.

Why parser-only? UVM testbench files (``aes_scoreboard.sv`` etc.) inherit
from ``cip_base_env`` / ``uvm_scoreboard`` whose definitions live outside
our parse set. ``pyslang.SyntaxTree.fromFile`` runs *only* the parser and
returns a syntax tree even when symbols are unresolvable, which is enough
for our textual pattern (single-statement invocations).

Why two passes? Wrappers (defined in ``aes_cov_if.sv``) and their callsites
(in ``aes_scoreboard.sv``) live in different files; we must walk the whole
directory once to learn wrapper -> covergroup bindings before we can resolve
callsites that go through the wrapper.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pyslang  # parser-only — see module docstring.

from kgweave.knowledge_graph.common import (
    Entity,
    ExtractionResult,
    Triple,
)

__all__ = ["UVMSampleExtractor", "UVM_SAMPLE_SOURCE"]

UVM_SAMPLE_SOURCE = "uvm_sample"

_logger = logging.getLogger("rag.knowledge_graph.uvm_sample")


# ---------------------------------------------------------------------------
# AST traversal helpers
# ---------------------------------------------------------------------------

def _iter_descendants(node: Any):
    """Yield every descendant of a pyslang SyntaxNode (depth-first)."""
    yield node
    try:
        for child in node:
            if child is None:
                continue
            # Skip pure tokens (TokenKind.*) -- only descend SyntaxNodes.
            kind = getattr(child, "kind", None)
            if kind is None:
                continue
            kind_str = str(kind)
            if not kind_str.startswith("SyntaxKind."):
                continue
            yield from _iter_descendants(child)
    except TypeError:
        return


def _kind_name(node: Any) -> str:
    k = getattr(node, "kind", None)
    if k is None:
        return ""
    s = str(k)
    return s.split(".", 1)[1] if "." in s else s


def _node_text(node: Any) -> str:
    """Compact textual form of a SyntaxNode, with whitespace squeezed."""
    try:
        raw = str(node)
    except Exception:
        return ""
    return " ".join(raw.split())


# ---------------------------------------------------------------------------
# InvocationExpression decomposition
# ---------------------------------------------------------------------------

def _decompose_invocation(inv: Any) -> Tuple[str, str, List[str], List[str]]:
    """Return (receiver_text, method_name, dotted_components, args_text).

    ``receiver_text`` is the textual form of the scoped name with the trailing
    ``.method`` stripped (or empty for a bare-name invocation).
    ``method_name`` is the right-most identifier of the scoped name.
    ``dotted_components`` is the full dotted chain split on ``.`` so callers
    can scan for ``_inst`` markers anywhere in the path.
    ``args_text`` is the textual form of each ordered argument expression.
    """
    receiver_text = ""
    method_name = ""
    dotted: List[str] = []
    args: List[str] = []

    # Children: ScopedName / IdentifierName, possibly an attribute SyntaxList,
    # then ArgumentList.
    for child in inv:
        if child is None:
            continue
        ck = _kind_name(child)
        if ck == "ScopedName":
            full = _node_text(child)
            # Split on '.' tokens at top level. The textual form already
            # collapsed whitespace, but spaces around '.' may persist.
            parts = [p.strip() for p in full.replace(" .", ".").replace(". ", ".").split(".")]
            parts = [p for p in parts if p]
            dotted = parts
            if parts:
                method_name = parts[-1]
                receiver_text = ".".join(parts[:-1])
        elif ck == "IdentifierName" and not method_name:
            method_name = _node_text(child)
            dotted = [method_name]
        elif ck == "ArgumentList":
            for sub in child:
                if sub is None:
                    continue
                if _kind_name(sub) == "SeparatedList":
                    for arg in sub:
                        if arg is None:
                            continue
                        if _kind_name(arg) == "OrderedArgument":
                            args.append(_node_text(arg))
    return receiver_text, method_name, dotted, args


def _strip_inst_suffix(name: str) -> Optional[str]:
    """Return the covergroup name if ``name`` looks like a covergroup instance.

    Convention from slang-fcov-macros: the covergroup variable is named
    ``<cg_name>_inst`` (e.g. ``aes_ctrl_cg_inst`` -> ``aes_ctrl_cg``).
    """
    if not name:
        return None
    # Take the bare identifier without leading dotted prefix.
    tail = name.split(".")[-1]
    if tail.endswith("_cg_inst"):
        return tail[: -len("_inst")]
    if tail.endswith("_inst") and "_cg_" in tail:
        return tail[: -len("_inst")]
    if tail.endswith("_inst"):
        # Fallback: strip _inst even without _cg marker.
        return tail[: -len("_inst")]
    return None


def _find_inst_in_chain(dotted: List[str]) -> Optional[str]:
    """Scan a dotted invocation chain for a ``<cg>_inst`` component.

    Direct callsites look like ``cov_if.aes_ctrl_cg_inst.sample`` — we walk
    the chain and return the cg name from the first ``_inst``-suffixed
    component we find.
    """
    for comp in dotted:
        if comp.endswith("_inst"):
            stem = _strip_inst_suffix(comp)
            if stem:
                return stem
    return None


# ---------------------------------------------------------------------------
# Function/task declaration parsing
# ---------------------------------------------------------------------------

def _function_signature(decl: Any) -> Tuple[str, List[str]]:
    """Return (function_name, [param_name, ...]) for a Function/TaskDeclaration."""
    fname = ""
    params: List[str] = []
    for child in decl:
        if child is None:
            continue
        ck = _kind_name(child)
        if ck in ("FunctionPrototype",):
            for sub in child:
                if sub is None:
                    continue
                sk = _kind_name(sub)
                if sk == "IdentifierName" and not fname:
                    fname = _node_text(sub)
                elif sk == "FunctionPortList":
                    for fpl_child in sub:
                        if fpl_child is None:
                            continue
                        if _kind_name(fpl_child) == "SeparatedList":
                            for port in fpl_child:
                                if port is None:
                                    continue
                                if _kind_name(port) in ("FunctionPort",):
                                    pname = _extract_declarator_name(port)
                                    if pname:
                                        params.append(pname)
    return fname, params


def _extract_declarator_name(port_node: Any) -> str:
    """Pull the param name out of a FunctionPort's Declarator child."""
    for child in port_node:
        if child is None:
            continue
        if _kind_name(child) == "Declarator":
            for sub in child:
                if sub is None:
                    continue
                tk = getattr(sub, "kind", None)
                if tk is not None and str(tk) == "TokenKind.Identifier":
                    return _node_text(sub).strip()
    return ""


# ---------------------------------------------------------------------------
# Source-location helper
# ---------------------------------------------------------------------------

def _node_location(node: Any, sm: Any) -> Tuple[int, int]:
    """Return (line, col) for the start of ``node``; (0, 0) on failure."""
    try:
        sr = node.sourceRange
        start = sr.start
        return sm.getLineNumber(start), sm.getColumnNumber(start)
    except Exception:
        return 0, 0


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class _WrapperRecord:
    __slots__ = ("file_basename", "wrapper_name", "covergroup_name", "params")

    def __init__(
        self,
        file_basename: str,
        wrapper_name: str,
        covergroup_name: str,
        params: List[str],
    ) -> None:
        self.file_basename = file_basename
        self.wrapper_name = wrapper_name
        self.covergroup_name = covergroup_name
        self.params = list(params)

    @property
    def entity_name(self) -> str:
        return f"{self.file_basename}::{self.wrapper_name}"


class UVMSampleExtractor:
    """Walk a UVM testbench directory and emit sample-callsite audit nodes.

    The single public entry point is :meth:`extract_directory`. The class also
    exposes :meth:`extract` for API symmetry with other extractors (the
    ``source`` argument is treated as a directory path; ``text`` is ignored).
    """

    @property
    def name(self) -> str:
        return UVM_SAMPLE_SOURCE

    def __init__(
        self,
        known_covergroups: Optional[Iterable[str]] = None,
        known_sample_args: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
    ) -> None:
        self._schema = schema
        self._config = config
        # Map bare cg name (e.g. ``aes_ctrl_cg``) -> canonical name
        # (e.g. ``aes_cov_if.aes_ctrl_cg``). Multiple canonical names can map
        # back to the same bare stem in pathological cases — keep the last.
        self._cg_by_stem: Dict[str, str] = {}
        self._cg_canonical: Set[str] = set()
        for canonical in known_covergroups or ():
            if not canonical:
                continue
            self._cg_canonical.add(canonical)
            stem = canonical.split(".")[-1]
            self._cg_by_stem[stem] = canonical
        # Set of known SampleArg canonical names (e.g.
        # ``aes_cov_if.aes_ctrl_cg.arg.aes_op``). Used to emit
        # ``binds_to_arg`` edges when wrapper params align positionally.
        self._sample_args: Set[str] = set(known_sample_args or ())

    # -- public API ----------------------------------------------------------

    def extract(self, text: str = "", source: str = "") -> ExtractionResult:
        """API-compatibility shim — delegates to :meth:`extract_directory`."""
        return self.extract_directory(source) if source else ExtractionResult()

    def extract_directory(
        self,
        uvm_dir: Any,
        *,
        known_covergroups: Optional[Iterable[str]] = None,
    ) -> ExtractionResult:
        """Walk ``uvm_dir`` for ``*.sv`` files and emit callsite/wrapper KG.

        ``uvm_dir`` may be a single ``Path``/``str`` or an iterable of paths
        (so callers can fold ``dv/env/`` and ``dv/cov/`` into a single pass —
        wrappers in cov/ must be visible when scanning env/ for callsites).

        ``known_covergroups`` here augments the constructor-supplied set
        (mirrors how RagWeave callers pass it inline at the demo step).
        """
        if known_covergroups:
            for canonical in known_covergroups:
                if not canonical:
                    continue
                self._cg_canonical.add(canonical)
                self._cg_by_stem[canonical.split(".")[-1]] = canonical

        if not uvm_dir:
            return ExtractionResult()
        # Normalise to a list of root directories.
        if isinstance(uvm_dir, (str, Path)):
            roots = [Path(uvm_dir)]
        else:
            roots = [Path(p) for p in uvm_dir if p]

        sv_files: List[Path] = []
        for root in roots:
            if not root.is_dir():
                _logger.warning("UVM directory not found: %s", root)
                continue
            sv_files.extend(sorted(root.rglob("*.sv")))
        if not sv_files:
            return ExtractionResult()

        # Pre-parse every file once and reuse the trees across both passes.
        parsed: List[Tuple[Path, Any]] = []
        for sv_path in sv_files:
            tree = self._parse(sv_path)
            if tree is not None:
                parsed.append((sv_path, tree))

        wrappers = self._pass1_wrappers(parsed)
        return self._pass2_callsites(parsed, wrappers)

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _parse(sv_path: Path) -> Optional[Any]:
        try:
            return pyslang.SyntaxTree.fromFile(str(sv_path))
        except Exception as exc:  # noqa: BLE001 — parser failure is per-file
            _logger.debug("pyslang parse failed for %s: %s", sv_path, exc)
            return None

    def _pass1_wrappers(
        self,
        parsed: List[Tuple[Path, Any]],
    ) -> Dict[str, _WrapperRecord]:
        """Pass 1: discover wrapper functions/tasks calling ``<cg>_inst.sample``.

        Returns a mapping from bare wrapper name -> wrapper record. When two
        files define the same wrapper name we keep the first; both will still
        be emitted as separate ``UVMSampleWrapper`` entities in pass 2.
        """
        wrappers: Dict[str, _WrapperRecord] = {}
        for sv_path, tree in parsed:
            for node in _iter_descendants(tree.root):
                kind = _kind_name(node)
                if kind not in ("FunctionDeclaration", "TaskDeclaration"):
                    continue
                fname, params = _function_signature(node)
                if not fname:
                    continue
                # Scan body for the inner .sample() invocation.
                cg_stem = self._find_inner_sample_target(node)
                if not cg_stem:
                    continue
                rec = _WrapperRecord(
                    file_basename=sv_path.name,
                    wrapper_name=fname,
                    covergroup_name=cg_stem,
                    params=params,
                )
                wrappers.setdefault(fname, rec)
        return wrappers

    @staticmethod
    def _find_inner_sample_target(decl: Any) -> Optional[str]:
        for inner in _iter_descendants(decl):
            if _kind_name(inner) != "InvocationExpression":
                continue
            _recv, method, dotted, _args = _decompose_invocation(inner)
            if method != "sample":
                continue
            # The receiver should end in `_inst`. Scan dotted chain.
            stem = _find_inst_in_chain(dotted[:-1] if dotted else [])
            if stem:
                return stem
        return None

    def _pass2_callsites(
        self,
        parsed: List[Tuple[Path, Any]],
        wrappers: Dict[str, _WrapperRecord],
    ) -> ExtractionResult:
        entities: List[Entity] = []
        triples: List[Triple] = []
        # Track wrapper entity emission (one per (file, wrapper_name)).
        emitted_wrappers: Set[str] = set()
        # Track callsite entity emission (one per (file, line, col)).
        emitted_callsites: Set[str] = set()

        # Emit UVMSampleWrapper entities + wraps_covergroup edges first so
        # callsite-side via_wrapper edges resolve to entities that exist.
        for rec in wrappers.values():
            wrapper_ent_name = rec.entity_name
            if wrapper_ent_name in emitted_wrappers:
                continue
            emitted_wrappers.add(wrapper_ent_name)
            cg_canonical = self._cg_by_stem.get(rec.covergroup_name, rec.covergroup_name)
            aliases = [
                f"inner_covergroup={cg_canonical}",
                f"param_count={len(rec.params)}",
                f"wrapper_name={rec.wrapper_name}",
            ]
            entities.append(Entity(
                name=wrapper_ent_name,
                type="UVMSampleWrapper",
                aliases=aliases,
                extractor_source=[UVM_SAMPLE_SOURCE],
                layer=UVM_SAMPLE_SOURCE,
            ))
            triples.append(Triple(
                subject=wrapper_ent_name,
                predicate="wraps_covergroup",
                object=cg_canonical,
                extractor_source=UVM_SAMPLE_SOURCE,
                evidence_span=f"function {rec.wrapper_name} -> {rec.covergroup_name}_inst.sample",
                layer=UVM_SAMPLE_SOURCE,
            ))

        # Walk every file again for callsites.
        for sv_path, tree in parsed:
            sm = tree.sourceManager
            file_basename = sv_path.name
            for node in _iter_descendants(tree.root):
                if _kind_name(node) != "InvocationExpression":
                    continue
                receiver, method, dotted, args = _decompose_invocation(node)
                if not method:
                    continue

                # Two cases:
                #   (a) wrapper call -- method is a known wrapper name
                #   (b) direct call  -- method == 'sample' and chain has _inst
                wrapper_rec: Optional[_WrapperRecord] = wrappers.get(method)
                cg_stem: Optional[str] = None
                if wrapper_rec is not None:
                    cg_stem = wrapper_rec.covergroup_name
                elif method == "sample":
                    cg_stem = _find_inst_in_chain(dotted[:-1] if dotted else [])
                else:
                    continue

                # Skip the wrapper-definition self-call inside aes_cov_if.sv:
                # the inner `<cg>_inst.sample(...)` IS the wrapper body, not
                # a callsite from the testbench. We detect this by checking
                # whether the enclosing file defines a wrapper with the same
                # cg_stem (best-effort heuristic — wrappers and direct
                # callsites in the same file are rare in practice).
                if (
                    method == "sample"
                    and wrapper_rec is None
                    and cg_stem
                    and self._is_inside_wrapper_for_cg(sv_path, wrappers, cg_stem)
                ):
                    continue

                line, col = _node_location(node, sm)
                callsite_name = f"{file_basename}::{line}::{col}"
                if callsite_name in emitted_callsites:
                    continue
                emitted_callsites.add(callsite_name)

                expr_text = _node_text(node)
                aliases = [f"expression_text={expr_text}"]
                if wrapper_rec is not None:
                    aliases.append(f"wrapper_name={wrapper_rec.wrapper_name}")
                entities.append(Entity(
                    name=callsite_name,
                    type="UVMSampleCallsite",
                    sources=[str(sv_path)],
                    aliases=aliases,
                    extractor_source=[UVM_SAMPLE_SOURCE],
                    layer=UVM_SAMPLE_SOURCE,
                ))

                # samples_covergroup edge — fuse to canonical Covergroup_SV
                # name when known, else emit the bare stem (audit signal).
                cg_target = self._cg_by_stem.get(cg_stem or "", cg_stem or "")
                if cg_target:
                    triples.append(Triple(
                        subject=callsite_name,
                        predicate="samples_covergroup",
                        object=cg_target,
                        source=str(sv_path),
                        extractor_source=UVM_SAMPLE_SOURCE,
                        evidence_span=expr_text,
                        layer=UVM_SAMPLE_SOURCE,
                    ))

                # defined_in_uvm_file edge to a SV_File node (fuses to
                # DVTestRealization output if present, else surfaces a new
                # SV_File entity here).
                triples.append(Triple(
                    subject=callsite_name,
                    predicate="defined_in_uvm_file",
                    object=file_basename,
                    source=str(sv_path),
                    extractor_source=UVM_SAMPLE_SOURCE,
                    evidence_span=f"line {line}:{col}",
                    layer=UVM_SAMPLE_SOURCE,
                ))
                # Emit the SV_File entity as well so the edge has a target
                # node when this file isn't already in the graph (e.g.
                # aes_scoreboard.sv lives outside dv/tests/).
                entities.append(Entity(
                    name=file_basename,
                    type="SV_File",
                    sources=[str(sv_path)],
                    extractor_source=[UVM_SAMPLE_SOURCE],
                    layer=UVM_SAMPLE_SOURCE,
                ))

                if wrapper_rec is not None:
                    triples.append(Triple(
                        subject=callsite_name,
                        predicate="via_wrapper",
                        object=wrapper_rec.entity_name,
                        source=str(sv_path),
                        extractor_source=UVM_SAMPLE_SOURCE,
                        evidence_span=f"calls {wrapper_rec.wrapper_name}",
                        layer=UVM_SAMPLE_SOURCE,
                    ))

                # Per-argument expressions + composition edges.
                for idx, arg_text in enumerate(args):
                    arg_name = f"{callsite_name}.arg{idx}"
                    entities.append(Entity(
                        name=arg_name,
                        type="UVMSampleArgExpr",
                        sources=[str(sv_path)],
                        aliases=[f"expression={arg_text}", f"index={idx}"],
                        extractor_source=[UVM_SAMPLE_SOURCE],
                        layer=UVM_SAMPLE_SOURCE,
                    ))
                    triples.append(Triple(
                        subject=callsite_name,
                        predicate="passes_arg",
                        object=arg_name,
                        source=str(sv_path),
                        extractor_source=UVM_SAMPLE_SOURCE,
                        evidence_span=arg_text,
                        layer=UVM_SAMPLE_SOURCE,
                    ))
                    # binds_to_arg: positional alignment with wrapper params
                    # -> Covergroup_SampleArg entity (Gap #2 emits these).
                    if (
                        wrapper_rec is not None
                        and idx < len(wrapper_rec.params)
                        and cg_target
                    ):
                        candidate = (
                            f"{cg_target}.arg.{wrapper_rec.params[idx]}"
                        )
                        if candidate in self._sample_args:
                            triples.append(Triple(
                                subject=arg_name,
                                predicate="binds_to_arg",
                                object=candidate,
                                source=str(sv_path),
                                extractor_source=UVM_SAMPLE_SOURCE,
                                evidence_span=(
                                    f"{wrapper_rec.wrapper_name} param "
                                    f"{wrapper_rec.params[idx]}"
                                ),
                                layer=UVM_SAMPLE_SOURCE,
                            ))

        return ExtractionResult(entities=entities, triples=triples)

    @staticmethod
    def _is_inside_wrapper_for_cg(
        sv_path: Path,
        wrappers: Dict[str, _WrapperRecord],
        cg_stem: str,
    ) -> bool:
        """True if ``sv_path`` defines any wrapper whose cg matches ``cg_stem``.

        Heuristic: the inner ``<cg>_inst.sample(...)`` inside a wrapper
        definition lives in the SAME file as the wrapper. Suppressing direct
        callsites in those files prevents double-counting (one for the
        wrapper-self-call, one for every external testbench call).
        """
        target = sv_path.name
        for rec in wrappers.values():
            if rec.file_basename == target and rec.covergroup_name == cg_stem:
                return True
        return False

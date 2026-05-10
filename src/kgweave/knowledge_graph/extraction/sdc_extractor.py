# @summary
# SDC (Synopsys Design Constraints) extractor.
# Parses .sdc/.tcl/.xdc timing-constraints files into ClockConstraint /
# IODelay / FalsePath / MulticyclePath / ClockGroup entities and edges
# anchored to existing ClockDomain / Port / Signal entities (case-insensitive
# fusion via known_entity_names lookup, mirroring MarkdownDocExtractor).
# Exports: SDCExtractor, SDC_SOURCE
# Deps: os, src.kgweave.knowledge_graph.common
# @end-summary
"""Synopsys Design Constraints (SDC) extractor.

Parses SDC / TCL / XDC timing-constraints files and emits typed nodes and
edges fused to the existing KG. SDC is Tcl, but instead of pulling in a
real Tcl interpreter we use a small line-based tokenizer that respects
``[...]`` (Tcl bracket expressions), ``{...}`` (lists), ``"..."`` (quoted
strings), ``\\``-line continuations, and ``#``/``;#`` comments.

Supported commands (others are skipped silently after a debug log):

* ``create_clock`` / ``create_generated_clock`` → ``ClockConstraint`` plus
  ``constrains_clock`` to the ClockDomain. Generated clocks also emit a
  ``relative_to_clock`` edge to the master.
* ``set_input_delay`` / ``set_output_delay`` → ``IODelay`` plus
  ``constrains_port`` (Port) and ``relative_to_clock`` (ClockDomain).
* ``set_false_path`` → ``FalsePath`` plus ``from_endpoint`` and
  ``to_endpoint`` to the referenced Port / Signal / ClockDomain.
* ``set_multicycle_path`` → ``MulticyclePath`` (cycle count carried in
  ``raw_mentions``) plus ``from_endpoint`` / ``to_endpoint``.
* ``set_clock_groups`` → one ``ClockGroup`` per command, plus a
  ``groups_clock`` edge per member of any ``-group`` list.
* ``set_max_delay`` / ``set_min_delay`` / ``set_clock_uncertainty`` are
  parsed as best-effort plain-text mentions; we do not currently emit
  dedicated entities for them (documented limitation — follow-up work).
* ``set_disable_timing`` is **skipped** (it disables a path within a cell,
  which has no good anchor entity in the current schema).

Tcl variables like ``$CLK_PERIOD`` are not evaluated — the literal string
is preserved on the entity's ``raw_mentions``. Object expressions of the
form ``[get_ports name]`` / ``[get_clocks name]`` / ``[get_pins a/b/q]``
are mined for bare identifiers; the last path component of ``a/b/q`` is
treated as the entity name. Set / list constructs (``[all_inputs]``,
``[remove_from_collection ...]``, etc.) yield no concrete identifier and
are skipped, so the surrounding command may still produce an entity but
without that particular endpoint edge.

When a ``known_entity_names`` list is supplied, bare identifiers are
fused to the closest case-insensitive match (also accepting suffix
``.<bare_id>`` for module-namespaced names like ``aes.clk_i``). When no
match is found the bare identifier is emitted as-is and the backend's
auto-create stubs the target.

All emitted entities and triples are tagged ``extractor_source="sdc"``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from kgweave.knowledge_graph.common import (
    Entity,
    EntityDescription,
    ExtractionResult,
    Triple,
)

__all__ = ["SDCExtractor", "SDC_SOURCE"]

SDC_SOURCE = "sdc"

_logger = logging.getLogger("rag.knowledge_graph.sdc")


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def _strip_comments_and_join_continuations(text: str) -> List[str]:
    """Return a list of logical SDC commands (one per line, joined).

    * ``#`` (or ``;#``) starts a comment that runs to end-of-line, unless it
      sits inside ``[...]`` / ``{...}`` / ``"..."`` (rare in real SDC).
    * Trailing ``\\`` joins the next physical line into the current one.
    * Blank lines are skipped.
    """
    lines: List[str] = []
    buf = ""
    for raw in text.splitlines():
        # Strip trailing comments outside brackets/quotes.
        cleaned = _strip_inline_comment(raw)
        if cleaned.endswith("\\"):
            buf += cleaned[:-1] + " "
            continue
        buf += cleaned
        stripped = buf.strip()
        if stripped:
            lines.append(stripped)
        buf = ""
    if buf.strip():
        lines.append(buf.strip())
    return lines


def _strip_inline_comment(line: str) -> str:
    """Strip ``#`` / ``;#`` comments that are not inside brackets or quotes."""
    depth_brk = 0
    depth_brc = 0
    in_quote = False
    out_chars: List[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == '"' and depth_brk == 0 and depth_brc == 0:
            in_quote = not in_quote
            out_chars.append(ch)
            i += 1
            continue
        if not in_quote:
            if ch == "[":
                depth_brk += 1
            elif ch == "]":
                depth_brk = max(0, depth_brk - 1)
            elif ch == "{":
                depth_brc += 1
            elif ch == "}":
                depth_brc = max(0, depth_brc - 1)
            elif ch == "#" and depth_brk == 0 and depth_brc == 0:
                # Tcl ``;#`` is a comment after a stmt separator; ``#`` at
                # word boundary is also a comment. We keep both simple by
                # cutting at any unbracketed/unquoted ``#``.
                # But require that the previous non-space char is not part
                # of an identifier (avoid clipping ``foo#bar``, although such
                # tokens are extremely rare in SDC).
                prev = out_chars[-1] if out_chars else " "
                if prev.isspace() or prev == ";":
                    if prev == ";":
                        out_chars.pop()
                    break
        out_chars.append(ch)
        i += 1
    return "".join(out_chars).rstrip()


def _tokenize(line: str) -> List[str]:
    """Split a single SDC command into atomic tokens.

    Whitespace splits except inside ``[...]`` / ``{...}`` / ``"..."``. The
    bracket / brace pairs are kept verbatim on the resulting tokens.
    """
    tokens: List[str] = []
    buf: List[str] = []
    depth_brk = 0
    depth_brc = 0
    in_quote = False
    for ch in line:
        if in_quote:
            buf.append(ch)
            if ch == '"':
                in_quote = False
            continue
        if depth_brk > 0:
            buf.append(ch)
            if ch == "[":
                depth_brk += 1
            elif ch == "]":
                depth_brk -= 1
            continue
        if depth_brc > 0:
            buf.append(ch)
            if ch == "{":
                depth_brc += 1
            elif ch == "}":
                depth_brc -= 1
            continue
        if ch == '"':
            in_quote = True
            buf.append(ch)
        elif ch == "[":
            depth_brk = 1
            buf.append(ch)
        elif ch == "{":
            depth_brc = 1
            buf.append(ch)
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


# ---------------------------------------------------------------------------
# Object-expression mining: extract bare identifiers from [get_ports x] / {a b}
# ---------------------------------------------------------------------------


# Structural SDC command names that yield object collections but no concrete
# named identifier we can fuse to. Used by _mine_identifiers below.
_COLLECTION_CMDS = frozenset({
    "all_inputs", "all_outputs", "all_clocks", "all_registers",
})

# Named get_* commands whose first non-flag argument IS a concrete name.
_GET_CMDS = frozenset({
    "get_ports", "get_clocks", "get_pins", "get_cells", "get_nets",
})


def _parse_bracket_expr(inner: str) -> List[str]:
    """Parse the interior of a ``[cmd arg...]`` Tcl bracket expression.

    Returns the list of bare identifier strings, or an empty list when the
    command is a collection constructor with no concrete single name (e.g.
    ``all_inputs``) or when the command is unknown.

    No regex is used — the inner string is split on whitespace and the
    first word is the command name. Brace-lists in the argument are handled
    by stripping outer ``{}``.
    """
    inner = inner.strip()
    if not inner:
        return []

    # Split on whitespace to separate command from arguments.
    parts = inner.split()
    if not parts:
        return []

    cmd = parts[0]

    if cmd in _COLLECTION_CMDS:
        return []
    if cmd not in _GET_CMDS:
        # Unknown command (e.g. remove_from_collection, filter_collection) —
        # cannot safely extract identifiers.
        return []

    # Remaining parts are the command arguments.
    args = parts[1:]
    if not args:
        return []

    # Collapse brace-grouped arguments: ``{a b}`` appears as multiple tokens
    # after split if the outer caller didn't preserve them, but _tokenize
    # keeps brace groups verbatim so in practice ``args`` is already split
    # at the top level. We re-join and re-split to handle both styles.
    joined = " ".join(args).strip()
    if joined and joined[0] == "{" and joined[-1] == "}":
        joined = joined[1:-1]

    # Strip option flags (start with '-') — same logic as before, no regex.
    words: List[str] = []
    skip_next = False
    for w in joined.split():
        if skip_next:
            skip_next = False
            continue
        if w and w[0] == "-":
            if w in ("-hierarchical", "-hier", "-regexp", "-nocase"):
                continue
            # Conservative: assume unknown flags consume the next word.
            skip_next = True
            continue
        words.append(w)

    return [_clean_id(w) for w in words if _clean_id(w)]


def _mine_identifiers(raw: str) -> List[str]:
    """Return bare identifiers referenced in a token.

    Handles:
    * ``[get_ports clk_i]`` → ``["clk_i"]``
    * ``[get_clocks {a b}]`` → ``["a", "b"]``
    * ``{clk_a clk_b}`` → ``["clk_a", "clk_b"]``
    * ``[get_pins divider/q]`` → ``["q"]`` (last path component)
    * ``[all_inputs]`` / ``[remove_from_collection ...]`` → ``[]``
    * Bare ``main_clk`` → ``["main_clk"]``

    Implemented without ``re`` — structural character and string operations only.
    """
    if not raw:
        return []
    first = raw[0]
    last = raw[-1]
    # Bare brace list: {a b c}
    if first == "{" and last == "}":
        inner = raw[1:-1]
        return [_clean_id(t) for t in inner.split() if _clean_id(t)]
    # Bracket expression: [cmd arg...]
    if first == "[" and last == "]":
        return _parse_bracket_expr(raw[1:-1])
    # Tcl-substituted variable: $CLK or ${CLK} — no usable identifier.
    if first == "$":
        return []
    cid = _clean_id(raw)
    return [cid] if cid else []


def _clean_id(tok: str) -> str:
    """Strip ``$``, ``${...}``, ``[`` / ``]``, and trailing path components.

    For ``divider/q``, return ``q`` (last component); SDC pin paths point at
    a flop's Q output and the Q-flop name is the most useful anchor.
    """
    tok = tok.strip().strip('"')
    if not tok:
        return ""
    if tok.startswith("$") or tok.startswith("${"):
        return ""
    if tok.startswith("[") or tok.endswith("]"):
        return ""
    # Pin path a/b/q — keep last component.
    if "/" in tok:
        tok = tok.split("/")[-1]
    # Strip wildcards.
    tok = tok.strip("*?")
    return tok


# ---------------------------------------------------------------------------
# Option parser
# ---------------------------------------------------------------------------


# Options that take a value (the next token); flags below are bare booleans.
_VALUED_OPTS = frozenset({
    "-period", "-name", "-source", "-divide_by", "-multiply_by",
    "-clock", "-from", "-to", "-through", "-setup", "-hold",
    "-reference_pin", "-edges", "-edge_shift", "-master_clock",
    "-comment",
})

_BARE_FLAGS = frozenset({
    "-asynchronous", "-physically_exclusive", "-logically_exclusive",
    "-add", "-rise", "-fall", "-add_delay", "-min", "-max",
    "-network_latency_included", "-source_latency_included",
    "-add_clock", "-invert", "-waveform",
})


def _parse_options(args: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    """Split arg list into ``(options_dict, positional_list)``.

    ``-group`` and ``-waveform`` may appear multiple times — the dict value
    becomes a list of all occurrences for those.
    """
    opts: Dict[str, Any] = {}
    positional: List[str] = []
    i = 0
    n = len(args)
    while i < n:
        a = args[i]
        if a.startswith("-"):
            if a in _BARE_FLAGS:
                opts[a] = True
                i += 1
                continue
            if a == "-group":
                opts.setdefault("-group", []).append(args[i + 1] if i + 1 < n else "")
                i += 2
                continue
            if a in _VALUED_OPTS:
                opts[a] = args[i + 1] if i + 1 < n else ""
                i += 2
                continue
            # Unknown flag: assume it takes one value (safer than dropping).
            if i + 1 < n and not args[i + 1].startswith("-"):
                opts[a] = args[i + 1]
                i += 2
            else:
                opts[a] = True
                i += 1
            continue
        positional.append(a)
        i += 1
    return opts, positional


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


def _basename_no_ext(source: str) -> str:
    if not source:
        return "sdc"
    return os.path.basename(source)


class SDCExtractor:
    """Parse SDC/TCL/XDC text into KG entities and triples.

    Parameters
    ----------
    known_entity_names:
        Optional iterable of canonical entity names. When provided, bare
        identifiers mined from object expressions are fused to the closest
        case-insensitive match (or to a name ending in ``.<bare_id>``).
    schema, config:
        Accepted for symmetry with the other extractors; not required.
    """

    @property
    def name(self) -> str:
        return SDC_SOURCE

    def __init__(
        self,
        known_entity_names: Optional[Iterable[str]] = None,
        schema: Optional[Any] = None,
        config: Optional[Any] = None,
    ) -> None:
        self._schema = schema
        self._config = config
        names = list(known_entity_names) if known_entity_names else []
        # Build (lower-case) lookup index. Last-write wins on duplicates.
        self._known_lower: Dict[str, str] = {}
        # Suffix index: ".<bare>" lowercased → canonical, used for module-
        # namespaced fusion ("aes.clk_i" matched by bare "clk_i").
        self._suffix_lower: Dict[str, str] = {}
        for n in names:
            if not n:
                continue
            self._known_lower[n.lower()] = n
            if "." in n:
                _, _, tail = n.rpartition(".")
                if tail:
                    self._suffix_lower[tail.lower()] = n

    # -- Public API ---------------------------------------------------------

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Parse SDC text and emit ClockConstraint / IODelay / etc. entities."""
        base = _basename_no_ext(source)
        entities: List[Entity] = []
        triples: List[Triple] = []
        false_path_idx = 0
        multicycle_idx = 0
        clock_group_idx = 0

        for line in _strip_comments_and_join_continuations(text):
            try:
                tokens = _tokenize(line)
            except Exception as exc:  # pragma: no cover — defensive
                _logger.warning("SDC tokenize failed for %r: %s", line, exc)
                continue
            if not tokens:
                continue
            cmd = tokens[0]
            args = tokens[1:]

            try:
                if cmd == "create_clock":
                    self._handle_create_clock(
                        args, source, base, line, entities, triples,
                        generated=False,
                    )
                elif cmd == "create_generated_clock":
                    self._handle_create_clock(
                        args, source, base, line, entities, triples,
                        generated=True,
                    )
                elif cmd == "set_input_delay":
                    self._handle_io_delay(
                        args, source, base, line, entities, triples,
                        direction="input",
                    )
                elif cmd == "set_output_delay":
                    self._handle_io_delay(
                        args, source, base, line, entities, triples,
                        direction="output",
                    )
                elif cmd == "set_false_path":
                    self._handle_false_path(
                        args, source, base, line, entities, triples,
                        idx=false_path_idx,
                    )
                    false_path_idx += 1
                elif cmd == "set_multicycle_path":
                    self._handle_multicycle_path(
                        args, source, base, line, entities, triples,
                        idx=multicycle_idx,
                    )
                    multicycle_idx += 1
                elif cmd == "set_clock_groups":
                    self._handle_clock_groups(
                        args, source, base, line, entities, triples,
                        idx=clock_group_idx,
                    )
                    clock_group_idx += 1
                else:
                    _logger.debug("SDC command skipped (unsupported): %s", cmd)
            except Exception as exc:  # noqa: BLE001 — be tolerant
                _logger.warning("SDC handler failed on %r: %s", line, exc)
                continue

        return ExtractionResult(entities=entities, triples=triples)

    # -- Handlers -----------------------------------------------------------

    def _handle_create_clock(
        self,
        args: List[str],
        source: str,
        base: str,
        line: str,
        entities: List[Entity],
        triples: List[Triple],
        *,
        generated: bool,
    ) -> None:
        opts, positional = _parse_options(args)
        clock_name = (opts.get("-name") or "").strip("{}\"")
        period = str(opts.get("-period", "")).strip("{}\"")
        # If no -name, derive from the positional object expression.
        if not clock_name:
            for tok in positional:
                ids = _mine_identifiers(tok)
                if ids:
                    clock_name = ids[0]
                    break
        if not clock_name:
            return
        ent_name = f"{base}.create_clock.{clock_name}"
        attrs = [f"period={period}"] if period else []
        if generated:
            attrs.append("generated=true")
            divide_by = opts.get("-divide_by")
            if divide_by:
                attrs.append(f"divide_by={divide_by}")
        entity = Entity(
            name=ent_name,
            type="ClockConstraint",
            sources=[source] if source else [],
            extractor_source=[SDC_SOURCE],
            aliases=["generated"] if generated else [],
            raw_mentions=[
                EntityDescription(text="; ".join(attrs) or line,
                                  source=source, chunk_id="")
            ],
        )
        entities.append(entity)
        triples.append(Triple(
            subject=ent_name,
            predicate="constrains_clock",
            object=self._fuse(clock_name),
            source=source,
            extractor_source=SDC_SOURCE,
            evidence_span="; ".join(attrs),
        ))
        # For generated clocks: edge to the master clock via -source.
        if generated:
            src_tok = opts.get("-source") or opts.get("-master_clock") or ""
            for src_id in _mine_identifiers(src_tok):
                triples.append(Triple(
                    subject=ent_name,
                    predicate="relative_to_clock",
                    object=self._fuse(src_id),
                    source=source,
                    extractor_source=SDC_SOURCE,
                ))

    def _handle_io_delay(
        self,
        args: List[str],
        source: str,
        base: str,
        line: str,
        entities: List[Entity],
        triples: List[Triple],
        *,
        direction: str,
    ) -> None:
        opts, positional = _parse_options(args)
        clock_name = (opts.get("-clock") or "").strip("{}\"")
        # set_input_delay [-clock C] <delay> <port_object>
        # The first positional that yields identifiers is the port; an
        # earlier numeric positional is the delay value.
        delay_val = ""
        port_ids: List[str] = []
        for tok in positional:
            # Numeric tokens (delay values) come before the port object and
            # must not be mined as identifiers.
            if _looks_numeric(tok):
                if not delay_val:
                    delay_val = tok
                continue
            ids = _mine_identifiers(tok)
            if not port_ids:
                if ids:
                    port_ids = ids
                else:
                    # Non-numeric, no identifier: likely a Tcl variable like
                    # ``$delay`` — keep as the delay value.
                    delay_val = delay_val or tok
            else:
                port_ids.extend(ids)
        if not port_ids:
            return
        for port in port_ids:
            ent_name = f"{base}.{direction}_delay.{port}"
            attrs = [f"direction={direction}"]
            if delay_val:
                attrs.append(f"delay={delay_val}")
            if clock_name:
                attrs.append(f"clock={clock_name}")
            entities.append(Entity(
                name=ent_name,
                type="IODelay",
                sources=[source] if source else [],
                extractor_source=[SDC_SOURCE],
                raw_mentions=[
                    EntityDescription(text="; ".join(attrs),
                                      source=source, chunk_id="")
                ],
            ))
            triples.append(Triple(
                subject=ent_name,
                predicate="constrains_port",
                object=self._fuse(port),
                source=source,
                extractor_source=SDC_SOURCE,
                evidence_span="; ".join(attrs),
            ))
            if clock_name:
                triples.append(Triple(
                    subject=ent_name,
                    predicate="relative_to_clock",
                    object=self._fuse(clock_name),
                    source=source,
                    extractor_source=SDC_SOURCE,
                ))

    def _handle_false_path(
        self,
        args: List[str],
        source: str,
        base: str,
        line: str,
        entities: List[Entity],
        triples: List[Triple],
        *,
        idx: int,
    ) -> None:
        opts, _positional = _parse_options(args)
        ent_name = f"{base}.false_path.{idx}"
        entities.append(Entity(
            name=ent_name,
            type="FalsePath",
            sources=[source] if source else [],
            extractor_source=[SDC_SOURCE],
            raw_mentions=[EntityDescription(text=line, source=source, chunk_id="")],
        ))
        for tok in _ensure_list(opts.get("-from")):
            for ident in _mine_identifiers(tok):
                triples.append(Triple(
                    subject=ent_name, predicate="from_endpoint",
                    object=self._fuse(ident), source=source,
                    extractor_source=SDC_SOURCE,
                ))
        for tok in _ensure_list(opts.get("-to")):
            for ident in _mine_identifiers(tok):
                triples.append(Triple(
                    subject=ent_name, predicate="to_endpoint",
                    object=self._fuse(ident), source=source,
                    extractor_source=SDC_SOURCE,
                ))

    def _handle_multicycle_path(
        self,
        args: List[str],
        source: str,
        base: str,
        line: str,
        entities: List[Entity],
        triples: List[Triple],
        *,
        idx: int,
    ) -> None:
        opts, positional = _parse_options(args)
        # Cycle count: -setup N or -hold N or first bare positional integer.
        cycles = ""
        for k in ("-setup", "-hold"):
            v = opts.get(k)
            if isinstance(v, str) and v.strip("-").isdigit():
                cycles = v
                break
        if not cycles:
            for p in positional:
                if p.strip("-").isdigit():
                    cycles = p
                    break
        ent_name = f"{base}.multicycle_path.{idx}"
        attrs = []
        if cycles:
            attrs.append(f"cycles={cycles}")
        if opts.get("-setup"):
            attrs.append("kind=setup")
        elif opts.get("-hold"):
            attrs.append("kind=hold")
        entities.append(Entity(
            name=ent_name,
            type="MulticyclePath",
            sources=[source] if source else [],
            extractor_source=[SDC_SOURCE],
            raw_mentions=[EntityDescription(
                text="; ".join(attrs) or line, source=source, chunk_id="")],
        ))
        for tok in _ensure_list(opts.get("-from")):
            for ident in _mine_identifiers(tok):
                triples.append(Triple(
                    subject=ent_name, predicate="from_endpoint",
                    object=self._fuse(ident), source=source,
                    extractor_source=SDC_SOURCE,
                ))
        for tok in _ensure_list(opts.get("-to")):
            for ident in _mine_identifiers(tok):
                triples.append(Triple(
                    subject=ent_name, predicate="to_endpoint",
                    object=self._fuse(ident), source=source,
                    extractor_source=SDC_SOURCE,
                ))

    def _handle_clock_groups(
        self,
        args: List[str],
        source: str,
        base: str,
        line: str,
        entities: List[Entity],
        triples: List[Triple],
        *,
        idx: int,
    ) -> None:
        opts, _pos = _parse_options(args)
        groups: List[str] = list(opts.get("-group") or [])
        if not groups:
            return
        ent_name = f"{base}.clock_group.{idx}"
        attrs = []
        if opts.get("-asynchronous"):
            attrs.append("kind=asynchronous")
        if opts.get("-physically_exclusive"):
            attrs.append("kind=physically_exclusive")
        if opts.get("-logically_exclusive"):
            attrs.append("kind=logically_exclusive")
        entities.append(Entity(
            name=ent_name,
            type="ClockGroup",
            sources=[source] if source else [],
            extractor_source=[SDC_SOURCE],
            raw_mentions=[EntityDescription(
                text="; ".join(attrs) or line, source=source, chunk_id="")],
        ))
        for grp_tok in groups:
            for ident in _mine_identifiers(grp_tok):
                triples.append(Triple(
                    subject=ent_name,
                    predicate="groups_clock",
                    object=self._fuse(ident),
                    source=source,
                    extractor_source=SDC_SOURCE,
                ))

    # -- Fusion helper ------------------------------------------------------

    def _fuse(self, bare: str) -> str:
        """Return the canonical entity name for *bare*, or *bare* if no match."""
        if not bare:
            return bare
        key = bare.lower()
        if key in self._known_lower:
            return self._known_lower[key]
        if key in self._suffix_lower:
            return self._suffix_lower[key]
        return bare


def _looks_numeric(tok: str) -> bool:
    """Return True for a literal numeric token (``2``, ``2.0``, ``1e-3``).

    Uses stdlib ``float()`` parsing — no regex required.  A leading ``-``
    sign is valid for delay values (e.g. ``-2.5``).
    """
    s = tok.strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _ensure_list(value: Any) -> List[str]:
    """Normalize an option value to a list of tokens (handles ``-from {a b}``)."""
    if value is None or value is True or value is False:
        return []
    if isinstance(value, list):
        return [v for v in value if v]
    s = str(value)
    if not s:
        return []
    # ``-from {a b}`` tokenises to a single ``{a b}`` token; let
    # _mine_identifiers handle the brace list. Otherwise return as-is.
    return [s]

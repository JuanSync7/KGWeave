"""v1.3-#1: per-file promote() output cache.

After v1.2-#1's per-file lift cache landed, the SV builder's hot path is the
two-pass ``promote()`` walk that runs the semantic rule dispatch over every
file in the compilation. The per-file lift slice is already cache-served in
``builders/sv/lift.py`` but ``promote()`` still rewalks every file's syntax
tree on every ``build_kg()`` call. For a stable corpus that yields the same
work product on every extract; this module turns that into a near-zero-cost
replay.

Cache key
---------

``(uri, sha256(file_bytes), corpus_fp, ruleset_fp)``:

* **uri / sha256** — file identity + content. Mirrors lift's cache key.
* **corpus_fp** — fingerprint over the full set of ``(uri, sha)`` pairs
  participating in this ``build_kg`` call.  Cross-file ``promote()`` resolves
  references through the shared ``semantic_name_index``; a cached pass-2
  delta therefore bakes in gids of *other* files at capture time.  If any
  file in the corpus changes its bytes, the gids of its nodes change (they
  embed the file's lift counter and stem-prefix), which would make a replay
  of a stale cached edge point at a non-existent target. Pinning the corpus
  fingerprint to the set of file shas keeps the replay sound: any change
  anywhere in the corpus invalidates every entry, and a fresh walk fills the
  cache for the new corpus state.
* **ruleset_fp** — fingerprint over the dispatch source + every rule
  submodule's source. Changing the rule code invalidates every cached
  output. Required because the rule callables are part of the projection;
  bumping them silently would let stale deltas survive a code change.

Replay semantics
----------------

The captured delta for each ``(file, phase)`` covers four mutations
``promote()`` makes to the shared graph dict:

* node-slice marks — ``role`` / ``path`` / ``name`` / ``attributes`` keys
  written by ``_mark`` onto entries in ``graph['nodes'][off:off+tree_count]``
  (lift already populated the slice; promote only marks it).
* edges appended to ``graph['edges']``.
* entries added to ``graph['semantic_name_index']``.
* entries appended to ``graph['semantic_leaks']``.
* the cross-file ``_s60_pending`` deferral list which pass1 appends to and
  pass2 drains — captured as additive items for pass1 and as a "drained" flag
  for the first pass2 call.

A cached file's pass-1 and pass-2 deltas are replayed in the same order the
walker would have produced them; subsequent miss files still see a
fully-populated ``semantic_name_index`` because hits replay first.

Soundness
---------

Replay produces a byte-equal graph delta when:

1. The lift slice for the file is identical (guaranteed by the v1.2-#1
   ``(uri, sha, id_prefix)`` lift cache contract — same key in both layers).
2. Every other file's pass-1 contribution to ``semantic_name_index`` is
   either replayed from a cache hit or freshly produced — both of which
   restore the same key→gid mapping the original walk saw, because gids are
   a pure function of ``(stem-prefix, lift counter)`` and the lift counter
   is deterministic given the file bytes.
3. No rule code has changed since capture (``ruleset_fp`` enforces this).

We deep-copy on store AND on serve — v1.2-#1's retro called out a poisoning
bug where a downstream stage mutated cached lift output in place.

Scope
-----

In-process dict cache only. No disk persistence; deferred to a future
editor/LSP integration that needs cross-process cache sharing. See JOURNAL
v1.3-#1 retro.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .dispatch import promote as _promote_inner


# ---------------------------------------------------------------------------
# Module-level cache state.
# ---------------------------------------------------------------------------

_PROMOTE_CACHE: dict[tuple[str, str, str, str], dict[str, Any]] = {}
_CACHE_STATS: dict[str, int] = {"hits": 0, "misses": 0}

# Sentinel so we can distinguish "key absent on this node before promote"
# from "key present and equal to None after promote".
_MISSING = object()

# Keys that promote() writes onto a lifted node via ``_mark``. Kept in sync
# with ``common.graph._mark`` — any new top-level mark key MUST be added
# here so it rides along in the cached delta. ``_mark`` sets ``queryable``
# at the top level and merges semantic kwargs into a nested ``semantic``
# dict, so we capture both.
_MARK_KEYS = ("queryable", "semantic")


def clear_cache() -> None:
    """Drop all cached promote slices and reset the hit/miss counters."""
    _PROMOTE_CACHE.clear()
    _CACHE_STATS["hits"] = 0
    _CACHE_STATS["misses"] = 0


def cache_stats() -> dict[str, int]:
    """Return a copy of the in-process cache hit/miss counters."""
    return dict(_CACHE_STATS)


def _sha256_hex_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_corpus_fp(files: list[tuple[str, str]]) -> str:
    """Fingerprint a corpus as the sha256 of its ordered ``(uri, sha)`` list.

    Any change to a file's bytes (sha), to the set of participating files
    / uris, OR to the **order** they were presented in flips this
    fingerprint, invalidating every cached entry that referenced the old
    corpus state.

    Order matters: SV promote dispatch is order-sensitive — pass1 of file
    N populates the cross-file ``semantic_name_index`` BEFORE pass2 of any
    file consults it. The same set of files presented in different orders
    can produce different ``imports`` / ``of_module`` / ``references_*``
    edges (a file imported by another file that hasn't been pass1'd yet
    lands on a synthetic ``_unresolved.<name>`` placeholder). v1.6-#1
    surfaced this as the md<->sv test-isolation pollution: hashing a
    sorted list collapsed the two orderings to the same key, so a cache
    hit replayed the wrong-order delta. The fix is to hash the list
    AS-GIVEN.
    """
    payload = json.dumps(list(files), separators=(",", ":"))
    return _sha256_hex_str(payload)


_RULESET_FP_CACHE: dict[str, str] = {}


def compute_ruleset_fp() -> str:
    """Fingerprint the rule projection (dispatch + every rule submodule).

    The fingerprint is cached per-process — the rule code can't change
    mid-process without a reload, and we don't want to re-stat / re-hash
    every file on every ``promote_file_cached`` call.
    """
    if "fp" in _RULESET_FP_CACHE:
        return _RULESET_FP_CACHE["fp"]
    # Import here to avoid circulars at module load.
    import inspect

    from . import dispatch as _dispatch_mod
    from .rules import ALL_RULE_MODULES, RULE_TABLE

    h = hashlib.sha256()
    # Hash the dispatch source.
    try:
        h.update(inspect.getsource(_dispatch_mod).encode("utf-8"))
    except (OSError, TypeError):
        h.update(b"dispatch:no-source")
    # Hash each rule submodule's source in import order.
    for mod in ALL_RULE_MODULES:
        try:
            h.update(inspect.getsource(mod).encode("utf-8"))
        except (OSError, TypeError):
            h.update(f"{mod.__name__}:no-source".encode("utf-8"))
    # Hash the active dispatch keys (string form of pyslang SyntaxKind).
    h.update(json.dumps(
        sorted(str(k) for k in RULE_TABLE.keys()),
    ).encode("utf-8"))
    fp = h.hexdigest()
    _RULESET_FP_CACHE["fp"] = fp
    return fp


def clear_ruleset_fp_cache() -> None:
    """Drop the memoized ruleset fingerprint (test-only hook)."""
    _RULESET_FP_CACHE.pop("fp", None)


# ---------------------------------------------------------------------------
# Per-file delta capture / replay.
# ---------------------------------------------------------------------------


def _snapshot_node_marks(
    nodes_list: list[dict[str, Any]], off: int, count: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(off, off + count):
        n = nodes_list[i]
        snap = {}
        for k in _MARK_KEYS:
            snap[k] = copy.deepcopy(n[k]) if k in n else _MISSING
        out.append(snap)
    return out


def _diff_node_marks(
    nodes_list: list[dict[str, Any]],
    off: int,
    before: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    """Per-node diff of mark-key writes added by promote.

    Returns a list of ``(local_index, mark_dict)`` entries where
    ``mark_dict`` carries only the keys that were added or changed during
    the call. ``local_index`` is the offset within the file's node slice.
    """
    diffs: list[tuple[int, dict[str, Any]]] = []
    for i, prev in enumerate(before):
        n = nodes_list[off + i]
        added: dict[str, Any] = {}
        for k in _MARK_KEYS:
            new = n.get(k, _MISSING)
            old = prev[k]
            if new is _MISSING and old is _MISSING:
                continue
            if new is _MISSING and old is not _MISSING:
                # promote() does not delete mark keys today, but be defensive.
                added[k] = _MISSING
                continue
            if new != old:
                added[k] = copy.deepcopy(new)
        if added:
            diffs.append((i, added))
    return diffs


def _apply_node_mark_diffs(
    nodes_list: list[dict[str, Any]],
    off: int,
    diffs: list[tuple[int, dict[str, Any]]],
) -> None:
    for local_idx, marks in diffs:
        n = nodes_list[off + local_idx]
        for k, v in marks.items():
            if v is _MISSING:
                n.pop(k, None)
            else:
                n[k] = copy.deepcopy(v)


def _tree_node_count(tree: Any) -> int:
    """Count syntax / token nodes pyslang's iterator yields for ``tree.root``.

    Mirrors ``_Builder.visit`` in :mod:`builders.sv.lift` — every visit emits
    exactly one graph node, whether the underlying pyslang object is a
    SyntaxNode or a Token.
    """
    from .common.tokens import _is_token

    count = 0

    def _walk(node: Any) -> None:
        nonlocal count
        count += 1
        if _is_token(node):
            return
        try:
            children = list(node)
        except TypeError:
            return
        for ch in children:
            _walk(ch)

    _walk(tree.root)
    return count


def promote_file_cached(
    graph: dict[str, Any],
    syntax_tree: Any,
    compilation: Any,
    *,
    node_offset: int,
    phase: str,
    uri: str,
    sha: str,
    corpus_fp: str,
    ruleset_fp: str | None = None,
    tree_node_count: int | None = None,
) -> None:
    """Run (or replay) one promote() phase for a single file.

    On a cache hit: replays the captured delta into ``graph`` — same node
    marks, edges, name_index entries, leaks, and ``_s60_pending`` items the
    original walk emitted, with deep-copied payloads so callers can mutate
    freely.

    On a cache miss: invokes the real ``promote()`` while capturing every
    mutation it makes to ``graph``; the captured delta is stored under
    ``(uri, sha, corpus_fp, ruleset_fp)`` so the next call with the same
    key replays it.

    ``phase`` is ``"pass1"`` or ``"pass2"`` — the two phases of dispatch are
    cached independently because pass-2 reads cross-file name_index entries
    populated by pass-1 of *other* files.
    """
    if ruleset_fp is None:
        ruleset_fp = compute_ruleset_fp()
    key = (uri, sha, corpus_fp, ruleset_fp)

    entry = _PROMOTE_CACHE.get(key)
    if entry is not None and phase in entry:
        _CACHE_STATS["hits"] += 1
        _replay(graph, entry[phase], node_offset)
        return

    _CACHE_STATS["misses"] += 1
    if tree_node_count is None:
        tree_node_count = _tree_node_count(syntax_tree)
    delta = _run_and_capture(
        graph, syntax_tree, compilation,
        node_offset=node_offset, phase=phase,
        tree_node_count=tree_node_count,
    )
    if entry is None:
        entry = {}
        _PROMOTE_CACHE[key] = entry
    entry[phase] = delta
    entry["tree_node_count"] = tree_node_count


def _run_and_capture(
    graph: dict[str, Any],
    syntax_tree: Any,
    compilation: Any,
    *,
    node_offset: int,
    phase: str,
    tree_node_count: int,
) -> dict[str, Any]:
    nodes_list = graph["nodes"]
    name_index = graph.setdefault("semantic_name_index", {})
    leaks = graph.setdefault("semantic_leaks", [])

    # Snapshot what's there now so we can subtract after promote() runs.
    nodes_before = _snapshot_node_marks(nodes_list, node_offset, tree_node_count)
    nodes_len_before = len(nodes_list)
    edges_len_before = len(graph["edges"])
    ni_keys_before = set(name_index.keys())
    leaks_len_before = len(leaks)
    s60_len_before = len(graph.get("_s60_pending") or [])
    s60_present_before = "_s60_pending" in graph

    _promote_inner(
        graph, syntax_tree, compilation,
        node_offset=node_offset, phase=phase,
    )

    edges_added = graph["edges"][edges_len_before:]
    leaks_added = leaks[leaks_len_before:]
    ni_added = {
        k: name_index[k] for k in name_index.keys() - ni_keys_before
    }
    node_diffs = _diff_node_marks(nodes_list, node_offset, nodes_before)
    # Synthetic nodes a rule appended to ``nodes_list`` during this call
    # (e.g. S38 / S54 / S58 fanout for multi-declarator declarations).
    # They live AT THE END of nodes_list, past every file's lift slice, so
    # replaying by re-appending is safe — they don't displace any other
    # file's ``node_offset``.
    nodes_appended = nodes_list[nodes_len_before:]

    # _s60_pending mutations: pass1 may APPEND to it; pass2's first invocation
    # POPs it. We capture both shapes.
    s60_after_present = "_s60_pending" in graph
    s60_after = graph.get("_s60_pending") or []
    s60_appended: list[Any] = []
    s60_drained = False
    if phase == "pass1":
        # Pass1 only appends (never drains).
        s60_appended = s60_after[s60_len_before:]
    else:
        # Pass2 drains on first call. We mark drained=True if before-present
        # and after-absent.
        if s60_present_before and not s60_after_present:
            s60_drained = True

    return {
        "node_diffs": node_diffs,
        "nodes_appended": copy.deepcopy(nodes_appended),
        "edges": copy.deepcopy(edges_added),
        "name_index": copy.deepcopy(ni_added),
        "leaks": copy.deepcopy(leaks_added),
        "s60_appended": copy.deepcopy(s60_appended),
        "s60_drained": s60_drained,
    }


def _replay(graph: dict[str, Any], delta: dict[str, Any], node_offset: int) -> None:
    nodes_list = graph["nodes"]
    name_index = graph.setdefault("semantic_name_index", {})
    leaks = graph.setdefault("semantic_leaks", [])

    _apply_node_mark_diffs(nodes_list, node_offset, delta["node_diffs"])
    if delta.get("nodes_appended"):
        nodes_list.extend(copy.deepcopy(delta["nodes_appended"]))
    graph["edges"].extend(copy.deepcopy(delta["edges"]))
    for k, v in delta["name_index"].items():
        # Preserve first-write-wins semantics: a pass-1 in the original walk
        # only writes a key if not already present in some sites; replicate
        # by overwriting only if not already there. Most dispatch sites
        # overwrite unconditionally, so the difference is invisible.
        if k not in name_index:
            name_index[k] = v
    leaks.extend(copy.deepcopy(delta["leaks"]))

    if delta.get("s60_appended"):
        bucket = graph.setdefault("_s60_pending", [])
        bucket.extend(copy.deepcopy(delta["s60_appended"]))
    if delta.get("s60_drained"):
        graph.pop("_s60_pending", None)


__all__ = [
    "promote_file_cached",
    "clear_cache",
    "cache_stats",
    "compute_corpus_fp",
    "compute_ruleset_fp",
    "clear_ruleset_fp_cache",
]

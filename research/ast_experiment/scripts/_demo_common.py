"""Shared logic between the legacy and Kuzu demo-graph exporters.

v1.3-#3 deduplicates two pieces that previously lived as byte-identical
copies in :mod:`export_demo_graph` and :mod:`export_demo_graph_kuzu`:

* :func:`parse_bucket1_categories` — parses ``BUCKET_1_CHECKLIST.md`` into
  the ``{SyntaxKindName: category}`` map used to resolve SPEC §3.3
  categories on top of writer-emitted labels.
* :data:`RULE_FAMILIES` — the SPEC §4 family roster (id, title, ruleIds,
  blurb) used to roll queryable nodes up into the demo's
  ``ruleFamilies[]`` summary.

The JOURNAL retro for v1.2-#3 flagged "two copies will drift"; this module
is the single source of truth so adding a new rule family or recategorising
a bucket-1 kind is a one-edit change.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Bucket-1 categorisation                                                     #
# --------------------------------------------------------------------------- #

_SECTION_MAP: dict[str, str] = {
    "PROMOTE": "semantic",
    "CONTAINER": "structural",
    "BLOB": "blob",
    "DIRECTIVE": "structural",
    "OUT-OF-SCOPE": "structural",
}


def parse_bucket1_categories(checklist_path: Path) -> dict[str, str]:
    """Parse ``BUCKET_1_CHECKLIST.md`` into ``{SyntaxKindName: category}``.

    Categories follow SPEC §3.3:

    * ``semantic`` for PROMOTE rows,
    * ``structural`` for CONTAINER (and DIRECTIVE / OUT-OF-SCOPE rows that
      only appear as preprocessor remnants),
    * ``blob`` for BLOB.
    """
    text = checklist_path.read_text()
    out: dict[str, str] = {}
    section: str | None = None
    for line in text.splitlines():
        m = re.match(r"^## ([A-Z\-]+)\s*\(", line)
        if m and m.group(1) in _SECTION_MAP:
            section = _SECTION_MAP[m.group(1)]
            continue
        if section is None:
            continue
        m2 = re.match(r"^\|\s*`([A-Za-z0-9_]+)`", line)
        if m2:
            out[m2.group(1)] = section
    return out


def category_for_kind(
    bucket1: dict[str, str],
    *,
    kind: str,
    is_token: bool,
    is_semantic: bool,
) -> str:
    """Resolve the SPEC §3.3 category for a node.

    ``bucket1`` is the result of :func:`parse_bucket1_categories`. Tokens
    and semantic-flagged nodes are never demoted; everything else falls
    back to the bucket-1 table, with ``"structural"`` as the catch-all
    for kinds the checklist does not enumerate (e.g. ``SyntaxList``,
    ``CompilationUnit``).
    """
    if is_token:
        return "token"
    if is_semantic:
        return "semantic"
    short = kind.split(".")[-1] if isinstance(kind, str) else ""
    cat = bucket1.get(short)
    if cat is not None:
        return cat
    return "structural"


# --------------------------------------------------------------------------- #
# Rule-family rollup (SPEC §4)                                                #
# --------------------------------------------------------------------------- #

# Family ids and the rule-id roster they cover, per SPEC §4. Single source
# of truth — both exporters import this list.
RULE_FAMILIES: list[dict[str, Any]] = [
    {
        "id": "structure",
        "title": "Module / Interface / Package / Program structure",
        "ruleIds": ["S1", "S11a", "S11b", "S12b", "S12c", "S30"],
        "blurb": "Top-level scopes (module, interface, package, program) and their nested generate / modport children.",
    },
    {
        "id": "ports_params",
        "title": "Ports & parameters",
        "ruleIds": ["S1", "S2", "S3", "S7", "S64", "S65", "S74", "S75", "S76", "S77", "S78"],
        "blurb": "ANSI / non-ANSI port lists, parameter declarations, and parameter overrides on instances.",
    },
    {
        "id": "nets_vars",
        "title": "Nets & variables",
        "ruleIds": ["S4"],
        "blurb": "Net and variable declarations, including identifier references that resolve back to declarators.",
    },
    {
        "id": "continuous_assign_dataflow",
        "title": "Continuous assigns + dataflow",
        "ruleIds": ["S5", "S33", "S34", "S35", "S36", "S37", "S38", "S39"],
        "blurb": "Continuous assigns, their LHS / RHS dataflow edges, and always-block flavours that drive nets.",
    },
    {
        "id": "procedural_blocks",
        "title": "Procedural blocks",
        "ruleIds": ["S7", "S8", "S9", "S9c", "S19", "S20", "S21"],
        "blurb": "always_comb / always_ff / initial / final blocks and the procedural statements inside them.",
    },
    {
        "id": "instances_hierarchy",
        "title": "Instances & hierarchy",
        "ruleIds": ["S6", "S28", "S79"],
        "blurb": "Hierarchical module instantiations and checker instantiations forming the design hierarchy.",
    },
    {
        "id": "assertions_clocking",
        "title": "Assertions & clocking",
        "ruleIds": ["S14", "S15", "S16", "S17", "S18", "S40", "S59", "S70", "S71", "S72"],
        "blurb": "Concurrent / immediate assertions, properties, sequences, and the clocking blocks they synchronise with.",
    },
    {
        "id": "covergroups",
        "title": "Covergroups",
        "ruleIds": ["S22", "S23", "S41"],
        "blurb": "Covergroup declarations, coverpoints, cross coverage, and the bins that drive them.",
    },
    {
        "id": "classes_constraints",
        "title": "Classes & constraints",
        "ruleIds": ["S24", "S25", "S26", "S27", "S82", "S83"],
        "blurb": "Class declarations with inheritance, methods, properties, and constraint blocks.",
    },
    {
        "id": "packages_types_externs",
        "title": "Packages, types & externs",
        "ruleIds": ["S29", "S31", "S32", "S40", "S44", "S45", "S56", "S57", "S80", "S81"]
                   + [f"S{n}" for n in range(40, 58)],
        "blurb": "Package imports/exports, typedefs, DPI imports/exports, and extern declarations bridging compilation units.",
    },
]


def attribute_to_family(
    node: dict[str, Any], kind_to_rule: dict[str, str]
) -> tuple[str | None, str | None]:
    """Return ``(rule_id, family_id)`` for ``node``, or ``(None, None)``.

    The rule id is taken from the node's ``semantic.ruleId`` payload when
    present, otherwise resolved from the static ``kind_to_rule`` map built
    by walking the rule modules. The family id is the first
    :data:`RULE_FAMILIES` entry whose roster lists the rule id.
    """
    sem = node.get("semantic") or {}
    rid = sem.get("ruleId") or kind_to_rule.get(str(node.get("kind", "")))
    if rid is None:
        return None, None
    for fam in RULE_FAMILIES:
        if rid in fam["ruleIds"]:
            return rid, fam["id"]
    return rid, None

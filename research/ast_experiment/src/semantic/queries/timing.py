"""Timing queries — sensitivity lists from ``always_*`` blocks."""

from __future__ import annotations

from typing import Any


def sensitivity_of(graph: dict[str, Any], always_block_id: str) -> list[dict[str, Any]]:
    """Return ``[{"signal": <net/port path>, "edge": <posedge|negedge|edge>}, …]``
    from outgoing ``sensitive_to`` edges of an ``always_*`` node."""
    by_id = {n["id"]: n for n in graph["nodes"]}
    out: list[dict[str, Any]] = []
    for e in graph["edges"]:
        if e["type"] != "sensitive_to" or e["src"] != always_block_id:
            continue
        dst = by_id.get(e["dst"])
        if dst is None:
            continue
        sig = dst.get("semantic", {}).get("path") or dst.get("semantic", {}).get("name")
        out.append({"signal": sig, "edge": e["payload"].get("edge")})
    return out

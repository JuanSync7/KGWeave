"""Deterministic ID helpers.

All IDs in KGWeave are SHA-derived strings so re-extracting an unchanged
corpus is bit-for-bit idempotent (invariant I6).
"""

from __future__ import annotations

import hashlib


def sha256_bytes(data: bytes) -> str:
    """Hex-encoded SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def origin_id_for(uri: str, sha256: str) -> str:
    """Deterministic ``:Origin.id`` from ``(uri, sha256)``.

    Keying on both means:

    * Re-snapshotting the same path with the same content is idempotent.
    * Re-snapshotting after the content changed yields a new id (old origin
      stays addressable for legacy spans).
    * Two files with identical content but different paths are stored as
      separate rows (deletion semantics stay clean).
    """
    h = hashlib.sha256()
    h.update(uri.encode("utf-8"))
    h.update(b"\x00")
    h.update(sha256.encode("ascii"))
    return "origin:" + h.hexdigest()


__all__ = ["sha256_bytes", "origin_id_for"]

"""File → ``:Origin`` ingestion.

Bytes-in / bytes-out contract: ``snapshot_file`` reads the file as raw
bytes, hashes them, and stores them as a ``STRING`` column using a
``latin-1`` round-trip. Latin-1 is the only 8-bit codec that maps
``0..255`` 1:1 to ``U+0000..U+00FF`` — so arbitrary byte sequences
(including NULs and invalid UTF-8) survive the trip.

This keeps the schema aligned with the plan's ``content STRING``
declaration without sacrificing the I1 round-trip guarantee.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from knowledge_graph.schemas import OriginRef
from knowledge_graph.shared.ids import origin_id_for, sha256_bytes

# Sentinel used by both writer and reader.
BYTES_CODEC = "latin-1"


def snapshot_file(
    conn,
    path: Path | str,
    *,
    source: str,
    corpus: str,
    lang: str = "",
    uri: str | None = None,
) -> OriginRef:
    """Ingest ``path`` into an ``:Origin`` row and return its handle.

    Idempotent on ``(uri, sha256)``: re-snapshotting the same file is a
    no-op (uses ``MERGE``), changed content yields a new row.
    """
    p = Path(path)
    raw = p.read_bytes()
    sha = sha256_bytes(raw)
    resolved_uri = uri if uri is not None else str(p.resolve())
    oid = origin_id_for(resolved_uri, sha)
    content_str = raw.decode(BYTES_CODEC)

    conn.execute(
        """
        MERGE (o:Origin {id: $id})
        ON CREATE SET
            o.uri = $uri,
            o.sha256 = $sha,
            o.content = $content,
            o.byte_length = $blen,
            o.source = $source,
            o.corpus = $corpus,
            o.lang = $lang,
            o.extracted_at = $ts
        """,
        {
            "id": oid,
            "uri": resolved_uri,
            "sha": sha,
            "content": content_str,
            "blen": len(raw),
            "source": source,
            "corpus": corpus,
            "lang": lang,
            "ts": datetime.now(timezone.utc),
        },
    )

    return OriginRef(
        id=oid,
        uri=resolved_uri,
        sha256=sha,
        source=source,
        corpus=corpus,
    )


__all__ = ["snapshot_file", "BYTES_CODEC"]

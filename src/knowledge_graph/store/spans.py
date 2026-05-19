"""``source_at`` — exact byte-range retrieval from an ``:Origin``."""

from __future__ import annotations

from knowledge_graph.store.snapshot import BYTES_CODEC


class OriginNotFoundError(KeyError):
    """Raised when ``source_at`` is asked for an origin that does not exist."""


def source_at(conn, origin_id: str, start_offset: int, end_offset: int) -> bytes:
    """Return the exact byte slice ``content[start:end]`` from the origin.

    The content column is a latin-1 encoded mirror of the original file
    bytes (see ``snapshot.py``); we decode the slice back to bytes here.
    """
    if start_offset < 0 or end_offset < 0:
        raise ValueError(f"offsets must be non-negative: {start_offset}, {end_offset}")
    if end_offset < start_offset:
        raise ValueError(
            f"end_offset ({end_offset}) < start_offset ({start_offset})"
        )

    res = conn.execute(
        "MATCH (o:Origin {id: $id}) RETURN o.content, o.byte_length",
        {"id": origin_id},
    )
    if not res.has_next():
        raise OriginNotFoundError(origin_id)
    row = res.get_next()
    content_str: str = row[0]
    byte_length: int = row[1]

    raw = content_str.encode(BYTES_CODEC)
    # Defensive: the encoded length must match what we wrote.
    if len(raw) != byte_length:
        raise RuntimeError(
            "origin content corruption: "
            f"encoded={len(raw)} stored_byte_length={byte_length} id={origin_id}"
        )

    # Python slicing is already clamping + half-open; mirror that.
    return raw[start_offset:end_offset]


__all__ = ["source_at", "OriginNotFoundError"]

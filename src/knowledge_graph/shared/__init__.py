"""Cross-cutting helpers shared by store, builders, and query layers."""

from knowledge_graph.shared.ids import origin_id_for, sha256_bytes

__all__ = ["origin_id_for", "sha256_bytes"]

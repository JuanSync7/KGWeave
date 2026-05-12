"""Semantic package — promote-on-demand projection over the structural
backbone.

The public API is the stable import surface used by RagWeave and other
consumers; internal modules (`common/`, `rules/`, `queries/`, `dispatch.py`)
are implementation detail and must not be imported directly from outside.

Re-exports (preserved from the old monolithic `scripts/semantic.py`)::

    promote, queryable_nodes, neighbors, find_by_name,
    find_drivers, cone_of_influence, forward_cone,
    port_connections, instances_of, param_overrides,
    sensitivity_of, width_of, default_value_of,
    modports_of, package_of, graph_query
"""

from __future__ import annotations

# Re-exports are populated as the migration progresses (split-01..split-07).
# Until then, the monolithic shim at scripts/semantic.py remains the source
# of truth for query-layer behaviour.

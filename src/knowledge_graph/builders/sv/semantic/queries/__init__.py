"""Query functions over a promoted graph.

Each submodule groups one query family:

* ``flow``        — find_drivers, cone_of_influence, forward_cone
* ``connectivity``— port_connections, instances_of, param_overrides,
                    modports_of, package_of, neighbors, find_by_name,
                    queryable_nodes
* ``timing``      — sensitivity_of
* ``attributes``  — width_of, default_value_of

Note: the ``graph_query`` pattern-dict DSL was retired in S7.
"""

from .connectivity import (
    neighbors,
    find_by_name,
    port_connections,
    instances_of,
    param_overrides,
    modports_of,
    package_of,
    queryable_nodes,
)
from .flow import find_drivers, cone_of_influence, forward_cone, reads_of
from .timing import sensitivity_of
from .attributes import width_of, default_value_of

# Structural-payload helpers — exposed for tests that read raw token text.
from .attributes import (
    _children_of,
    _parent_of,
    _text_of_subtree,
    _first_child_of_kind,
    _descendants_of_kind,
)

__all__ = [
    "neighbors", "find_by_name",
    "find_drivers", "cone_of_influence", "forward_cone", "reads_of",
    "port_connections", "instances_of", "param_overrides",
    "modports_of", "package_of",
    "sensitivity_of",
    "width_of", "default_value_of",
    "queryable_nodes",
    "_children_of", "_parent_of", "_text_of_subtree",
    "_first_child_of_kind", "_descendants_of_kind",
]

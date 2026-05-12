"""Compatibility shim — semantic.py has moved to src/semantic/.

Re-exports the entire public API so legacy ``from scripts.semantic import …``
keeps working until split-07. Slated for deletion in split-07.
"""

from __future__ import annotations

# Public API.
from research.ast_experiment.src.semantic import (  # noqa: F401
    promote,
    queryable_nodes,
    neighbors,
    find_by_name,
    find_drivers,
    reads_of,
    cone_of_influence,
    forward_cone,
    port_connections,
    instances_of,
    param_overrides,
    sensitivity_of,
    width_of,
    default_value_of,
    graph_query,
    modports_of,
    package_of,
)

# Private helpers historically exposed for tests.
from research.ast_experiment.src.semantic.common import (  # noqa: F401
    _walk_with_index,
    _descendants,
    _is_token,
    _cls,
    _token_kind_name,
    _identifier_tokens,
    _identifier_names_in,
    _mark,
    _add_edge,
    _has_edge,
    _module_scope,
    _all_module_scopes,
    _scope_path_of,
    _lookup_name,
    _resolve,
    _split_around_eq,
    _lhs_target_name,
    _expression_text,
    _module_name_of,
    _function_name_of,
    _typedef_name_of,
    _enum_value_names,
)

from research.ast_experiment.src.semantic.queries import (  # noqa: F401
    _children_of,
    _parent_of,
    _text_of_subtree,
    _first_child_of_kind,
    _descendants_of_kind,
)

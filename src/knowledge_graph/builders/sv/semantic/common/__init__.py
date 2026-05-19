"""Common helpers shared by rules/, queries/, and dispatch.py.

This package is the SINGLE source of truth for low-level walk/resolve/graph/
token primitives. No rule module or query module may redefine these helpers
— they must import from here.
"""

from .walk import _walk_with_index, _descendants
from .resolve import (
    _resolve,
    _lookup_name,
    _scope_path_of,
    _module_scope,
    _all_module_scopes,
)
from .graph import _add_edge, _has_edge, _mark
from .tokens import (
    _is_token,
    _cls,
    _token_kind_name,
    _identifier_tokens,
    _identifier_names_in,
    _split_around_eq,
    _lhs_target_name,
    _expression_text,
    _module_name_of,
    _function_name_of,
    _typedef_name_of,
    _enum_value_names,
)

__all__ = [
    "_walk_with_index", "_descendants",
    "_resolve", "_lookup_name", "_scope_path_of", "_module_scope",
    "_all_module_scopes",
    "_add_edge", "_has_edge", "_mark",
    "_is_token", "_cls", "_token_kind_name",
    "_identifier_tokens", "_identifier_names_in",
    "_split_around_eq", "_lhs_target_name", "_expression_text",
    "_module_name_of", "_function_name_of", "_typedef_name_of",
    "_enum_value_names",
]

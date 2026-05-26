"""Target module for v1.10-#1 module-import capture resolution fixture.

Intentionally empty (no top-level defs needed). Module B does
``import module_capture_a`` and captures the module object itself in a
lambda; the connector should classify that capture as ``module-import``
with ``origin_module == "module_capture_a"``.
"""

from __future__ import annotations

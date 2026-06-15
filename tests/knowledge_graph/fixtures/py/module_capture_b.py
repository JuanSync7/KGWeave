"""Consumer module for v1.10-#1 module-import capture resolution.

Imports a corpus-resident module (``module_capture_a``) and a stdlib
module (``json``, NOT in the corpus). A lambda captures both module
locals. The connector must classify the first as ``module-import`` with
``origin_module == "module_capture_a"`` and leave the second as
``unresolved`` (negative path within the same fixture).
"""

from __future__ import annotations

import json  # noqa: F401
import module_capture_a  # noqa: F401


use_modules = lambda x: (module_capture_a, json, x)  # noqa: E731

"""Module B — imports ``foo`` from ``crossfile_capture_a`` and
captures it inside a lambda (v1.9-#3).

The connector should tag the lambda's ``foo`` capture as
``cross-file-import`` with ``origin_module == "crossfile_capture_a"``.
"""

from __future__ import annotations

from crossfile_capture_a import foo


call_foo = lambda x: foo(x)  # noqa: E731

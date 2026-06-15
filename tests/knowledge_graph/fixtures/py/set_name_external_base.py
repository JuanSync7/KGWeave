"""Out-of-corpus set-name base (v1.14-#4 fixture).

set_name has chase_bases=False so this would not tag even if
the base were in-corpus; pinning the negative.
"""


class B(ExternalSetName):  # noqa: F821 — out-of-corpus base
    pass

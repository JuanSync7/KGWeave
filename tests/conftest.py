"""Common fixtures + pytest infra guards for KGWeave tests.

This module wires four cheap interim wins that prevent pytest from chewing the
16 GB tmpfs on /tmp and from hanging in kernel Dl state when a sibling pytest
steals I/O priority:

1. ``pytest_configure`` redirects ``basetemp`` to ``~/.pytest-tmp`` on the root
   FS unless the user explicitly passed ``--basetemp``.
2. ``pytest_sessionstart`` / ``pytest_sessionfinish`` manage a sibling-pytest
   lockfile at ``~/.kgweave-pytest.lock``.
3. An autouse function-scoped fixture rmtree's Kuzu store dirs (``*.kuzu``
   suffix OR a ``catalog.kz`` marker file) under each test's ``tmp_path`` on
   teardown -- finalizers see deletion before tmp_path itself is purged.
4. ``timeout`` / ``timeout_method`` are pinned in ``pyproject.toml``; see
   ``tests/README.md`` for context.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

# Make ``kgweave`` importable when running tests from the KGWeave repo root
# without an installed package (TDD mode).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# --------------------------------------------------------------------------- #
# Goal 4 helper -- exposed for unit testing.                                  #
# --------------------------------------------------------------------------- #
def _is_pytest_running(pid: int) -> bool:
    """Return True iff ``pid`` is a live process on this Linux box.

    Used by the lockfile guard to decide whether a stale ``~/.kgweave-pytest.lock``
    can be safely overwritten. ``pid <= 0`` is treated as not-running.
    """
    if pid <= 0:
        return False
    return Path(f"/proc/{pid}").exists()


_LOCKFILE = Path(os.path.expanduser("~/.kgweave-pytest.lock"))


# --------------------------------------------------------------------------- #
# Goal 1: redirect basetemp away from /tmp tmpfs.                             #
# --------------------------------------------------------------------------- #
def pytest_configure(config: pytest.Config) -> None:
    """Default ``basetemp`` to ~/.pytest-tmp (root FS) when caller didn't set it."""
    if config.option.basetemp is None:
        target = Path(os.path.expanduser("~/.pytest-tmp"))
        target.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(target)


# --------------------------------------------------------------------------- #
# Goal 4: sibling-pytest lockfile.                                            #
# --------------------------------------------------------------------------- #
def pytest_sessionstart(session: pytest.Session) -> None:
    """Refuse to start if a live sibling pytest already holds the lockfile."""
    if _LOCKFILE.exists():
        try:
            other_pid = int(_LOCKFILE.read_text().strip())
        except (ValueError, OSError):
            other_pid = 0
        if other_pid and other_pid != os.getpid() and _is_pytest_running(other_pid):
            raise pytest.UsageError(
                f"Another pytest run (pid={other_pid}) holds {_LOCKFILE}; "
                "refusing to start to avoid tmpfs / I/O contention. "
                "Wait for it to finish or delete the lockfile if stale."
            )
    _LOCKFILE.write_text(str(os.getpid()))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Drop the lockfile -- but only if it still points at us."""
    try:
        if _LOCKFILE.exists() and _LOCKFILE.read_text().strip() == str(os.getpid()):
            _LOCKFILE.unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Goal 3: autouse Kuzu store cleanup.                                         #
# --------------------------------------------------------------------------- #
def _iter_kuzu_dirs(root: Path):
    """Yield directories under ``root`` that look like a Kuzu store.

    A dir is Kuzu-shaped if its name ends in ``.kuzu`` OR it contains a
    ``catalog.kz`` file. We stay strictly within ``root`` -- ``os.walk`` is
    used with ``followlinks=False`` to avoid escaping tmp_path.
    """
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dp = Path(dirpath).resolve()
        # Belt-and-braces: refuse to descend outside the originally-resolved root.
        try:
            dp.relative_to(root)
        except ValueError:
            dirnames[:] = []
            continue
        for d in list(dirnames):
            if d.endswith(".kuzu"):
                yield dp / d
        if "catalog.kz" in filenames and dp != root:
            yield dp


@pytest.fixture(autouse=True)
def _kuzu_store_cleanup(request, tmp_path: Path):
    """After each test, rmtree any Kuzu-shaped dirs under its tmp_path.

    Runs strictly inside the test's own ``tmp_path`` -- never above it. Errors
    are swallowed (``ignore_errors=True``) because Kuzu sometimes leaves locked
    mmap handles on Linux when a test crashes mid-write.

    Ordering: pytest tears down fixtures in LIFO of setup order. Because this
    fixture is autouse, it sets up first and tears down last -- so any
    ``request.addfinalizer`` the test registers runs BEFORE this teardown. To
    let meta tests (and any future debug hook) verify cleanup happened, the
    fixture registers its own finalizer via ``request.addfinalizer`` from
    inside the setup phase, which by LIFO runs BEFORE the test body's own
    finalizers. We therefore use a plain yield (cleanup runs as the outermost
    teardown step) and additionally publish removed paths on
    ``request.node.kuzu_cleanup_removed`` for assertion-friendly testing.
    """
    request.node.kuzu_cleanup_removed = []
    try:
        yield
    finally:
        if not tmp_path.exists():
            return
        seen: set[Path] = set()
        for kuzu_dir in _iter_kuzu_dirs(tmp_path):
            if kuzu_dir in seen:
                continue
            seen.add(kuzu_dir)
            try:
                kuzu_dir.resolve().relative_to(tmp_path.resolve())
            except ValueError:
                continue
            shutil.rmtree(kuzu_dir, ignore_errors=True)
            request.node.kuzu_cleanup_removed.append(str(kuzu_dir))

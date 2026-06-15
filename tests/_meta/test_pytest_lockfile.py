"""Goal 4: sibling-worktree pytest guard via ~/.kgweave-pytest.lock.

Two pytest runs racing on the same box thrash the disk and trigger Dl hangs.
The session-start hook refuses to launch if a live sibling holds the lock.
"""
from __future__ import annotations

import os

from tests.conftest import _is_pytest_running


def test_self_pid_is_live() -> None:
    """The current process pid must be reported alive."""
    assert _is_pytest_running(os.getpid()) is True


def test_dead_pid_reported_not_running() -> None:
    """Pid 1 belongs to init -- but a wildly-high never-used pid must be dead."""
    # Pid space upper bound on Linux defaults to 4194304; 4_000_000 is almost
    # certainly unassigned during a CI run on a single dev box.
    assert _is_pytest_running(4_000_000) is False


def test_pid_zero_treated_as_not_running() -> None:
    """pid=0 is not a real process; helper must short-circuit to False."""
    assert _is_pytest_running(0) is False


def test_lockfile_exists_for_this_session() -> None:
    """During this very test, sessionstart hook should have written the lock with our pid."""
    lock = os.path.expanduser("~/.kgweave-pytest.lock")
    assert os.path.exists(lock), f"sessionstart hook did not create {lock}"
    pid = int(open(lock).read().strip())
    # The lock pid should be a live process (our pytest runner).
    assert _is_pytest_running(pid) is True

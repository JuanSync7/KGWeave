# KGWeave tests

Never run `pytest tests/` raw on this box. The suite is sized so that the default
`/tmp` tmpfs (16 GB) fills part-way through, and concurrent runs from sibling
worktrees (e.g. RagWeave) wedge pytest into 20+ min kernel `Dl` hangs. To
mitigate this, four pytest-infra guards are wired up:

- **basetemp** -- `tests/conftest.py:pytest_configure` redirects pytest's
  `basetemp` to `~/.pytest-tmp` (root FS) when the caller didn't pass
  `--basetemp` explicitly. Keeps Kuzu store dirs off the tmpfs.
- **timeout** -- `pyproject.toml [tool.pytest.ini_options]` pins
  `timeout = 60` with `timeout_method = "thread"` via `pytest-timeout`, so
  individual tests cannot wedge the suite when sibling I/O steals priority.
- **lockfile** -- `pytest_sessionstart` writes `~/.kgweave-pytest.lock` with
  the current pid and refuses to start if a live sibling already holds it;
  `pytest_sessionfinish` releases it. Stale locks (dead pid) are overwritten.
- **Kuzu cleanup** -- an autouse function-scoped fixture rmtree's any `*.kuzu`
  dirs or directories containing a `catalog.kz` marker file under each test's
  `tmp_path` on teardown, strictly scoped inside `tmp_path`.

Run targeted subsets only (e.g. `pytest tests/knowledge_graph/store/ -v`). The
meta tests that guard this infrastructure live under `tests/_meta/`.

## When disk gets tight

The four paths that grow without bound:

- `~/.pytest-tmp/` -- pytest basetemp (Kuzu DBs cleaned per-test by the autouse
  fixture, but the test-name dirs themselves persist).
- `~/.kgweave-tmp/` -- new default for `quickstart.py` / `quickstart_md.py`
  no-arg runs (replaces the legacy `./kgweave-store/` repo-root default that
  caused two disk-full events in v1.3).
- `~/.cache/uv/` -- wheel cache, ~7-8 GB after a few `uv add` cycles.
- `~/.cache/huggingface/hub/` -- model weights, ~3-4 GB if any builder ever
  loads an embedder.

`make disk-report` prints all five. `make clean-cache` runs `uv cache prune`
and removes HF dirs older than 30 days. `make clean-all` nukes every scratch
dir KGWeave controls -- safe to run any time, just costs a re-download on
next use.

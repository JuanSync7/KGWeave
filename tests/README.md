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

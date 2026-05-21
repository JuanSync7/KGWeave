.PHONY: install test lint typecheck clean clean-cache clean-all disk-report

install:
	uv pip install -e ".[dev]"

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +

# Trim the uv wheel cache + stale HF model cache when disk pressure mounts.
# Safe: re-runs of uv sync repopulate what's needed. HF re-downloads only
# the specific weights a test/run touches.
clean-cache:
	uv cache prune
	@if [ -d "$$HOME/.cache/huggingface/hub" ]; then \
		find "$$HOME/.cache/huggingface/hub" -mindepth 1 -maxdepth 1 -type d -mtime +30 -print -exec rm -rf {} +; \
	fi

# Nuke EVERY KGWeave-controlled scratch dir + caches. Use after a disk-full event.
clean-all: clean clean-cache
	rm -rf "$$HOME/.pytest-tmp" "$$HOME/.kgweave-tmp" ./kgweave-store

# One-liner disk report -- the paths that historically grow without bound.
disk-report:
	@echo "=== KGWeave disk footprint ==="
	@du -sh "$$HOME/.pytest-tmp" 2>/dev/null || echo "0    $$HOME/.pytest-tmp (absent)"
	@du -sh "$$HOME/.kgweave-tmp" 2>/dev/null || echo "0    $$HOME/.kgweave-tmp (absent)"
	@du -sh ./kgweave-store 2>/dev/null || echo "0    ./kgweave-store (absent)"
	@du -sh "$$HOME/.cache/uv" 2>/dev/null || echo "0    $$HOME/.cache/uv (absent)"
	@du -sh "$$HOME/.cache/huggingface" 2>/dev/null || echo "0    $$HOME/.cache/huggingface (absent)"
	@echo "=== /tmp tmpfs ==="
	@df -h /tmp | tail -1
	@echo "=== root FS ==="
	@df -h / | tail -1

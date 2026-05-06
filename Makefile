.PHONY: install test lint typecheck clean

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

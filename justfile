
test:
  PYTHONPATH=src uv run pytest -q

build:
  uv build

format:
  uv run ruff format .
  uv run ruff check --fix .

check-format:
  uv run ruff format --check .
  uv run ruff check .

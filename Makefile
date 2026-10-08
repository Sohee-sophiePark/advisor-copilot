# Advisor Copilot — developer commands.
# No target reads .env. Live targets (api, dev, record, smoke, eval-live) take GEMINI_API_KEY
# from the shell environment: run `set -a; . ./.env; set +a` once in your terminal first.

API_PORT ?= $(shell uv run advisor-copilot port)

.PHONY: fetch seed setup test lint format eval eval-live api web dev record smoke build-static env-check clean

setup:
	uv sync
	@if [ -f web/package.json ]; then npm --prefix web install; fi

fetch:  # laptop only; free sources; keys from the shell env (set -a; . ./.env; set +a)
	uv run advisor-copilot fetch

seed:
	uv run python data/generate_book.py
	uv run advisor-copilot seed

test:
	RUN_MODE=replay uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

eval:
	RUN_MODE=replay uv run python evals/run_evals.py --tier 1,2

eval-live:
	RUN_MODE=live uv run python evals/run_evals.py --tier 3 --k 3

api:
	DEV_CONSOLE=1 uv run uvicorn advisor_copilot.api.app:create_app --factory --host 127.0.0.1 --port $(API_PORT) --reload

web:
	API_PORT=$(API_PORT) npm --prefix web run dev

dev:  # with DATA_SOURCE=official, fetches first when the last fetch is over 20 hours old
	@if [ "$$DATA_SOURCE" = official ]; then uv run advisor-copilot fetch --if-stale; fi
	@trap 'kill 0' INT TERM; p=$$(uv run advisor-copilot port); $(MAKE) api API_PORT=$$p & $(MAKE) web API_PORT=$$p & wait

record:
	RUN_MODE=record uv run advisor-copilot record

smoke:
	RUN_MODE=live uv run advisor-copilot smoke

build-static:
	uv run advisor-copilot export web/public/static-data.json
	VITE_STATIC=1 npm --prefix web run build

env-check:
	@echo "GEMINI_API_KEY exported: $${GEMINI_API_KEY:+yes}$${GEMINI_API_KEY:-no}"

clean:
	rm -rf .pytest_cache .ruff_cache runs

# WikiMind — Development Workflow
# Usage: make <target>

SHELL := /bin/bash
.DEFAULT_GOAL := help
VENV := .venv
BIN := $(VENV)/bin
PYTHON := $(BIN)/python
PIP := $(BIN)/pip

# ══════════════════════════════════════════════════════════════════════════════

.PHONY: help
help: ## Show this help
	@echo ""
	@echo "🧠 WIKIMIND  (Personal LLM Knowledge OS)"
	@awk 'BEGIN {FS = ":.*## "} \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next } \
		/^[a-zA-Z_-]+:.*## / { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""

##@ 🌱 VIRTUAL ENVIRONMENT & INSTALLATION

.PHONY: venv
venv: ## Create Python virtual environment
	@echo "🌱  Creating virtual environment..."
	@python3 -m venv $(VENV)
	@$(PIP) install --upgrade pip > /dev/null
	@echo "✅  Created .venv — run 'make install-dev' next"

.PHONY: ensure-venv
ensure-venv:
	@test -d $(VENV) || (echo "🌱  No .venv found — creating..." && python3 -m venv $(VENV) && $(PIP) install --upgrade pip > /dev/null)

.PHONY: install
install: ensure-venv ## Install production dependencies
	@echo "📦  Installing production dependencies..."
	@$(PIP) install -e . > /dev/null
	@echo "✅  Install complete."

.PHONY: install-dev
install-dev: ensure-venv ## Install all dev/test/lint dependencies
	@echo "📦  Installing dev dependencies..."
	@$(PIP) install -e ".[dev]" > /dev/null
	@echo "✅  Install complete."

# Path to the editable install marker file inside the venv. We use this to
# detect when an agent worktree has hijacked the root venv (issue #66).
EDITABLE_PTH := $(VENV)/lib/python3.12/site-packages/__editable__.wikimind-0.1.0.pth
EXPECTED_SRC := $(abspath src)

.PHONY: check-venv
check-venv: ## Verify the venv editable install points at this checkout's src/
	@test -d $(VENV) || (echo "❌  No .venv found — run 'make venv' first" && exit 1)
	@test -f $(EDITABLE_PTH) || (echo "❌  No editable install — run 'make install-dev' or 'make repair-venv'" && exit 1)
	@actual=$$(cat $(EDITABLE_PTH) 2>/dev/null); \
	if [ "$$actual" != "$(EXPECTED_SRC)" ]; then \
	  echo "❌  Venv editable install is hijacked!"; \
	  echo ""; \
	  echo "    Expected: $(EXPECTED_SRC)"; \
	  echo "    Actual:   $$actual"; \
	  echo ""; \
	  echo "    A subagent worktree probably ran 'pip install -e .' inside its"; \
	  echo "    own copy and overwrote the root venv's editable path. The"; \
	  echo "    server would serve stale code from the agent's branch."; \
	  echo ""; \
	  echo "    Fix: run 'make repair-venv'"; \
	  exit 1; \
	fi
	@echo "✓ venv editable path: $(EXPECTED_SRC)"

.PHONY: repair-venv
repair-venv: ## Reinstall the editable package so it points at this checkout
	@echo "🔧  Reinstalling editable package..."
	@$(PIP) install -e . --force-reinstall --no-deps > /dev/null
	@echo "✅  Repaired. Restart 'make dev' to pick up changes."

.PHONY: check-env
check-env: check-venv ## Verify Python version, venv hygiene, and required tools
	@$(PYTHON) --version | grep -qE "3\.(11|12|13)" || (echo "ERROR: Python 3.11+ required" && exit 1)
	@echo "✓ Python: $$($(PYTHON) --version)"
	@test -f $(BIN)/ruff && echo "✓ ruff: $$($(BIN)/ruff --version)" || echo "✗ ruff not found (run: make install-dev)"
	@test -f $(BIN)/mypy && echo "✓ mypy: $$($(BIN)/mypy --version)" || echo "✗ mypy not found (run: make install-dev)"
	@test -f $(BIN)/pylint && echo "✓ pylint: $$($(BIN)/pylint --version | head -1)" || echo "✗ pylint not found (run: make install-dev)"
	@command -v npx >/dev/null 2>&1 && echo "✓ basedpyright: $$(npx basedpyright --version 2>/dev/null | head -1)" || echo "✗ basedpyright not found (requires Node.js + npx)"
	@test -f $(BIN)/pydocstyle && echo "✓ pydocstyle: $$($(BIN)/pydocstyle --version)" || echo "✗ pydocstyle not found (run: make install-dev)"
	@test -f $(BIN)/pytest && echo "✓ pytest: $$($(BIN)/pytest --version)" || echo "✗ pytest not found (run: make install-dev)"

##@ ▶️  SERVE

.PHONY: dev
dev: check-venv ## Run fast-reload dev server on :7842 (uvicorn)
	$(BIN)/uvicorn wikimind.main:app --host 127.0.0.1 --port 7842 --reload

.PHONY: serve
serve: ## Run production server on :7842 (gunicorn)
	$(BIN)/gunicorn wikimind.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:7842

.PHONY: worker
worker: ## Start ARQ background job worker
	$(PYTHON) -m arq wikimind.jobs.worker.WorkerSettings

##@ 🔍 QUALITY

.PHONY: pre-commit
pre-commit: ## Run all pre-commit hooks locally (same as CI)
	$(BIN)/pre-commit run --all-files

.PHONY: lint
lint: ## Run ruff linter on src/ and tests/ (includes pylint + pydocstyle rules)
	$(BIN)/ruff check src/ tests/

.PHONY: lint-fix
lint-fix: ## Auto-fix lint issues where possible
	$(BIN)/ruff check --fix src/ tests/

.PHONY: format
format: ## Format source code with ruff
	$(BIN)/ruff format src/ tests/

.PHONY: format-check
format-check: ## Check formatting without modifying files
	$(BIN)/ruff format --check src/ tests/

.PHONY: typecheck
typecheck: ## Run mypy type checking
	$(BIN)/mypy src/wikimind

.PHONY: pyright
pyright: ## Run basedpyright type checking (requires Node.js)
	@npx basedpyright src/wikimind

.PHONY: pylint
pylint: ## Run pylint static analysis (fails under 9.0/10)
	$(BIN)/pylint src/wikimind --fail-under=9.0

.PHONY: docstyle
docstyle: ## Run pydocstyle docstring checks
	$(BIN)/pydocstyle src/wikimind

.PHONY: verify
verify: lint format-check typecheck pyright docstyle test ## Run all checks (lint + format + mypy + pyright + docstyle + tests)

.PHONY: frontend-install
frontend-install: ## Install frontend dependencies
	cd apps/web && npm install

.PHONY: frontend-dev
frontend-dev: ## Start Vite dev server on :5173
	cd apps/web && npm run dev

.PHONY: frontend-build
frontend-build: ## Build frontend production bundle
	cd apps/web && npm run build

.PHONY: frontend-verify
frontend-verify: ## Run all frontend quality checks
	cd apps/web && npm run lint && npm run typecheck && npm run build

##@ 🧪 TESTING

.PHONY: test
test: ## Run unit + integration tests with pytest
	$(BIN)/pytest

.PHONY: test-unit
test-unit: ## Run unit tests only
	$(BIN)/pytest tests/unit -v

.PHONY: test-integration
test-integration: ## Run integration tests only
	$(BIN)/pytest tests/integration -v

.PHONY: coverage
coverage: ## Run tests with coverage report and HTML output
	$(BIN)/pytest --cov=wikimind --cov-report=term-missing --cov-report=html

.PHONY: test-matrix
test-matrix: ## Show how to run the LLM × document type benchmark
	@echo "Run a single matrix entry:"
	@echo "  python scripts/run_test_matrix.py --doc PATH --doc-type LABEL --question TEXT --provider PROVIDER"
	@echo ""
	@echo "See docs/test-matrix-results.md for results template and methodology."
	@echo "See scripts/README.md for full usage."

##@ 🗄️  DATABASE

.PHONY: db-reset
db-reset: ## Reset local SQLite database (recreated on next startup)
	rm -f ~/.wikimind/db/wikimind.db
	@echo "Database reset. Will be recreated on next startup."

##@ 🧹 CLEANUP

.PHONY: clean
clean: ## Remove caches, build artefacts, coverage files
	@echo "🧹  Cleaning workspace..."
	@echo "    removing __pycache__ directories"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "    removing .mypy_cache"
	@find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "    removing .ruff_cache"
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "    removing .pytest_cache"
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "    removing *.egg-info"
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "    removing coverage files"
	@rm -rf htmlcov .coverage
	@echo "✅  Clean complete."

.PHONY: clean-all
clean-all: clean ## Remove everything including .venv
	@echo "🧹  Removing virtual environment..."
	@rm -rf $(VENV)
	@echo "✅  Full clean complete."

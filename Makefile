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

.PHONY: check-env
check-env: ## Verify Python version and required tools are present
	@test -d $(VENV) || (echo "ERROR: No .venv found — run 'make venv' first" && exit 1)
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
dev: ## Run fast-reload dev server on :7842 (uvicorn)
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
lint: ## Run ruff linter (includes pylint + pydocstyle rules)
	$(BIN)/ruff check src/

.PHONY: lint-fix
lint-fix: ## Auto-fix lint issues where possible
	$(BIN)/ruff check --fix src/

.PHONY: format
format: ## Format source code with ruff
	$(BIN)/ruff format src/

.PHONY: format-check
format-check: ## Check formatting without modifying files
	$(BIN)/ruff format --check src/

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

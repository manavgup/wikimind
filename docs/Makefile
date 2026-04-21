# WikiMind Documentation — Build Automation
#
# Usage:
#   make venv    — create virtualenv with MkDocs dependencies
#   make serve   — start dev server at localhost:8003
#   make build   — production build to site/
#   make deploy  — deploy to gh-pages branch
#   make clean   — remove build artifacts

SHELL := /bin/bash
VENV := .venv
BIN := $(VENV)/bin
MKDOCS := $(BIN)/mkdocs

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: venv
venv: ## Create virtualenv with MkDocs dependencies
	python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt
	@echo "Docs venv ready. Run 'make serve' to start the dev server."

.PHONY: ensure-venv
ensure-venv:
	@test -f $(MKDOCS) || (echo "No docs venv found. Run 'make venv' first." && exit 1)

.PHONY: serve
serve: ensure-venv ## Development server at localhost:8003
	$(MKDOCS) serve -a localhost:8003

.PHONY: build
build: ensure-venv ## Production build to site/
	$(MKDOCS) build --strict

.PHONY: deploy
deploy: ensure-venv ## Deploy to gh-pages branch
	$(MKDOCS) gh-deploy --force

.PHONY: clean
clean: ## Remove build artifacts
	rm -rf site .cache
	@echo "Clean complete."

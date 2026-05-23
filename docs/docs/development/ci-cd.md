# CI/CD

WikiMind uses GitHub Actions for continuous integration and deployment.

## CI Pipeline

WikiMind splits CI across multiple GitHub Actions workflows. `Full Verify` (`full-verify.yml`) is the required merge gate. It runs `make verify` in CI so the authoritative verification sequence stays in the `Makefile` instead of being duplicated in workflow YAML.
It also installs the repo-root Node tooling manifest so `basedpyright` is pinned in version-controlled metadata instead of being fetched ad hoc via `npx`.

### Quality Gates

The following checks must pass before merging:

| Check | Command | Description |
|---|---|---|
| Lint | `make lint` | ruff linter (includes pylint + pydocstyle rules) |
| Format | `make format-check` | ruff formatter (check mode) |
| Type check | `make typecheck` | mypy static type checking |
| Pyright | `make pyright` | basedpyright type checking |
| Docstyle | `make docstyle` | pydocstyle docstring checks |
| Tests | `make coverage-check` | backend pytest suite with coverage (80% floor from pyproject.toml) |
| Frontend | `make frontend-verify` | ESLint + TypeScript + build |
| Desktop | `make desktop-verify` | Electron typecheck + build |
| Extension | `make extension-verify` | Browser extension typecheck + build |
| Doc sync | `make check-docs` | Verify generated docs are in sync |
| Dependency review | GitHub Action | Blocks vulnerable dependency changes in Python and frontend lockfiles |
| Bandit | `make bandit` | Python security scan for `src/wikimind` |
| CodeQL | GitHub Action | Repository code scanning for Python and TypeScript/JavaScript |

### Required vs supplemental workflows

- Required: `Full Verify` runs `make verify` and therefore covers `make lint`, `make format-check`, `make typecheck`, `make pyright`, `make docstyle`, `make coverage-check`, `make check-docs`, `make check-doc-sync`, `make check-layers`, `make desktop-verify`, and `make extension-verify`.
- Supplemental: the docs/smoke/e2e/Postgres-integration workflows provide faster or more specialized feedback, but they are not the canonical definition of the full verify suite.
- Intentional scope difference: `make verify` does not include `make frontend-verify`, so frontend checks remain a separate CI concern.

### Mock Provider for CI

Tests in CI use the mock LLM provider to avoid requiring API keys:

```bash
WIKIMIND_LLM__MOCK__ENABLED=true
WIKIMIND_LLM__DEFAULT_PROVIDER=mock
```

The mock provider returns deterministic JSON responses for compile, Q&A, and lint operations.

## Nightly Full-Stack Workflow

The `nightly.yml` workflow runs every day at `06:00 UTC` and can also be started manually with `workflow_dispatch`.

Currently the nightly workflow runs:

- backend coverage via `make coverage-ci` (with HTML + XML reports and Codecov upload)

Additional lanes (Postgres integration, Playwright e2e, Docker smoke, Bandit) run as separate path-filtered workflows on every PR and push to `main`, so nightly drift detection is provided by the weekly Docker rebuild (`docker.yml` schedule) and the weekly CodeQL scan (`codeql.yml` schedule).

## Coverage Gates

WikiMind uses two separate coverage guardrails:

- Total backend coverage: the GitHub Actions backend test job enforces a repository-wide floor via `make coverage-ci`.
- Changed-code coverage: Codecov receives the same `coverage.xml` upload on both pushes and pull requests, and `codecov.yml` defines a `codecov/patch` status for PRs.

Current Codecov policy:

- `codecov/project`: tracks overall backend coverage for the uploaded `backend` flag and allows a small 1% drop threshold.
- `codecov/patch`: requires `80%` coverage on changed backend lines in pull requests.

To make patch coverage a required merge gate, add the `codecov/patch` status check to the repository branch protection rules for `main`.

## Pre-Commit Hooks

Local pre-commit hooks mirror CI checks:

```bash
make pre-commit
```

This runs all pre-commit hooks plus mypy and unit tests. The hooks are configured to use the venv's Python to ensure consistent tool versions.

## Documentation Checks

The CI pipeline verifies that auto-generated documentation is in sync:

- **OpenAPI schema** -- `make check-openapi` verifies `docs/openapi.yaml` matches the FastAPI app
- **ADR index** -- `make check-adr-index` verifies `docs/adr/README.md` lists all ADR files
- **README targets** -- `make check-readme-targets` verifies the Make targets section is current

Bypass with `[skip-doc-check]` in the commit message or the `docs-skip` PR label.

## Deployment

### Fly.io

Deployment to Fly.io can be triggered manually or automated via CI:

```bash
fly deploy
```

For CI-automated deployment, set `FLY_API_TOKEN` as a repository secret and add a deploy step to the workflow.

### Documentation Site

The documentation site is built and deployed to GitHub Pages via the `docs.yml` workflow:

- **Trigger**: Push to `main` when files under `docs/` or `src/` change
- **Build**: MkDocs builds the site with `--strict` mode
- **Deploy**: Published to the `gh-pages` branch
- **URL**: [https://manavgup.github.io/wikimind/](https://manavgup.github.io/wikimind/)

## Dependency Security

The project uses:

- **Dependency Review** on pull requests that change Python dependency files or frontend `package.json` / `package-lock.json` files
- **bandit** for Python security scanning (`make bandit`) with JSON-to-SARIF conversion, code scanning upload in CI, and merge blocking only for medium-or-higher severity findings (`.github/workflows/bandit.yml`)
- **CodeQL** for GitHub code scanning across Python and JavaScript/TypeScript, including a weekly scheduled scan (`.github/workflows/codeql.yml`)
- **vulture** for dead code detection (`make vulture`)
- Pinned dependencies via `uv.lock` for reproducible builds

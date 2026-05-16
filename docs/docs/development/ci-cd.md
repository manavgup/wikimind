# CI/CD

WikiMind uses GitHub Actions for continuous integration and deployment.

## CI Pipeline

WikiMind splits CI across multiple GitHub Actions workflows. For test policy, the relevant workflow is `test.yml`, which runs on pushes to `main` and pull requests targeting `main` when backend test inputs change.

`Full Verify` is the required merge gate. It runs `make verify` in CI so the authoritative verification sequence stays in the `Makefile` instead of being duplicated in workflow YAML.
It also installs the repo-root Node tooling manifest so `basedpyright` is pinned in-version-controlled metadata instead of being fetched ad hoc via `npx`.

### Quality Gates

The following checks must pass before merging:

| Check | Command | Description |
|---|---|---|
| Lint | `make lint` | ruff linter (includes pylint + pydocstyle rules) |
| Format | `make format-check` | ruff formatter (check mode) |
| Type check | `make typecheck` | mypy static type checking |
| Pyright | `make pyright` | basedpyright type checking |
| Docstyle | `make docstyle` | pydocstyle docstring checks |
| Tests | `make coverage-ci` | backend pytest suite with HTML + XML coverage artifacts and an 80% repo floor in CI |
| Frontend | `make frontend-verify` | ESLint + TypeScript + build |
| Desktop | `make desktop-verify` | Electron typecheck + build |
| Extension | `make extension-verify` | Browser extension typecheck + build |
| Doc sync | `make check-docs` | Verify generated docs are in sync |
| Dependency review | GitHub Action | Blocks vulnerable dependency changes in Python and frontend lockfiles |
| Bandit | `make bandit` | Python security scan for `src/wikimind` |
| CodeQL | GitHub Action | Repository code scanning for Python and TypeScript/JavaScript |

### Required vs supplemental workflows

- Required: `Full Verify` runs `make verify` and therefore covers `make lint`, `make format-check`, `make typecheck`, `make pyright`, `make docstyle`, `make coverage-check`, `make desktop-verify`, and `make extension-verify`.
- Supplemental: `Tests & Coverage` and the docs/smoke/e2e workflows still provide faster or more specialized feedback, but they are not the canonical definition of the full verify suite.
- Intentional scope difference: `make verify` does not include `make frontend-verify` or `make check-docs`, so those remain separate CI checks rather than being folded into the required gate.

### Mock Provider for CI

Tests in CI use the mock LLM provider to avoid requiring API keys:

```bash
WIKIMIND_LLM__MOCK__ENABLED=true
WIKIMIND_LLM__DEFAULT_PROVIDER=mock
```

The mock provider returns deterministic JSON responses for compile, Q&A, and lint operations.

## Nightly Full-Stack Workflow

The `nightly.yml` workflow runs every day at `06:00 UTC` and can also be started manually with `workflow_dispatch`.

Nightly covers the runtime and integration surfaces that path-filtered PR CI can miss:

- backend coverage run via `make coverage-ci`
- PostgreSQL integration tests via `make test-postgres-ci`
- Playwright end-to-end coverage of the web app against the FastAPI backend
- Docker smoke tests against the production image
- Bandit security scanning via `make bandit`

This workflow is intentionally broader than PR CI because its job is drift detection: dependency breakage, runtime regressions, and environment-sensitive failures that may not be exercised by a narrow diff-triggered workflow.

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
- **bandit** for Python security scanning (`make bandit`) with JSON-to-SARIF conversion, code scanning upload in CI, and merge blocking only for medium-or-higher severity findings
- **CodeQL** for GitHub code scanning across Python and JavaScript/TypeScript, including a weekly scheduled scan
- a nightly Bandit run in `.github/workflows/nightly.yml`
- **vulture** for dead code detection (`make vulture`)
- Pinned dependencies via `uv.lock` for reproducible builds

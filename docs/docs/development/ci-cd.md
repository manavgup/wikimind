# CI/CD

WikiMind uses GitHub Actions for continuous integration and deployment.

## CI Pipeline

The primary CI pipeline runs on every pull request and push to `main`.

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
| Doc sync | `make check-docs` | Verify generated docs are in sync |

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
- Bandit security scanning via `make security-check`

This workflow is intentionally broader than PR CI because its job is drift detection: dependency breakage, runtime regressions, and environment-sensitive failures that may not be exercised by a narrow diff-triggered workflow.

## Coverage Gates

WikiMind now uses two separate coverage guardrails:

- Total backend coverage: the GitHub Actions backend test job still enforces a repository-wide floor via `make coverage-ci`.
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

- **bandit** for Python security scanning (`make bandit`)
- a nightly Bandit run in `.github/workflows/nightly.yml`
- **vulture** for dead code detection (`make vulture`)
- Pinned dependencies via `uv.lock` for reproducible builds

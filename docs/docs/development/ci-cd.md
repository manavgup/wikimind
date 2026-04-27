# CI/CD

WikiMind uses GitHub Actions for continuous integration and deployment.

## CI Pipeline

The CI pipeline runs on every pull request and push to `main`.

In addition to the broad lint, unit, and e2e workflows, CI now has two focused backend regression lanes:

- `auth-and-multiuser` runs the auth, endpoint dependency, and ownership/isolation regression subset via `make test-auth-multiuser`
- `postgres-integration` provisions PostgreSQL and runs the dedicated Postgres regression suite via `make test-postgres-integration`

### Quality Gates

The following checks must pass before merging:

| Check | Command | Description |
|---|---|---|
| Lint | `make lint` | ruff linter (includes pylint + pydocstyle rules) |
| Format | `make format-check` | ruff formatter (check mode) |
| Type check | `make typecheck` | mypy static type checking |
| Pyright | `make pyright` | basedpyright type checking |
| Docstyle | `make docstyle` | pydocstyle docstring checks |
| Tests | `make coverage-check` | pytest with 80% coverage threshold |
| Auth & multi-user | `make test-auth-multiuser` | Focused auth, dependency wiring, and user-isolation regressions |
| Postgres integration | `make test-postgres-integration` | PostgreSQL-backed integration regression suite |
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
- **vulture** for dead code detection (`make vulture`)
- Pinned dependencies via `uv.lock` for reproducible builds

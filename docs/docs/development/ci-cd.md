# CI/CD

WikiMind uses GitHub Actions for continuous integration and deployment.

## CI Pipeline

The CI pipeline runs on every pull request and push to `main`.

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
| Tests | `make coverage-check` | pytest with 80% coverage threshold |
| Desktop | `make desktop-verify` | Electron typecheck + build |
| Extension | `make extension-verify` | Browser extension typecheck + build |
| Frontend | `make frontend-verify` | ESLint + TypeScript + build |
| Doc sync | `make check-docs` | Verify generated docs are in sync |

### Required vs supplemental workflows

- Required: `Full Verify` runs `make verify` and therefore covers `make lint`, `make format-check`, `make typecheck`, `make pyright`, `make docstyle`, `make coverage-check`, `make desktop-verify`, and `make extension-verify`.
- Supplemental: `Lint & Static Analysis`, `Tests & Coverage`, `Pre-commit Checks`, and the docs/smoke/e2e workflows still provide faster or more specialized feedback, but they are not the canonical definition of the full verify suite.
- Intentional scope difference: `make verify` does not include `make frontend-verify` or `make check-docs`, so those remain separate CI checks rather than being folded into the required gate.

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

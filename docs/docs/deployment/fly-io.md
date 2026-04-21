# Fly.io Deployment

WikiMind can be deployed to [Fly.io](https://fly.io) for cloud hosting with auto-scaling.

## First-Time Setup

Use the setup script to create all Fly.io infrastructure:

```bash
make fly-setup
# or directly:
./scripts/fly-setup.sh
```

This creates:

- The Fly app (`wikimind`)
- A persistent volume (`wikimind_data`) for the data directory
- A Postgres cluster (if needed)
- Secrets for API keys

## Deploying

```bash
fly deploy
```

Set secrets for your LLM provider:

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
# or
fly secrets set OPENAI_API_KEY=sk-...
```

## Configuration

The `fly.toml` configures:

```toml
app = "wikimind"
primary_region = "ord"

[env]
  WIKIMIND_SERVER__HOST = "0.0.0.0"
  WIKIMIND_SERVER__PORT = "7842"
  WIKIMIND_DOCLING_SERVE_URL = "http://wikimind-docling.internal:5001"
  WEB_CONCURRENCY = "4"

[http_service]
  internal_port = 7842
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

  [http_service.concurrency]
    type = "connections"
    hard_limit = 50
    soft_limit = 25

[mounts]
  source = "wikimind_data"
  destination = "/home/wikimind/.wikimind"

[[vm]]
  memory = "1gb"
  cpu_kind = "shared"
  cpus = 1
```

Key points:

- **Auto-scaling** -- Machines auto-stop when idle and auto-start on incoming connections.
- **HTTPS** -- Forced for all traffic.
- **Persistent storage** -- The `wikimind_data` volume is mounted at `/home/wikimind/.wikimind`.
- **Health checks** -- `GET /health` every 30s with a 60s grace period.
- **Rolling deploys** -- The `rolling` strategy ensures zero-downtime deployments.

## PDF Processing Sidecar

WikiMind uses a separate docling-serve app for PDF extraction. Deploy it alongside the main app using `fly.docling.toml`:

```bash
fly deploy --config fly.docling.toml
```

The main app connects to it via Fly's internal DNS: `http://wikimind-docling.internal:5001`.

## Database

### Fly Postgres

Fly.io sets `DATABASE_URL` automatically when you attach a managed Postgres instance. WikiMind detects this and rewrites the URL for async compatibility (`postgresql+asyncpg://`).

The app also handles:

- **`sslmode` conversion** -- Fly.io sets `?sslmode=disable` which is not valid for asyncpg. WikiMind converts this automatically.
- **Internal SSL** -- Fly.io internal Postgres does not support SSL. When running on Fly (detected via `FLY_APP_NAME`), SSL is explicitly disabled.

### SQLite (single machine)

For simple single-machine deployments, the default SQLite database works. Data is stored on the persistent volume.

## CI/CD

Automated deployments can be configured in GitHub Actions. On merge to `main`, the workflow can build and deploy:

```yaml
- name: Deploy to Fly.io
  uses: superfly/flyctl-actions/setup-flyctl@master
- run: flyctl deploy --remote-only
  env:
    FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

## Monitoring

```bash
# View logs
fly logs

# Check app status
fly status

# SSH into the machine
fly ssh console

# View metrics
fly dashboard
```

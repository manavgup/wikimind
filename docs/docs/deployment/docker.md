# Docker Deployment

WikiMind provides Docker Compose configurations for both local development and production deployment.

## Development Stack

The development stack mounts your source code for hot-reloading:

```bash
make docker-up
```

Services:

| Service | Description | Port |
|---|---|---|
| `gateway` | FastAPI app with uvicorn (hot-reload) | 7842 |
| `worker` | ARQ background job worker | -- |
| `redis` | Job queue broker | 6379 |
| `docling` | PDF extraction sidecar | 5001 |

Data is persisted in Docker volumes (`wikimind-data`, `wikimind-redis`).

### Development commands

```bash
make docker-build     # Build the dev image
make docker-up        # Start the stack (uses cached image)
make docker-up-build  # Rebuild and start
make docker-logs      # Tail logs from all services
make docker-down      # Stop and remove the stack
```

The dev stack uses `docker-compose.yml` which mounts `./src` and `./tests` into the container, so code changes are reflected immediately.

## Production Stack

The production stack runs a complete deployment with PostgreSQL:

```bash
POSTGRES_PASSWORD=changeme make deploy-up
```

!!! warning "Set a strong password"
    Always set `POSTGRES_PASSWORD` to a strong, unique value. The compose file refuses to start without it.

### Services

| Service | Description | Port | Resources |
|---|---|---|---|
| `gateway` | FastAPI app with gunicorn | 7842 | 2 CPU, 1GB |
| `worker` | ARQ background worker | -- | 1 CPU, 1GB |
| `postgres` | PostgreSQL 16 | -- | 1 CPU, 1GB |
| `redis` | Job queue broker | -- | 0.5 CPU, 512MB |
| `docling` | PDF extraction sidecar | 5001 | 2 CPU, 4GB |

### Configuration

All production settings are sourced from `.env` or shell environment:

```bash
# Required
POSTGRES_PASSWORD=your-strong-password

# Optional (with defaults shown)
POSTGRES_USER=wikimind
POSTGRES_DB=wikimind
WIKIMIND_PORT=7842
WIKIMIND_IMAGE=wikimind:latest
```

Gunicorn workers auto-tune to available CPU cores (see `gunicorn.conf.py`). Override with:

```bash
WEB_CONCURRENCY=4 POSTGRES_PASSWORD=changeme make deploy-up
```

### Production commands

```bash
make deploy-up     # Build and start the production stack
make deploy-stop   # Stop the production stack (preserves data)
make deploy-logs   # Tail logs from all services
make deploy-ps     # Show service status
```

### PostgreSQL tuning

The production Postgres container is configured with:

- `max_connections=100`
- `shared_buffers=128MB`
- `work_mem=4MB`
- `statement_timeout=60s`
- `idle_in_transaction_session_timeout=120s`

Data is persisted in the `wikimind-pgdata` volume.

### Health checks

All services have health checks configured:

- **Gateway**: `GET /health` every 10s (60s start period)
- **Worker**: Depends on gateway health
- **Postgres**: `pg_isready` every 10s (15s start period)
- **Redis**: `redis-cli ping` every 10s
- **Docling**: `GET /health` every 30s

### Scaling

The production compose file supports horizontal scaling for the gateway:

```bash
docker compose -f docker-compose.prod.yml up -d --scale gateway=3
```

No `container_name` is set on the gateway service to allow this.

## LLM API Keys

Pass LLM API keys via `.env` file or environment variables. The compose files include:

```yaml
env_file:
  - path: .env
    required: false
```

So any keys in your `.env` are automatically available to the gateway and worker.

## Networking

The production stack uses a dedicated `wikimindnet` bridge network. Services communicate via Docker DNS (e.g., `postgres:5432`, `redis:6379`).

The development stack uses Docker Compose's default network.

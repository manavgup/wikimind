#!/usr/bin/env bash
# ---------------------------------------------------------------
# Fly.io Infrastructure Setup — idempotent
#
# Creates the app, volume, Postgres cluster, and configures
# secrets. Safe to re-run — each step checks whether the
# resource already exists before creating it.
#
# Redis runs inside the web machine (docker/start-combined.sh) —
# no separate Redis app or volume is needed. WIKIMIND_REDIS_URL is
# provided via [env] in fly.toml and does NOT require a Fly secret.
#
# Usage:
#   # Interactive (prompts for missing secrets):
#   ./scripts/fly-setup.sh
#
#   # Non-interactive (all secrets via env vars):
#   ANTHROPIC_API_KEY=sk-ant-... \
#   WIKIMIND_AUTH__GOOGLE_CLIENT_ID=... \
#   WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET=... \
#   WIKIMIND_AUTH__GITHUB_CLIENT_ID=... \
#   WIKIMIND_AUTH__GITHUB_CLIENT_SECRET=... \
#     ./scripts/fly-setup.sh
#
# Prerequisites:
#   brew install flyctl && fly auth login
# ---------------------------------------------------------------
set -euo pipefail

APP_NAME="wikimind"
REGION="ord"
VOLUME_NAME="wikimind_data"
VOLUME_SIZE_GB=1
PG_NAME="wikimind-db"

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------
info()  { printf '  ✅  %s\n' "$*"; }
warn()  { printf '  ⚠️   %s\n' "$*"; }
step()  { printf '\n🔹 %s\n' "$*"; }

require_flyctl() {
    if ! command -v flyctl &>/dev/null; then
        echo "ERROR: flyctl not found. Install with: brew install flyctl"
        exit 1
    fi
    if ! flyctl auth whoami &>/dev/null; then
        echo "ERROR: Not logged in. Run: fly auth login"
        exit 1
    fi
}

prompt_secret() {
    local var_name="$1" description="$2"
    local value="${!var_name:-}"
    if [[ -n "$value" ]]; then
        return 0
    fi
    read -rp "  Enter ${description}: " value
    if [[ -z "$value" ]]; then
        warn "Skipping ${var_name} (empty)"
        return 1
    fi
    export "${var_name}=${value}"
}

set_secret_if_provided() {
    local fly_key="$1" env_var="$2"
    local value="${!env_var:-}"
    if [[ -n "$value" ]]; then
        flyctl secrets set "${fly_key}=${value}" --app "$APP_NAME" --stage
        info "Staged ${fly_key}"
    fi
}

# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
require_flyctl

# 1. Create app
step "App: ${APP_NAME}"
if flyctl apps list --json | python3 -c "import sys,json; apps=[a['Name'] for a in json.load(sys.stdin)]; sys.exit(0 if '${APP_NAME}' in apps else 1)" 2>/dev/null; then
    info "Already exists"
else
    flyctl apps create "$APP_NAME" --json
    info "Created"
fi

# 2. Create volume
step "Volume: ${VOLUME_NAME} (${VOLUME_SIZE_GB} GB in ${REGION})"
if flyctl volumes list --app "$APP_NAME" --json | python3 -c "import sys,json; vols=[v['name'] for v in json.load(sys.stdin)]; sys.exit(0 if '${VOLUME_NAME}' in vols else 1)" 2>/dev/null; then
    info "Already exists"
else
    flyctl volumes create "$VOLUME_NAME" \
        --app "$APP_NAME" \
        --region "$REGION" \
        --size "$VOLUME_SIZE_GB" \
        --yes
    info "Created"
fi

# 3. Create and attach Postgres
step "Postgres: ${PG_NAME}"
if flyctl apps list --json | python3 -c "import sys,json; apps=[a['Name'] for a in json.load(sys.stdin)]; sys.exit(0 if '${PG_NAME}' in apps else 1)" 2>/dev/null; then
    info "Already exists"
else
    flyctl postgres create \
        --name "$PG_NAME" \
        --region "$REGION" \
        --vm-size shared-cpu-1x \
        --initial-cluster-size 1 \
        --volume-size 1
    info "Created"
fi

# Attach (idempotent — fails silently if already attached)
step "Attaching Postgres to ${APP_NAME}"
if flyctl postgres attach "$PG_NAME" --app "$APP_NAME" 2>/dev/null; then
    info "Attached (DATABASE_URL set automatically)"
else
    info "Already attached"
fi

# 4. Configure secrets
step "Secrets"

# LLM provider key
prompt_secret "ANTHROPIC_API_KEY" "Anthropic API key (sk-ant-...)" || true
set_secret_if_provided "ANTHROPIC_API_KEY" "ANTHROPIC_API_KEY"

# JWT secret — auto-generate if not provided
if [[ -z "${WIKIMIND_AUTH__JWT_SECRET_KEY:-}" ]]; then
    export WIKIMIND_AUTH__JWT_SECRET_KEY
    WIKIMIND_AUTH__JWT_SECRET_KEY=$(openssl rand -hex 32)
    info "Auto-generated JWT secret"
fi
set_secret_if_provided "WIKIMIND_AUTH__JWT_SECRET_KEY" "WIKIMIND_AUTH__JWT_SECRET_KEY"

# Auth enabled
flyctl secrets set "WIKIMIND_AUTH__ENABLED=true" --app "$APP_NAME" --stage
info "Staged WIKIMIND_AUTH__ENABLED=true"

# OAuth credentials
prompt_secret "WIKIMIND_AUTH__GOOGLE_CLIENT_ID" "Google OAuth Client ID" || true
prompt_secret "WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET" "Google OAuth Client Secret" || true
prompt_secret "WIKIMIND_AUTH__GITHUB_CLIENT_ID" "GitHub OAuth Client ID" || true
prompt_secret "WIKIMIND_AUTH__GITHUB_CLIENT_SECRET" "GitHub OAuth Client Secret" || true

set_secret_if_provided "WIKIMIND_AUTH__GOOGLE_CLIENT_ID" "WIKIMIND_AUTH__GOOGLE_CLIENT_ID"
set_secret_if_provided "WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET" "WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET"
set_secret_if_provided "WIKIMIND_AUTH__GITHUB_CLIENT_ID" "WIKIMIND_AUTH__GITHUB_CLIENT_ID"
set_secret_if_provided "WIKIMIND_AUTH__GITHUB_CLIENT_SECRET" "WIKIMIND_AUTH__GITHUB_CLIENT_SECRET"

# Deploy staged secrets
step "Deploying staged secrets"
flyctl secrets deploy --app "$APP_NAME"
info "All secrets deployed"

# 5. Generate deploy token
step "Deploy token for CI"
echo "  Add this token as FLY_API_TOKEN in GitHub repo secrets:"
echo "  GitHub → Settings → Secrets and variables → Actions → New repository secret"
echo ""
flyctl tokens create deploy --app "$APP_NAME" -x 999999h
echo ""

# 6. Summary
step "Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. Add FLY_API_TOKEN to GitHub repo secrets (printed above)"
echo "    2. Update Google OAuth redirect URI to: https://${APP_NAME}.fly.dev/auth/google/callback"
echo "    3. Update GitHub OAuth callback URL to: https://${APP_NAME}.fly.dev/auth/github/callback"
echo "    4. Deploy: fly deploy"
echo "    5. Verify: curl https://${APP_NAME}.fly.dev/health"
echo ""

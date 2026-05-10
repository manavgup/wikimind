#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5433}"
PGUSER="${PGUSER:-wikimind}"
PGPASSWORD="${PGPASSWORD:-wikimind}"
export PGHOST PGPORT PGUSER PGPASSWORD

ADMIN_DB="${ADMIN_DB:-postgres}"
KEEP_DBS=0
MODE="matrix"
SCHEMA_SQL=""
DATA_SQL=""

usage() {
  cat <<'EOF'
Usage:
  scripts/test_migration_0010.sh [--keep-dbs]
  scripts/test_migration_0010.sh fly-replay --schema-sql /tmp/fly-schema.sql [--data-sql /tmp/fly-data.sql] [--keep-dbs]

What it does:
  1. Creates scratch Postgres databases on the local dev Postgres instance.
  2. Runs Alembic upgrade head against migration 0010.
  3. Runs wikimind.database.init_db() to simulate app startup.
  4. Verifies that:
     - alembic_version is 0010
     - old table names are gone
     - new table names exist
     - row counts are preserved in rename scenarios

Default local Postgres connection:
  PGHOST=localhost
  PGPORT=5433
  PGUSER=wikimind
  PGPASSWORD=wikimind

Examples:
  make pg-up
  scripts/test_migration_0010.sh

  fly proxy 6543:5432 -a wikimind-db
  pg_dump -h localhost -p 6543 -U wikimind --schema-only > /tmp/fly-schema.sql
  pg_dump -h localhost -p 6543 -U wikimind \
    -t compiled_claim -t concept_cluster -t claim_concept -t compilation_schema \
    --data-only > /tmp/fly-data.sql
  scripts/test_migration_0010.sh fly-replay \
    --schema-sql /tmp/fly-schema.sql \
    --data-sql /tmp/fly-data.sql
EOF
}

log() {
  printf '\n==> %s\n' "$1"
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

psql_db() {
  local db="$1"
  shift
  psql -v ON_ERROR_STOP=1 -X -d "$db" "$@"
}

psql_admin() {
  psql_db "$ADMIN_DB" "$@"
}

drop_db_if_exists() {
  local db="$1"
  dropdb --if-exists "$db" >/dev/null 2>&1 || true
}

create_clean_db() {
  local db="$1"
  drop_db_if_exists "$db"
  createdb "$db"
}

db_url() {
  local db="$1"
  printf 'postgresql+asyncpg://%s:%s@%s:%s/%s' "$PGUSER" "$PGPASSWORD" "$PGHOST" "$PGPORT" "$db"
}

seed_minimal_base_schema() {
  local db="$1"
  psql_db "$db" <<'SQL'
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);
INSERT INTO alembic_version (version_num) VALUES ('0009');

CREATE TABLE "user" (
    id VARCHAR NOT NULL PRIMARY KEY
);

CREATE TABLE article (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES "user"(id)
);

INSERT INTO "user" (id) VALUES ('user-1');
INSERT INTO article (id, user_id) VALUES ('article-1', 'user-1');
SQL
}

seed_old_named_tables() {
  local db="$1"
  psql_db "$db" <<'SQL'
CREATE TABLE compiled_claim (
    id VARCHAR NOT NULL PRIMARY KEY,
    article_id VARCHAR NOT NULL REFERENCES article(id),
    user_id VARCHAR NOT NULL REFERENCES "user"(id),
    text VARCHAR NOT NULL,
    subjects VARCHAR NOT NULL,
    predicate VARCHAR,
    confidence_level VARCHAR NOT NULL,
    confidence_score FLOAT NOT NULL,
    source_ids VARCHAR NOT NULL,
    last_reinforced_at TIMESTAMP NOT NULL,
    quote VARCHAR,
    embedding BYTEA,
    embedding_version VARCHAR,
    cluster_assignment_reconciled BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
CREATE INDEX ix_compiled_claim_user_id ON compiled_claim (user_id);
CREATE INDEX ix_compiled_claim_article_id ON compiled_claim (article_id);

CREATE TABLE concept_cluster (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES "user"(id),
    canonical_text VARCHAR NOT NULL,
    centroid_embedding BYTEA,
    embedding_version VARCHAR,
    member_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    superseded_by VARCHAR REFERENCES concept_cluster(id),
    last_reinforced_at TIMESTAMP NOT NULL,
    last_reconciled_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
CREATE INDEX ix_concept_cluster_user_id ON concept_cluster (user_id);

CREATE TABLE compilation_schema (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES "user"(id),
    name VARCHAR NOT NULL,
    description VARCHAR,
    is_active BOOLEAN NOT NULL,
    article_max_length INTEGER,
    required_sections VARCHAR,
    style VARCHAR,
    focus VARCHAR,
    concept_max_depth INTEGER,
    concept_naming VARCHAR,
    extraction_always_note VARCHAR,
    extraction_ignore VARCHAR,
    custom_directives VARCHAR,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_compilation_schema_user_name UNIQUE (user_id, name)
);
CREATE INDEX ix_compilation_schema_user_id ON compilation_schema (user_id);

CREATE TABLE claim_concept (
    claim_id VARCHAR NOT NULL REFERENCES compiled_claim(id),
    concept_id VARCHAR NOT NULL REFERENCES concept_cluster(id),
    role VARCHAR NOT NULL,
    advisory BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (claim_id, concept_id, role)
);
CREATE INDEX ix_claim_concept_concept_id ON claim_concept (concept_id);

INSERT INTO compiled_claim (
    id, article_id, user_id, text, subjects, predicate, confidence_level,
    confidence_score, source_ids, last_reinforced_at, quote, embedding,
    embedding_version, cluster_assignment_reconciled, created_at, updated_at
) VALUES (
    'claim-1', 'article-1', 'user-1', 'Old claim row', '["AI"]', NULL, 'high',
    0.9, '["source-1"]', NOW(), NULL, NULL, NULL, FALSE, NOW(), NOW()
);

INSERT INTO concept_cluster (
    id, user_id, canonical_text, centroid_embedding, embedding_version,
    member_count, status, superseded_by, last_reinforced_at,
    last_reconciled_at, created_at, updated_at
) VALUES (
    'cluster-1', 'user-1', 'AI', NULL, NULL, 1, 'candidate', NULL, NOW(),
    NULL, NOW(), NOW()
);

INSERT INTO claim_concept (
    claim_id, concept_id, role, advisory, created_at
) VALUES (
    'claim-1', 'cluster-1', 'subject', TRUE, NOW()
);

INSERT INTO compilation_schema (
    id, user_id, name, description, is_active, article_max_length,
    required_sections, style, focus, concept_max_depth, concept_naming,
    extraction_always_note, extraction_ignore, custom_directives,
    created_at, updated_at
) VALUES (
    'schema-1', 'user-1', 'Default', 'Old schema row', FALSE, NULL, NULL,
    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NOW(), NOW()
);
SQL
}

seed_new_named_collision_tables() {
  local db="$1"
  psql_db "$db" <<'SQL'
CREATE TABLE compiledclaim (
    id VARCHAR NOT NULL PRIMARY KEY,
    article_id VARCHAR NOT NULL REFERENCES article(id),
    user_id VARCHAR NOT NULL REFERENCES "user"(id),
    text VARCHAR NOT NULL,
    subjects VARCHAR NOT NULL,
    predicate VARCHAR,
    confidence_level VARCHAR NOT NULL,
    confidence_score FLOAT NOT NULL,
    source_ids VARCHAR NOT NULL,
    last_reinforced_at TIMESTAMP NOT NULL,
    quote VARCHAR,
    embedding BYTEA,
    embedding_version VARCHAR,
    cluster_assignment_reconciled BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE conceptcluster (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES "user"(id),
    canonical_text VARCHAR NOT NULL,
    centroid_embedding BYTEA,
    embedding_version VARCHAR,
    member_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    superseded_by VARCHAR REFERENCES conceptcluster(id),
    last_reinforced_at TIMESTAMP NOT NULL,
    last_reconciled_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE compilationschema (
    id VARCHAR NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES "user"(id),
    name VARCHAR NOT NULL,
    description VARCHAR,
    is_active BOOLEAN NOT NULL,
    article_max_length INTEGER,
    required_sections VARCHAR,
    style VARCHAR,
    focus VARCHAR,
    concept_max_depth INTEGER,
    concept_naming VARCHAR,
    extraction_always_note VARCHAR,
    extraction_ignore VARCHAR,
    custom_directives VARCHAR,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_compilationschema_user_name UNIQUE (user_id, name)
);

CREATE TABLE claimconcept (
    claim_id VARCHAR NOT NULL REFERENCES compiledclaim(id),
    concept_id VARCHAR NOT NULL REFERENCES conceptcluster(id),
    role VARCHAR NOT NULL,
    advisory BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (claim_id, concept_id, role)
);
SQL
}

run_alembic_upgrade() {
  local db="$1"
  local url
  url="$(db_url "$db")"
  log "Running alembic upgrade head on $db"
  WIKIMIND_DATABASE_URL="$url" .venv/bin/python -m alembic upgrade head
}

run_init_db() {
  local db="$1"
  local url
  url="$(db_url "$db")"
  log "Running init_db() on $db"
  WIKIMIND_DATABASE_URL="$url" .venv/bin/python - <<'PY'
import asyncio
from wikimind.database import init_db
asyncio.run(init_db())
PY
}

assert_equals() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [[ "$expected" != "$actual" ]]; then
    die "$message (expected=$expected actual=$actual)"
  fi
}

query_value() {
  local db="$1"
  local sql="$2"
  psql_db "$db" -At -c "$sql"
}

verify_common_post_conditions() {
  local db="$1"

  assert_equals "0010" "$(query_value "$db" "SELECT version_num FROM alembic_version;")" \
    "alembic_version should be 0010"

  assert_equals "compiledclaim" "$(query_value "$db" "SELECT to_regclass('public.compiledclaim');")" \
    "compiledclaim should exist"
  assert_equals "conceptcluster" "$(query_value "$db" "SELECT to_regclass('public.conceptcluster');")" \
    "conceptcluster should exist"
  assert_equals "claimconcept" "$(query_value "$db" "SELECT to_regclass('public.claimconcept');")" \
    "claimconcept should exist"
  assert_equals "compilationschema" "$(query_value "$db" "SELECT to_regclass('public.compilationschema');")" \
    "compilationschema should exist"

  assert_equals "" "$(query_value "$db" "SELECT to_regclass('public.compiled_claim');")" \
    "compiled_claim should be gone"
  assert_equals "" "$(query_value "$db" "SELECT to_regclass('public.concept_cluster');")" \
    "concept_cluster should be gone"
  assert_equals "" "$(query_value "$db" "SELECT to_regclass('public.claim_concept');")" \
    "claim_concept should be gone"
  assert_equals "" "$(query_value "$db" "SELECT to_regclass('public.compilation_schema');")" \
    "compilation_schema should be gone"
}

verify_counts() {
  local db="$1"
  local expected="$2"
  assert_equals "$expected" "$(query_value "$db" "SELECT count(*) FROM compiledclaim;")" \
    "compiledclaim row count mismatch"
  assert_equals "$expected" "$(query_value "$db" "SELECT count(*) FROM conceptcluster;")" \
    "conceptcluster row count mismatch"
  assert_equals "$expected" "$(query_value "$db" "SELECT count(*) FROM claimconcept;")" \
    "claimconcept row count mismatch"
  assert_equals "$expected" "$(query_value "$db" "SELECT count(*) FROM compilationschema;")" \
    "compilationschema row count mismatch"
}

verify_fk_join() {
  local db="$1"
  local count
  count="$(query_value "$db" "SELECT count(*) FROM claimconcept cc JOIN compiledclaim c ON c.id = cc.claim_id JOIN conceptcluster k ON k.id = cc.concept_id;")"
  assert_equals "1" "$count" "claimconcept foreign-key join should still work"
}

run_scenario() {
  local scenario="$1"
  local db="wikimind_0010_${scenario}_$$"

  log "Preparing scenario: $scenario"
  create_clean_db "$db"
  seed_minimal_base_schema "$db"

  case "$scenario" in
    fresh)
      ;;
    old_only)
      seed_old_named_tables "$db"
      ;;
    collision)
      seed_old_named_tables "$db"
      seed_new_named_collision_tables "$db"
      ;;
    *)
      die "unknown scenario: $scenario"
      ;;
  esac

  run_alembic_upgrade "$db"
  run_init_db "$db"
  verify_common_post_conditions "$db"

  if [[ "$scenario" == "fresh" ]]; then
    verify_counts "$db" "0"
  else
    verify_counts "$db" "1"
    verify_fk_join "$db"
  fi

  log "Scenario passed: $scenario ($db)"
  if [[ "$KEEP_DBS" -ne 1 ]]; then
    drop_db_if_exists "$db"
  fi
}

run_fly_replay() {
  [[ -n "$SCHEMA_SQL" ]] || die "--schema-sql is required for fly-replay"
  [[ -f "$SCHEMA_SQL" ]] || die "schema SQL file not found: $SCHEMA_SQL"
  if [[ -n "$DATA_SQL" && ! -f "$DATA_SQL" ]]; then
    die "data SQL file not found: $DATA_SQL"
  fi

  local db="wikimind_0010_fly_replay_$$"
  log "Preparing Fly replay DB: $db"
  create_clean_db "$db"
  psql_db "$db" -f "$SCHEMA_SQL"
  if [[ -n "$DATA_SQL" ]]; then
    psql_db "$db" -f "$DATA_SQL"
  fi

  run_alembic_upgrade "$db"
  run_init_db "$db"
  verify_common_post_conditions "$db"

  log "Fly replay checks"
  psql_db "$db" -c "SELECT count(*) AS compiledclaim_rows FROM compiledclaim;"
  psql_db "$db" -c "SELECT count(*) AS conceptcluster_rows FROM conceptcluster;"
  psql_db "$db" -c "SELECT count(*) AS claimconcept_rows FROM claimconcept;"
  psql_db "$db" -c "SELECT count(*) AS compilationschema_rows FROM compilationschema;"

  log "Fly replay passed: $db"
  if [[ "$KEEP_DBS" -ne 1 ]]; then
    drop_db_if_exists "$db"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      fly-replay)
        MODE="fly-replay"
        shift
        ;;
      --schema-sql)
        SCHEMA_SQL="${2:-}"
        shift 2
        ;;
      --data-sql)
        DATA_SQL="${2:-}"
        shift 2
        ;;
      --keep-dbs)
        KEEP_DBS=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
  done
}

main() {
  require_cmd psql
  require_cmd createdb
  require_cmd dropdb
  [[ -x .venv/bin/python ]] || die "missing .venv/bin/python; run make venv && make install-dev"
  [[ -f alembic/versions/0010_add_concept_layer_tables.py ]] || \
    die "migration 0010 not found in this checkout; run from the PR branch/worktree"

  parse_args "$@"

  log "Checking local Postgres connection"
  psql_admin -c "SELECT version();" >/dev/null

  case "$MODE" in
    matrix)
      run_scenario fresh
      run_scenario old_only
      run_scenario collision
      ;;
    fly-replay)
      run_fly_replay
      ;;
    *)
      die "unknown mode: $MODE"
      ;;
  esac

  log "All checks passed"
}

main "$@"

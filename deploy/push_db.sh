#!/usr/bin/env bash
# Copy the fully loaded LOCAL database to Cloud SQL:
#   pg_dump (local) -> Cloud Storage -> gcloud sql import -> grants for the app user.
# Requires: a loaded local DB (make load) and deploy/gcp_setup.sh already run.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/gcp.env
BUCKET="${PROJECT_ID}-db-import"
LOCAL_DB="${DATABASE_URL:-postgresql://localhost/ipl}"
DUMP="data/raw/ipl_dump.sql"

echo "== Dumping local database"
# --no-owner/--no-acl: Cloud SQL import runs as the 'postgres' user; ownership from the
# laptop would not exist there. Grants are applied separately below.
pg_dump "$LOCAL_DB" --format=plain --no-owner --no-acl --clean --if-exists --file="$DUMP"
# Remove the two statement types Cloud SQL's importer rejects:
#  * COMMENT ON EXTENSION (needs true superuser)
#  * SET transaction_timeout (written by pg_dump 17+, unknown to PostgreSQL 16)
sed -i.bak -e '/^COMMENT ON EXTENSION/d' -e '/^SET transaction_timeout/d' "$DUMP" && rm -f "$DUMP.bak"

echo "== Uploading to gs://${BUCKET}"
gcloud storage cp "$DUMP" "gs://${BUCKET}/ipl_dump.sql"
gcloud storage cp db/grants.sql "gs://${BUCKET}/grants.sql"

echo "== Importing into Cloud SQL (a few minutes)"
gcloud sql import sql "$INSTANCE" "gs://${BUCKET}/ipl_dump.sql" --database="$DB_NAME" --user=postgres --quiet
gcloud sql import sql "$INSTANCE" "gs://${BUCKET}/grants.sql"   --database="$DB_NAME" --user=postgres --quiet

echo "== Cleaning up the dump (it is the whole database)"
gcloud storage rm "gs://${BUCKET}/ipl_dump.sql" "gs://${BUCKET}/grants.sql"
echo "Done."

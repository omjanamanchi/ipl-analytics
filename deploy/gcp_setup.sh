#!/usr/bin/env bash
# One-time Google Cloud setup: project APIs, Cloud SQL (PostgreSQL 16), users,
# secrets, IAM, App Engine, optional budget alert. Safe to re-run: steps that
# already exist are skipped.
#   cp deploy/gcp.env.example deploy/gcp.env   # edit PROJECT_ID
#   gcloud auth login && bash deploy/gcp_setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/gcp.env
BUCKET="${PROJECT_ID}-db-import"

gcloud config set project "$PROJECT_ID"

echo "== Enabling APIs"
gcloud services enable sqladmin.googleapis.com appengine.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com storage.googleapis.com \
  billingbudgets.googleapis.com

echo "== Creating Cloud SQL instance (takes ~10 min)"
if ! gcloud sql instances describe "$INSTANCE" >/dev/null 2>&1; then
  ADMIN_PASS="$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-28)"
  # Security choices:
  #  * no --authorized-networks: nothing on the internet can reach Postgres directly;
  #    only IAM-authorised Cloud SQL connections (App Engine, gcloud) get in.
  #  * --ssl-mode=ENCRYPTED_ONLY: refuse unencrypted connections.
  #  * strong random admin password, kept only in Secret Manager.
  gcloud sql instances create "$INSTANCE" \
    --database-version=POSTGRES_16 --edition=enterprise --tier=db-f1-micro \
    --region="$REGION" --storage-type=SSD --storage-size=10 \
    --availability-type=zonal --ssl-mode=ENCRYPTED_ONLY \
    --insights-config-query-insights-enabled \
    --root-password="$ADMIN_PASS"
  printf '%s' "$ADMIN_PASS" | gcloud secrets create ipl-db-admin-password --replication-policy=automatic --data-file=-
fi

echo "== Database and application user"
gcloud sql databases describe "$DB_NAME" --instance="$INSTANCE" >/dev/null 2>&1 \
  || gcloud sql databases create "$DB_NAME" --instance="$INSTANCE"
if ! gcloud secrets describe ipl-db-app-password >/dev/null 2>&1; then
  APP_PASS="$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-28)"
  gcloud sql users create "$APP_DB_USER" --instance="$INSTANCE" --password="$APP_PASS"
  printf '%s' "$APP_PASS" | gcloud secrets create ipl-db-app-password --replication-policy=automatic --data-file=-
fi
gcloud secrets describe ipl-flask-secret-key >/dev/null 2>&1 \
  || openssl rand -hex 32 | tr -d '\n' | gcloud secrets create ipl-flask-secret-key --replication-policy=automatic --data-file=-

echo "== App Engine"
gcloud app describe >/dev/null 2>&1 || gcloud app create --region="$APP_ENGINE_REGION"
APP_SA="${PROJECT_ID}@appspot.gserviceaccount.com"
# Least privilege for the app: connect to Cloud SQL, read its two secrets. Nothing else.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${APP_SA}" --role="roles/cloudsql.client" --condition=None >/dev/null
for s in ipl-db-app-password ipl-flask-secret-key; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${APP_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null
done

echo "== Import bucket (used by deploy/push_db.sh)"
gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1 \
  || gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" --uniform-bucket-level-access
SQL_SA="$(gcloud sql instances describe "$INSTANCE" --format='value(serviceAccountEmailAddress)')"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SQL_SA}" --role="roles/storage.objectViewer" >/dev/null

if [[ -n "${BILLING_ACCOUNT:-}" ]]; then
  echo "== Budget alert at \$20 (emails billing admins at 50/90/100%)"
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
    --display-name="ipl-analytics budget" --budget-amount=20USD \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 || true
fi

echo
echo "Done. Next: bash deploy/push_db.sh   then   bash deploy/deploy_app.sh"

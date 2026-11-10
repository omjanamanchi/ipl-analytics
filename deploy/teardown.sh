#!/usr/bin/env bash
# Run AFTER grading closes (12/23/2026 11:59 pm). Deletes the whole project so nothing keeps billing.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/gcp.env
echo "This permanently deletes project $PROJECT_ID (Cloud SQL, App Engine, secrets, bucket)."
read -r -p "Type the project id to confirm: " ans
[[ "$ans" == "$PROJECT_ID" ]] || { echo "Aborted."; exit 1; }
gcloud projects delete "$PROJECT_ID"

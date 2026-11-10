#!/usr/bin/env bash
# Render app.yaml from the template and deploy to App Engine.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/gcp.env
export PROJECT_ID REGION INSTANCE DB_NAME APP_DB_USER
# Substitute ${VAR}s from gcp.env; $PORT is left alone for App Engine to fill in.
"$(command -v python3 || command -v python)" -c 'import os,sys; sys.stdout.write(os.path.expandvars(open("deploy/app.yaml.template").read()))' > app.yaml
gcloud app deploy app.yaml --project="$PROJECT_ID" --quiet
echo
echo "Live at: $(gcloud app describe --project="$PROJECT_ID" --format='value(defaultHostname)' | sed 's|^|https://|')"
echo "Health:  curl \$URL/healthz"

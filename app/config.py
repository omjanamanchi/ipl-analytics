"""Configuration: local dev uses DATABASE_URL; App Engine uses Cloud SQL + Secret Manager."""
from __future__ import annotations

import os
import secrets


def _secret(resource: str) -> str:
    """Read a Secret Manager secret, e.g. projects/p/secrets/name/versions/latest."""
    from google.cloud import secretmanager  # imported lazily: not needed locally

    client = secretmanager.SecretManagerServiceClient()
    return client.access_secret_version(name=resource).payload.data.decode().strip()


def database_conninfo() -> str:
    """Return a libpq connection string.

    Local:      DATABASE_URL=postgresql://user:pass@localhost:5432/ipl
    App Engine: INSTANCE_CONNECTION_NAME=project:region:instance, DB_USER, DB_NAME and
                DB_PASS_SECRET (Secret Manager resource) - connects over the built-in
                Unix socket /cloudsql/<connection name>, never over the public internet.
    """
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    instance = os.environ["INSTANCE_CONNECTION_NAME"]
    password = os.environ.get("DB_PASS") or _secret(os.environ["DB_PASS_SECRET"])
    from psycopg.conninfo import make_conninfo

    return make_conninfo(
        host=f"/cloudsql/{instance}",
        dbname=os.environ.get("DB_NAME", "ipl"),
        user=os.environ.get("DB_USER", "ipl_app"),
        password=password,
    )


def flask_secret_key() -> str:
    if os.environ.get("FLASK_SECRET_KEY"):
        return os.environ["FLASK_SECRET_KEY"]
    if os.environ.get("FLASK_SECRET_SECRET"):
        return _secret(os.environ["FLASK_SECRET_SECRET"])
    return secrets.token_hex(32)  # dev only: sessions reset on restart

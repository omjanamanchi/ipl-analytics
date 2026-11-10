import os

import psycopg
import pytest
from psycopg.rows import dict_row

DB_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/ipl")


@pytest.fixture(scope="session")
def conn():
    with psycopg.connect(DB_URL, row_factory=dict_row) as c:
        yield c


@pytest.fixture(scope="session")
def client():
    from app import create_app

    app = create_app(DB_URL)
    app.config["TESTING"] = True
    return app.test_client()

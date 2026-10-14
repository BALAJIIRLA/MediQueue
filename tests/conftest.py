import os
import sqlite3

import pytest

os.environ.setdefault(
    "MEDIQUEUE_SECRET_KEY",
    "local-test-only-key-change-before-deployment",
)

import app as mediqueue


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test_mediqueue.db"

    monkeypatch.setattr(mediqueue, "DATABASE", str(test_db))
    mediqueue.app.config.update(
        TESTING=True,
        SECRET_KEY="pytest-only-secret",
    )

    mediqueue.init_database()

    with mediqueue.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def test_db(client):
    import app as mediqueue
    return mediqueue.DATABASE

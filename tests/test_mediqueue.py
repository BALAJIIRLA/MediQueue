import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault(
    "MEDIQUEUE_SECRET_KEY",
    "local-test-only-key-change-before-deployment"
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


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/register",
        "/doctor/register",
        "/login",
        "/doctor/login",
    ],
)
def test_public_pages(client, path):
    response = client.get(path)
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/patient/dashboard",
        "/patient/doctors",
        "/patient/appointments",
        "/patient/notifications",
        "/patient/profile",
        "/patient/my-queue",
        "/doctor/dashboard",
        "/doctor/availability",
        "/admin/dashboard",
        "/admin/patients",
        "/admin/doctors",
        "/admin/appointments",
        "/admin/analytics",
        "/admin/reports",
    ],
)
def test_private_pages_redirect_when_logged_out(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code in (302, 303)


def test_test_database_has_required_tables(client):
    db_path = Path(mediqueue.DATABASE)
    conn = sqlite3.connect(db_path)

    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()

    expected = {
        "users",
        "patients",
        "doctors",
        "appointments",
        "doctor_availability",
        "doctor_unavailable_dates",
        "notifications",
    }

    assert expected.issubset(tables)


def test_original_database_still_exists():
    assert Path("hospital.db").exists()

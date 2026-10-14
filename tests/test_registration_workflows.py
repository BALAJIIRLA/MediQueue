import sqlite3

import pytest
from werkzeug.security import check_password_hash


def user_count(db, email):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            (email.lower(),),
        ).fetchone()[0]
    finally:
        conn.close()


def test_patient_registration_success(client, test_db):
    response = client.post(
        "/register",
        data={
            "name": "Test Patient",
            "email": "test.patient@example.com",
            "phone": "9000000001",
            "age": "25",
            "gender": "Female",
            "password": "patient123",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert user_count(test_db, "test.patient@example.com") == 1


def test_patient_registration_rejects_invalid_age(client, test_db):
    response = client.post(
        "/register",
        data={
            "name": "Invalid Age",
            "email": "invalid.age@example.com",
            "phone": "9000000002",
            "age": "0",
            "gender": "Female",
            "password": "patient123",
        },
    )

    assert response.status_code in (200, 302)
    assert user_count(test_db, "invalid.age@example.com") == 0


def test_patient_registration_rejects_short_password(client, test_db):
    client.post(
        "/register",
        data={
            "name": "Short Password",
            "email": "short.pass@example.com",
            "phone": "9000000003",
            "age": "25",
            "gender": "Female",
            "password": "123",
        },
    )

    assert user_count(test_db, "short.pass@example.com") == 0


def test_duplicate_patient_registration_is_rejected(client, test_db):
    data = {
        "name": "Duplicate Patient",
        "email": "duplicate@example.com",
        "phone": "9000000004",
        "age": "25",
        "gender": "Female",
        "password": "patient123",
    }

    client.post("/register", data=data)
    client.post(
        "/register",
        data={**data, "name": "Duplicate Again"},
    )

    assert user_count(test_db, "duplicate@example.com") == 1


def test_doctor_registration_starts_pending(client, test_db):
    client.post(
        "/doctor/register",
        data={
            "name": "Test Doctor",
            "email": "test.doctor@example.com",
            "phone": "9000000005",
            "department": "General Medicine",
            "specialization": "General Physician",
            "qualification": "MBBS",
            "experience": "5",
            "password": "doctor123",
        },
    )

    conn = sqlite3.connect(test_db)
    try:
        result = conn.execute(
            """
            SELECT users.role, doctors.status
            FROM users
            JOIN doctors ON doctors.user_id = users.id
            WHERE users.email = ?
            """,
            ("test.doctor@example.com",),
        ).fetchone()
    finally:
        conn.close()

    assert result == ("doctor", "pending")


def test_doctor_registration_rejects_invalid_experience(client, test_db):
    client.post(
        "/doctor/register",
        data={
            "name": "Invalid Doctor",
            "email": "invalid.doctor@example.com",
            "phone": "9000000006",
            "department": "General Medicine",
            "specialization": "General Physician",
            "qualification": "MBBS",
            "experience": "100",
            "password": "doctor123",
        },
    )

    assert user_count(
        test_db,
        "invalid.doctor@example.com",
    ) == 0

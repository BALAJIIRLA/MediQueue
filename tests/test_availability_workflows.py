import sqlite3
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash


def create_doctor(test_db, status="approved"):
    conn = sqlite3.connect(test_db)
    try:
        cur = conn.execute(
            """
            INSERT INTO users (name, email, phone, password, role)
            VALUES (?, ?, ?, ?, 'doctor')
            """,
            (
                "Workflow Doctor",
                "workflow.doctor@example.com",
                "9000000101",
                generate_password_hash("doctor123"),
            ),
        )
        user_id = cur.lastrowid

        cur = conn.execute(
            """
            INSERT INTO doctors
            (user_id, department, specialization, qualification,
             experience, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "General Medicine",
                "General Physician",
                "MBBS",
                5,
                status,
            ),
        )
        doctor_id = cur.lastrowid
        conn.commit()
        return user_id, doctor_id
    finally:
        conn.close()


def create_patient(test_db):
    conn = sqlite3.connect(test_db)
    try:
        cur = conn.execute(
            """
            INSERT INTO users (name, email, phone, password, role)
            VALUES (?, ?, ?, ?, 'patient')
            """,
            (
                "Workflow Patient",
                "workflow.patient@example.com",
                "9000000102",
                generate_password_hash("patient123"),
            ),
        )
        user_id = cur.lastrowid

        cur = conn.execute(
            """
            INSERT INTO patients (user_id, age, gender)
            VALUES (?, ?, ?)
            """,
            (user_id, 24, "Female"),
        )
        patient_id = cur.lastrowid
        conn.commit()
        return user_id, patient_id
    finally:
        conn.close()


def set_schedule(test_db, doctor_id, selected_date):
    conn = sqlite3.connect(test_db)
    try:
        conn.execute(
            """
            INSERT INTO doctor_availability
            (doctor_id, day_of_week, start_time, end_time, is_available)
            VALUES (?, ?, ?, ?, 1)
            """,
            (doctor_id, selected_date.weekday(), "09:00", "17:00"),
        )
        conn.commit()
    finally:
        conn.close()


def future_date_with_weekday(weekday):
    selected = date.today() + timedelta(days=1)
    while selected.weekday() != weekday:
        selected += timedelta(days=1)
    return selected


def test_approved_doctor_can_save_weekly_availability(client, test_db):
    user_id, doctor_id = create_doctor(test_db)

    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = "doctor"

    response = client.post(
        "/doctor/availability",
        data={
            "available_0": "on",
            "start_0": "09:00",
            "end_0": "17:00",
        },
    )

    assert response.status_code in (302, 303)

    conn = sqlite3.connect(test_db)
    try:
        row = conn.execute(
            """
            SELECT start_time, end_time, is_available
            FROM doctor_availability
            WHERE doctor_id = ? AND day_of_week = 0
            """,
            (doctor_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("09:00", "17:00", 1)


def test_unapproved_doctor_cannot_manage_availability(client, test_db):
    user_id, _ = create_doctor(test_db, status="pending")

    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = "doctor"

    response = client.post(
        "/doctor/availability",
        data={"available_0": "on", "start_0": "09:00", "end_0": "17:00"},
    )

    assert response.status_code in (302, 303)


def test_availability_rejects_end_time_before_start_time(client, test_db):
    user_id, doctor_id = create_doctor(test_db)

    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = "doctor"

    client.post(
        "/doctor/availability",
        data={
            "available_0": "on",
            "start_0": "17:00",
            "end_0": "09:00",
        },
    )

    conn = sqlite3.connect(test_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM doctor_availability WHERE doctor_id = ?",
            (doctor_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 0


def test_booking_rejects_doctor_without_availability(client, test_db):
    patient_user_id, _ = create_patient(test_db)
    _, doctor_id = create_doctor(test_db)

    with client.session_transaction() as session:
        session["user_id"] = patient_user_id
        session["role"] = "patient"

    selected = future_date_with_weekday(0)

    response = client.post(
        f"/patient/book/{doctor_id}",
        data={"appointment_date": selected.isoformat()},
        follow_redirects=False,
    )

    assert response.status_code in (302, 303)

    conn = sqlite3.connect(test_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM appointments"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 0


def test_booking_rejects_unapproved_doctor(client, test_db):
    patient_user_id, _ = create_patient(test_db)
    _, doctor_id = create_doctor(test_db, status="pending")

    with client.session_transaction() as session:
        session["user_id"] = patient_user_id
        session["role"] = "patient"

    response = client.get(f"/patient/book/{doctor_id}")

    assert response.status_code == 404


def test_past_appointment_date_is_rejected(client, test_db):
    import app as mediqueue

    _, doctor_id = create_doctor(test_db)

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    try:
        valid, message = mediqueue.validate_appointment_date(
            conn,
            doctor_id,
            (date.today() - timedelta(days=1)).isoformat(),
        )
    finally:
        conn.close()

    assert valid is False
    assert "past" in message.lower()


def test_invalid_appointment_date_is_rejected(client, test_db):
    import app as mediqueue

    _, doctor_id = create_doctor(test_db)

    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    try:
        valid, message = mediqueue.validate_appointment_date(
            conn,
            doctor_id,
            "not-a-date",
        )
    finally:
        conn.close()

    assert valid is False
    assert "invalid" in message.lower()

import sqlite3
from datetime import date, timedelta

from werkzeug.security import generate_password_hash, check_password_hash

from test_booking_queue_workflows import (
    setup_patient_and_doctor,
    enable_availability,
    create_appointment,
    login_as,
    get_appointment_status,
)


def get_user(test_db, user_id):
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def test_patient_can_reschedule_waiting_appointment(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(test_db, patient_id, doctor_id)
    new_date = date.today() + timedelta(days=1)
    enable_availability(test_db, doctor_id, new_date)
    login_as(client, patient_user, "patient")

    response = client.post(
        f"/patient/appointment/{appointment_id}/reschedule",
        data={"appointment_date": new_date.isoformat()},
        follow_redirects=True,
    )

    assert response.status_code == 200
    conn = sqlite3.connect(test_db)
    row = conn.execute(
        "SELECT appointment_date, status, token_number FROM appointments WHERE id = ?",
        (appointment_id,),
    ).fetchone()
    conn.close()

    assert row[0] == new_date.isoformat()
    assert row[1] == "WAITING"
    assert row[2] == 1


def test_patient_cannot_reschedule_another_patients_appointment(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(test_db, patient_id, doctor_id)

    conn = sqlite3.connect(test_db)
    conn.execute("""
        INSERT INTO users (name, email, phone, password, role)
        VALUES ('Other Patient', 'other2@test.com', '9000000005', 'test-hash', 'patient')
    """)
    other_user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'other2@test.com'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO patients (user_id, age, gender) VALUES (?, 30, 'Male')",
        (other_user_id,),
    )
    conn.commit()
    conn.close()

    login_as(client, other_user_id, "patient")
    response = client.post(
        f"/patient/appointment/{appointment_id}/reschedule",
        data={"appointment_date": (date.today() + timedelta(days=2)).isoformat()},
        follow_redirects=True,
    )

    assert response.status_code == 404
    assert get_appointment_status(test_db, appointment_id) == "WAITING"


def test_patient_cannot_reschedule_completed_appointment(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(
        test_db, patient_id, doctor_id, "COMPLETED"
    )
    login_as(client, patient_user, "patient")

    response = client.post(
        f"/patient/appointment/{appointment_id}/reschedule",
        data={"appointment_date": (date.today() + timedelta(days=1)).isoformat()},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "COMPLETED"


def test_patient_can_update_profile(client, test_db):
    patient_user, _, _, _ = setup_patient_and_doctor(test_db)
    login_as(client, patient_user, "patient")

    response = client.post(
        "/patient/profile",
        data={
            "name": "Updated Patient",
            "phone": "9000000011",
            "age": "26",
            "gender": "Female",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    user = get_user(test_db, patient_user)
    assert user["name"] == "Updated Patient"
    assert user["phone"] == "9000000011"

    conn = sqlite3.connect(test_db)
    age = conn.execute(
        "SELECT age FROM patients WHERE user_id = ?", (patient_user,)
    ).fetchone()[0]
    conn.close()
    assert age == 26


def test_patient_profile_rejects_invalid_age(client, test_db):
    patient_user, _, _, _ = setup_patient_and_doctor(test_db)
    login_as(client, patient_user, "patient")

    client.post(
        "/patient/profile",
        data={
            "name": "Updated Patient",
            "phone": "9000000011",
            "age": "0",
            "gender": "Female",
        },
        follow_redirects=True,
    )

    conn = sqlite3.connect(test_db)
    age = conn.execute(
        "SELECT age FROM patients WHERE user_id = ?", (patient_user,)
    ).fetchone()[0]
    conn.close()
    assert age == 25


def test_patient_can_change_password(client, test_db):
    patient_user, _, _, _ = setup_patient_and_doctor(test_db)
    conn = sqlite3.connect(test_db)
    conn.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (generate_password_hash("oldpass123"), patient_user),
    )
    conn.commit()
    conn.close()
    login_as(client, patient_user, "patient")

    response = client.post(
        "/patient/profile/change-password",
        data={
            "current_password": "oldpass123",
            "new_password": "newpass123",
            "confirm_password": "newpass123",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    user = get_user(test_db, patient_user)
    assert check_password_hash(user["password"], "newpass123")


def test_patient_cannot_change_password_with_wrong_current_password(client, test_db):
    patient_user, _, _, _ = setup_patient_and_doctor(test_db)
    conn = sqlite3.connect(test_db)
    conn.execute(
        "UPDATE users SET password = ? WHERE id = ?",
        (generate_password_hash("oldpass123"), patient_user),
    )
    conn.commit()
    conn.close()
    login_as(client, patient_user, "patient")

    client.post(
        "/patient/profile/change-password",
        data={
            "current_password": "wrongpass",
            "new_password": "newpass123",
            "confirm_password": "newpass123",
        },
        follow_redirects=True,
    )

    user = get_user(test_db, patient_user)
    assert check_password_hash(user["password"], "oldpass123")


def test_patient_can_mark_notification_read(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(test_db, patient_id, doctor_id)

    conn = sqlite3.connect(test_db)
    cursor = conn.execute("""
        INSERT INTO notifications
        (patient_id, title, message, notification_type, appointment_id, is_read)
        VALUES (?, 'Test notice', 'Test message', 'TEST', ?, 0)
    """, (patient_id, appointment_id))
    notification_id = cursor.lastrowid
    conn.commit()
    conn.close()

    login_as(client, patient_user, "patient")
    response = client.post(
        f"/patient/notifications/read/{notification_id}",
        follow_redirects=True,
    )

    assert response.status_code == 200
    conn = sqlite3.connect(test_db)
    is_read = conn.execute(
        "SELECT is_read FROM notifications WHERE id = ?", (notification_id,)
    ).fetchone()[0]
    conn.close()
    assert is_read == 1


def test_patient_cannot_mark_another_patients_notification_read(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(test_db, patient_id, doctor_id)

    conn = sqlite3.connect(test_db)
    conn.execute("""
        INSERT INTO users (name, email, phone, password, role)
        VALUES ('Other Patient', 'other3@test.com', '9000000006', 'test-hash', 'patient')
    """)
    other_user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'other3@test.com'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO patients (user_id, age, gender) VALUES (?, 30, 'Male')",
        (other_user_id,),
    )
    other_patient_id = conn.execute(
        "SELECT id FROM patients WHERE user_id = ?", (other_user_id,)
    ).fetchone()[0]
    cursor = conn.execute("""
        INSERT INTO notifications
        (patient_id, title, message, notification_type, appointment_id, is_read)
        VALUES (?, 'Private notice', 'Private message', 'TEST', ?, 0)
    """, (other_patient_id, appointment_id))
    notification_id = cursor.lastrowid
    conn.commit()
    conn.close()

    login_as(client, patient_user, "patient")
    response = client.post(
        f"/patient/notifications/read/{notification_id}",
        follow_redirects=True,
    )

    assert response.status_code == 200
    conn = sqlite3.connect(test_db)
    is_read = conn.execute(
        "SELECT is_read FROM notifications WHERE id = ?", (notification_id,)
    ).fetchone()[0]
    conn.close()
    assert is_read == 0


def test_admin_can_approve_doctor(client, test_db):
    _, _, doctor_user, doctor_id = setup_patient_and_doctor(
        test_db, doctor_status="pending"
    )
    admin_user = 999
    login_as(client, admin_user, "admin")

    response = client.post(
        f"/admin/doctor/{doctor_id}/approve",
        follow_redirects=True,
    )

    assert response.status_code == 200
    conn = sqlite3.connect(test_db)
    status = conn.execute(
        "SELECT status FROM doctors WHERE id = ?", (doctor_id,)
    ).fetchone()[0]
    conn.close()
    assert status == "approved"

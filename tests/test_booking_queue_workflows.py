import sqlite3
from datetime import date, timedelta


def setup_patient_and_doctor(test_db, doctor_status="approved"):
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        INSERT INTO users (name, email, phone, password, role)
        VALUES ('Test Patient', 'patient@test.com', '9000000001', 'test-hash', 'patient')
    """)
    patient_user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'patient@test.com'"
    ).fetchone()["id"]

    conn.execute("""
        INSERT INTO patients (user_id, age, gender)
        VALUES (?, 25, 'Female')
    """, (patient_user_id,))
    patient_id = conn.execute(
        "SELECT id FROM patients WHERE user_id = ?", (patient_user_id,)
    ).fetchone()["id"]

    conn.execute("""
        INSERT INTO users (name, email, phone, password, role)
        VALUES ('Test Doctor', 'doctor@test.com', '9000000002', 'test-hash', 'doctor')
    """)
    doctor_user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'doctor@test.com'"
    ).fetchone()["id"]

    conn.execute("""
        INSERT INTO doctors
        (user_id, department, specialization, qualification, experience, status)
        VALUES (?, 'General', 'General Physician', 'MBBS', 5, ?)
    """, (doctor_user_id, doctor_status))
    doctor_id = conn.execute(
        "SELECT id FROM doctors WHERE user_id = ?", (doctor_user_id,)
    ).fetchone()["id"]

    conn.commit()
    conn.close()
    return patient_user_id, patient_id, doctor_user_id, doctor_id


def enable_availability(test_db, doctor_id, selected_date):
    conn = sqlite3.connect(test_db)
    conn.execute("""
        INSERT INTO doctor_availability
        (doctor_id, day_of_week, start_time, end_time, is_available)
        VALUES (?, ?, '09:00', '17:00', 1)
    """, (doctor_id, selected_date.weekday()))
    conn.commit()
    conn.close()


def create_appointment(test_db, patient_id, doctor_id, status="WAITING"):
    conn = sqlite3.connect(test_db)
    selected_date = date.today().isoformat()
    cursor = conn.execute("""
        INSERT INTO appointments
        (patient_id, doctor_id, appointment_date, token_number, status)
        VALUES (?, ?, ?, 1, ?)
    """, (patient_id, doctor_id, selected_date, status))
    appointment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return appointment_id


def login_as(client, user_id, role):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = role


def get_appointment_status(test_db, appointment_id):
    conn = sqlite3.connect(test_db)
    row = conn.execute(
        "SELECT status FROM appointments WHERE id = ?", (appointment_id,)
    ).fetchone()
    conn.close()
    return row[0]


def test_patient_can_book_available_doctor(client, test_db):
    patient_user, patient_id, doctor_user, doctor_id = (
        setup_patient_and_doctor(test_db)
    )
    selected_date = date.today() + timedelta(days=1)
    enable_availability(test_db, doctor_id, selected_date)
    login_as(client, patient_user, "patient")

    response = client.post(
        f"/patient/book/{doctor_id}",
        data={"appointment_date": selected_date.isoformat()},
        follow_redirects=True,
    )

    assert response.status_code == 200
    conn = sqlite3.connect(test_db)
    appointment = conn.execute("""
        SELECT patient_id, doctor_id, appointment_date, token_number, status
        FROM appointments
    """).fetchone()
    conn.close()

    assert appointment is not None
    assert appointment[0] == patient_id
    assert appointment[1] == doctor_id
    assert appointment[2] == selected_date.isoformat()
    assert appointment[3] == 1
    assert appointment[4] == "WAITING"


def test_patient_cannot_book_same_doctor_twice_on_same_date(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    selected_date = date.today() + timedelta(days=1)
    enable_availability(test_db, doctor_id, selected_date)
    conn = sqlite3.connect(test_db)
    conn.execute("""
        INSERT INTO appointments
        (patient_id, doctor_id, appointment_date, token_number, status)
        VALUES (?, ?, ?, 1, 'WAITING')
    """, (patient_id, doctor_id, selected_date.isoformat()))
    conn.commit()
    conn.close()

    login_as(client, patient_user, "patient")

    response = client.post(
        f"/patient/book/{doctor_id}",
        data={"appointment_date": selected_date.isoformat()},
        follow_redirects=True,
    )

    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    conn.close()

    assert response.status_code == 200
    assert count == 1


def test_patient_can_cancel_waiting_appointment(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(test_db, patient_id, doctor_id)
    login_as(client, patient_user, "patient")

    response = client.post(
        f"/patient/appointment/{appointment_id}/cancel",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "CANCELLED"


def test_patient_cannot_cancel_in_progress_appointment(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(
        test_db, patient_id, doctor_id, "IN_PROGRESS"
    )
    login_as(client, patient_user, "patient")

    response = client.post(
        f"/patient/appointment/{appointment_id}/cancel",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "IN_PROGRESS"


def test_patient_cannot_cancel_another_patients_appointment(client, test_db):
    patient_user, patient_id, _, doctor_id = setup_patient_and_doctor(test_db)
    appointment_id = create_appointment(test_db, patient_id, doctor_id)

    other_user_id = None
    conn = sqlite3.connect(test_db)
    conn.execute("""
        INSERT INTO users (name, email, phone, password, role)
        VALUES ('Other Patient', 'other@test.com', '9000000003', 'test-hash', 'patient')
    """)
    other_user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'other@test.com'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO patients (user_id, age, gender) VALUES (?, 30, 'Male')",
        (other_user_id,),
    )
    conn.commit()
    conn.close()

    login_as(client, other_user_id, "patient")
    response = client.post(
        f"/patient/appointment/{appointment_id}/cancel",
        follow_redirects=True,
    )

    assert response.status_code == 404
    assert get_appointment_status(test_db, appointment_id) == "WAITING"


def test_doctor_can_call_next_waiting_patient(client, test_db):
    patient_user, patient_id, doctor_user, doctor_id = setup_patient_and_doctor(
        test_db
    )
    appointment_id = create_appointment(test_db, patient_id, doctor_id)
    login_as(client, doctor_user, "doctor")

    response = client.post("/doctor/queue/call-next", follow_redirects=True)

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "CALLED"


def test_doctor_can_accept_called_patient(client, test_db):
    patient_user, patient_id, doctor_user, doctor_id = setup_patient_and_doctor(
        test_db
    )
    appointment_id = create_appointment(
        test_db, patient_id, doctor_id, "CALLED"
    )
    login_as(client, doctor_user, "doctor")

    response = client.post(
        f"/doctor/queue/{appointment_id}/accept",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "IN_PROGRESS"


def test_doctor_can_complete_in_progress_patient(client, test_db):
    patient_user, patient_id, doctor_user, doctor_id = setup_patient_and_doctor(
        test_db
    )
    appointment_id = create_appointment(
        test_db, patient_id, doctor_id, "IN_PROGRESS"
    )
    login_as(client, doctor_user, "doctor")

    response = client.post(
        f"/doctor/queue/{appointment_id}/complete",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "COMPLETED"


def test_doctor_can_skip_waiting_patient(client, test_db):
    patient_user, patient_id, doctor_user, doctor_id = setup_patient_and_doctor(
        test_db
    )
    appointment_id = create_appointment(test_db, patient_id, doctor_id)
    login_as(client, doctor_user, "doctor")

    response = client.post(
        f"/doctor/queue/{appointment_id}/skip",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "SKIPPED"


def test_doctor_cannot_accept_another_doctors_patient(client, test_db):
    patient_user, patient_id, doctor_user, doctor_id = setup_patient_and_doctor(
        test_db
    )
    appointment_id = create_appointment(
        test_db, patient_id, doctor_id, "CALLED"
    )

    conn = sqlite3.connect(test_db)
    conn.execute("""
        INSERT INTO users (name, email, phone, password, role)
        VALUES ('Second Doctor', 'doctor2@test.com', '9000000004', 'test-hash', 'doctor')
    """)
    second_user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'doctor2@test.com'"
    ).fetchone()[0]
    conn.execute("""
        INSERT INTO doctors
        (user_id, department, specialization, qualification, experience, status)
        VALUES (?, 'General', 'General Physician', 'MBBS', 4, 'approved')
    """, (second_user_id,))
    conn.commit()
    conn.close()

    login_as(client, second_user_id, "doctor")
    response = client.post(
        f"/doctor/queue/{appointment_id}/accept",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert get_appointment_status(test_db, appointment_id) == "CALLED"

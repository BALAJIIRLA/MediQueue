from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from pathlib import Path
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
import os

app.secret_key = os.environ.get("MEDIQUEUE_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "MEDIQUEUE_SECRET_KEY is missing. Set it before starting MediQueue."
    )

DATABASE = Path("hospital.db")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('patient', 'doctor', 'admin')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            age INTEGER,
            gender TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            department TEXT NOT NULL,
            specialization TEXT,
            qualification TEXT,
            experience INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'approved', 'blocked')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            appointment_date TEXT NOT NULL,
            token_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'WAITING'
                CHECK(status IN (
                    'WAITING',
                    'CALLED',
                    'IN_PROGRESS',
                    'COMPLETED',
                    'SKIPPED',
                    'CANCELLED'
                )),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            called_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_available INTEGER NOT NULL DEFAULT 1,
            UNIQUE(doctor_id, day_of_week),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_unavailable_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            unavailable_date TEXT NOT NULL,
            reason TEXT,
            UNIQUE(doctor_id, unavailable_date),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        )
    """)


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            appointment_id INTEGER,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (appointment_id) REFERENCES appointments(id)
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# NOTIFICATION HELPERS
# =========================================================

def create_notification(
    conn,
    patient_id,
    title,
    message,
    notification_type,
    appointment_id=None
):
    conn.execute("""
        INSERT INTO notifications (
            patient_id,
            title,
            message,
            notification_type,
            appointment_id
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        patient_id,
        title,
        message,
        notification_type,
        appointment_id
    ))


def get_unread_notification_count(conn, patient_id):
    row = conn.execute("""
        SELECT COUNT(*) AS unread_count
        FROM notifications
        WHERE patient_id = ?
          AND is_read = 0
    """, (patient_id,)).fetchone()

    return row["unread_count"] if row else 0


# =========================================================
# DOCTOR AVAILABILITY HELPERS
# =========================================================

DAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday"
}


def is_doctor_available(conn, doctor_id, selected_date):
    """
    Check whether a doctor is available on a specific date.

    Availability rules:
    1. Doctor must have a weekly schedule for that weekday.
    2. That weekday must be enabled.
    3. The date must not be specifically blocked.
    """

    day_of_week = selected_date.weekday()

    unavailable = conn.execute("""
        SELECT id
        FROM doctor_unavailable_dates
        WHERE doctor_id = ?
          AND unavailable_date = ?
    """, (
        doctor_id,
        selected_date.isoformat()
    )).fetchone()

    if unavailable:
        return False, "The doctor is unavailable on the selected date."

    schedule = conn.execute("""
        SELECT
            start_time,
            end_time,
            is_available
        FROM doctor_availability
        WHERE doctor_id = ?
          AND day_of_week = ?
    """, (
        doctor_id,
        day_of_week
    )).fetchone()

    if not schedule:
        return False, (
            f"The doctor has not set availability for "
            f"{DAY_NAMES[day_of_week]}."
        )

    if not schedule["is_available"]:
        return False, (
            f"The doctor is not available on "
            f"{DAY_NAMES[day_of_week]}."
        )

    return True, (
        f"Available from {schedule['start_time']} "
        f"to {schedule['end_time']}."
    )


def validate_appointment_date(conn, doctor_id, appointment_date):
    """
    Validate a booking/rescheduling date.
    """

    try:
        selected_date = date.fromisoformat(appointment_date)

    except ValueError:
        return False, "Invalid appointment date."

    if selected_date < date.today():
        return False, "You cannot select a past date."

    doctor = conn.execute("""
        SELECT id, status
        FROM doctors
        WHERE id = ?
    """, (doctor_id,)).fetchone()

    if not doctor:
        return False, "Doctor not found."

    if doctor["status"] != "approved":
        return False, "This doctor is not currently available for appointments."

    available, message = is_doctor_available(
        conn,
        doctor_id,
        selected_date
    )

    if not available:
        return False, message

    return True, message



# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


# =========================================================
# PATIENT REGISTRATION
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        age = request.form.get("age", "").strip()
        gender = request.form.get("gender", "").strip()
        password = request.form.get("password", "")

        if not all([name, email, phone, age, gender, password]):
            flash("Please fill in all fields.", "error")
            return redirect(url_for("register"))

        try:
            age = int(age)

            if age < 1 or age > 120:
                flash("Please enter a valid age.", "error")
                return redirect(url_for("register"))

        except ValueError:
            flash("Age must be a number.", "error")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return redirect(url_for("register"))

        conn = get_db()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO users
                (name, email, phone, password, role)
                VALUES (?, ?, ?, ?, 'patient')
            """, (
                name,
                email,
                phone,
                generate_password_hash(password)
            ))

            user_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO patients
                (user_id, age, gender)
                VALUES (?, ?, ?)
            """, (user_id, age, gender))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()

            flash(
                "Email or phone number is already registered.",
                "error"
            )

            return redirect(url_for("register"))

        conn.close()

        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# =========================================================
# DOCTOR REGISTRATION
# =========================================================

@app.route("/doctor/register", methods=["GET", "POST"])
def doctor_register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        department = request.form.get("department", "").strip()
        specialization = request.form.get("specialization", "").strip()
        qualification = request.form.get("qualification", "").strip()
        experience = request.form.get("experience", "").strip()
        password = request.form.get("password", "")

        if not all([
            name,
            email,
            phone,
            department,
            specialization,
            qualification,
            experience,
            password
        ]):
            flash("Please fill in all fields.", "error")
            return redirect(url_for("doctor_register"))

        try:
            experience = int(experience)

            if experience < 0 or experience > 70:
                flash("Please enter valid experience.", "error")
                return redirect(url_for("doctor_register"))

        except ValueError:
            flash("Experience must be a number.", "error")
            return redirect(url_for("doctor_register"))

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return redirect(url_for("doctor_register"))

        conn = get_db()

        try:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO users
                (name, email, phone, password, role)
                VALUES (?, ?, ?, ?, 'doctor')
            """, (
                name,
                email,
                phone,
                generate_password_hash(password)
            ))

            user_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO doctors
                (user_id, department, specialization,
                 qualification, experience, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (
                user_id,
                department,
                specialization,
                qualification,
                experience
            ))

            conn.commit()

        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()

            flash(
                "Email or phone number is already registered.",
                "error"
            )

            return redirect(url_for("doctor_register"))

        conn.close()

        flash(
            "Doctor registration submitted. "
            "Please wait for admin approval.",
            "success"
        )

        return redirect(url_for("doctor_login"))

    return render_template("doctor_register.html")


# =========================================================
# PATIENT LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute("""
            SELECT *
            FROM users
            WHERE email = ?
        """, (email,)).fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session.clear()

            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            if user["role"] == "patient":
                return redirect(url_for("patient_dashboard"))

            if user["role"] == "doctor":
                return redirect(url_for("doctor_dashboard"))

            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))

        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


# =========================================================
# DOCTOR LOGIN
# =========================================================

@app.route("/doctor/login", methods=["GET", "POST"])
def doctor_login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute("""
            SELECT
                users.*,
                doctors.status AS doctor_status
            FROM users
            JOIN doctors
                ON users.id = doctors.user_id
            WHERE users.email = ?
              AND users.role = 'doctor'
        """, (email,)).fetchone()

        conn.close()

        if not user:
            flash("Doctor account not found.", "error")
            return redirect(url_for("doctor_login"))

        if not check_password_hash(user["password"], password):
            flash("Invalid password.", "error")
            return redirect(url_for("doctor_login"))

        if user["doctor_status"] == "pending":
            flash(
                "Your doctor account is waiting for admin approval.",
                "error"
            )
            return redirect(url_for("doctor_login"))

        if user["doctor_status"] == "blocked":
            flash(
                "Your doctor account has been blocked.",
                "error"
            )
            return redirect(url_for("doctor_login"))

        session.clear()

        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["role"] = "doctor"

        return redirect(url_for("doctor_dashboard"))

    return render_template("doctor_login.html")


# =========================================================
# PATIENT DASHBOARD
# =========================================================

@app.route("/patient/dashboard")
def patient_dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    unread_notification_count = get_unread_notification_count(
        conn,
        patient["id"]
    )

    conn.close()

    return render_template(
        "patient_dashboard.html",
        name=session.get("name"),
        patient=patient,
        unread_notification_count=unread_notification_count
    )


# =========================================================
# FIND DOCTORS
# =========================================================

@app.route("/patient/doctors")
def patient_doctors():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    doctors = conn.execute("""
        SELECT
            doctors.id,
            doctors.department,
            doctors.specialization,
            doctors.qualification,
            doctors.experience,
            users.name
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.status = 'approved'
        ORDER BY users.name
    """).fetchall()

    conn.close()

    return render_template(
        "patient_doctors.html",
        doctors=doctors
    )


# =========================================================
# BOOK APPOINTMENT
# =========================================================

@app.route("/patient/book/<int:doctor_id>", methods=["GET", "POST"])
def book_appointment(doctor_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    doctor = conn.execute("""
        SELECT
            doctors.*,
            users.name
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.id = ?
          AND doctors.status = 'approved'
    """, (doctor_id,)).fetchone()

    patient = conn.execute("""
        SELECT *
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    conn.close()

    if not doctor or not patient:
        return "Doctor or patient not found.", 404

    if request.method == "POST":

        appointment_date = request.form.get(
            "appointment_date",
            ""
        ).strip()

        if not appointment_date:
            flash("Please select an appointment date.", "error")
            return redirect(
                url_for("book_appointment", doctor_id=doctor_id)
            )

        conn = get_db()

        valid_date, validation_message = validate_appointment_date(
            conn,
            doctor_id,
            appointment_date
        )

        if not valid_date:
            conn.close()

            flash(
                validation_message,
                "error"
            )

            return redirect(
                url_for(
                    "book_appointment",
                    doctor_id=doctor_id
                )
            )

        # Check whether patient already booked this doctor on this date
        existing = conn.execute("""
            SELECT id
            FROM appointments
            WHERE patient_id = ?
              AND doctor_id = ?
              AND appointment_date = ?
              AND status != 'CANCELLED'
        """, (
            patient["id"],
            doctor_id,
            appointment_date
        )).fetchone()

        if existing:
            conn.close()

            flash(
                "You already have an appointment with this doctor "
                "on this date.",
                "error"
            )

            return redirect(url_for("patient_appointments"))

        # Find the highest token for this doctor on this date
        last_token = conn.execute("""
            SELECT MAX(token_number) AS max_token
            FROM appointments
            WHERE doctor_id = ?
              AND appointment_date = ?
        """, (
            doctor_id,
            appointment_date
        )).fetchone()

        if last_token["max_token"] is None:
            token_number = 1
        else:
            token_number = last_token["max_token"] + 1

        conn.execute("""
            INSERT INTO appointments
            (
                patient_id,
                doctor_id,
                appointment_date,
                token_number,
                status
            )
            VALUES (?, ?, ?, ?, 'WAITING')
        """, (
            patient["id"],
            doctor_id,
            appointment_date,
            token_number
        ))

        appointment_id = conn.execute("""
            SELECT id
            FROM appointments
            WHERE patient_id = ?
              AND doctor_id = ?
              AND appointment_date = ?
              AND token_number = ?
            ORDER BY id DESC
            LIMIT 1
        """, (
            patient["id"],
            doctor_id,
            appointment_date,
            token_number
        )).fetchone()["id"]

        create_notification(
            conn,
            patient["id"],
            "Appointment Booked",
            f"Your appointment with Dr. {doctor['name']} "
            f"is booked for {appointment_date}. "
            f"Your token number is {token_number}.",
            "BOOKING",
            appointment_id
        )

        conn.commit()
        conn.close()

        flash(
            f"Appointment booked successfully! "
            f"Your token number is {token_number}.",
            "success"
        )

        return redirect(url_for("patient_appointments"))

    return render_template(
        "book_appointment.html",
        doctor=doctor,
        today=date.today().isoformat()
    )


# =========================================================
# PATIENT APPOINTMENTS
# =========================================================

@app.route("/patient/appointments")
def patient_appointments():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    appointments = conn.execute("""
        SELECT
            appointments.*,
            users.name AS doctor_name,
            doctors.department,
            doctors.specialization
        FROM appointments
        JOIN doctors
            ON appointments.doctor_id = doctors.id
        JOIN users
            ON doctors.user_id = users.id
        WHERE appointments.patient_id = ?
        ORDER BY
            appointments.appointment_date DESC,
            appointments.token_number DESC
    """, (patient["id"],)).fetchall()

    conn.close()

    return render_template(
        "patient_appointments.html",
        appointments=appointments
    )


# =========================================================
# PATIENT RESCHEDULE APPOINTMENT
# =========================================================

@app.route(
    "/patient/appointment/<int:appointment_id>/reschedule",
    methods=["GET", "POST"]
)
def patient_reschedule_appointment(appointment_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    appointment = conn.execute("""
        SELECT
            appointments.*,
            users.name AS doctor_name,
            doctors.department,
            doctors.specialization
        FROM appointments
        JOIN doctors
            ON appointments.doctor_id = doctors.id
        JOIN users
            ON doctors.user_id = users.id
        WHERE appointments.id = ?
          AND appointments.patient_id = ?
    """, (
        appointment_id,
        patient["id"]
    )).fetchone()

    if not appointment:
        conn.close()
        return "Appointment not found.", 404

    if appointment["status"] not in ["WAITING", "CALLED"]:
        conn.close()

        flash(
            "Only waiting or called appointments can be rescheduled.",
            "error"
        )

        return redirect(
            url_for("patient_appointments")
        )

    if request.method == "POST":

        new_date = request.form.get(
            "appointment_date",
            ""
        ).strip()

        if not new_date:
            conn.close()

            flash(
                "Please select a new appointment date.",
                "error"
            )

            return redirect(
                url_for(
                    "patient_reschedule_appointment",
                    appointment_id=appointment_id
                )
            )

        valid_date, validation_message = validate_appointment_date(
            conn,
            appointment["doctor_id"],
            new_date
        )

        if not valid_date:
            conn.close()

            flash(
                validation_message,
                "error"
            )

            return redirect(
                url_for(
                    "patient_reschedule_appointment",
                    appointment_id=appointment_id
                )
            )

        # Prevent duplicate appointment with the same doctor
        # on the same new date.
        existing = conn.execute("""
            SELECT id
            FROM appointments
            WHERE patient_id = ?
              AND doctor_id = ?
              AND appointment_date = ?
              AND id != ?
              AND status != 'CANCELLED'
        """, (
            patient["id"],
            appointment["doctor_id"],
            new_date,
            appointment_id
        )).fetchone()

        if existing:
            conn.close()

            flash(
                "You already have another appointment with this "
                "doctor on the selected date.",
                "error"
            )

            return redirect(
                url_for(
                    "patient_reschedule_appointment",
                    appointment_id=appointment_id
                )
            )

        # Generate the next token for the doctor on the new date.
        last_token = conn.execute("""
            SELECT MAX(token_number) AS max_token
            FROM appointments
            WHERE doctor_id = ?
              AND appointment_date = ?
              AND status != 'CANCELLED'
        """, (
            appointment["doctor_id"],
            new_date
        )).fetchone()

        if last_token["max_token"] is None:
            new_token = 1
        else:
            new_token = last_token["max_token"] + 1

        # Rescheduling resets the queue position.
        conn.execute("""
            UPDATE appointments
            SET
                appointment_date = ?,
                token_number = ?,
                status = 'WAITING',
                called_at = NULL,
                completed_at = NULL
            WHERE id = ?
              AND patient_id = ?
              AND status IN ('WAITING', 'CALLED')
        """, (
            new_date,
            new_token,
            appointment_id,
            patient["id"]
        ))

        create_notification(
            conn,
            patient["id"],
            "Appointment Rescheduled",
            f"Your appointment with Dr. {appointment['doctor_name']} "
            f"has been rescheduled to {new_date}. "
            f"Your new token number is {new_token}.",
            "RESCHEDULED",
            appointment_id
        )

        conn.commit()
        conn.close()

        flash(
            f"Appointment rescheduled successfully! "
            f"New date: {new_date}. "
            f"New token: {new_token}.",
            "success"
        )

        return redirect(
            url_for("patient_appointments")
        )

    return render_template(
        "patient_reschedule.html",
        appointment=appointment,
        today=date.today().isoformat()
    )




# =========================================================
# PATIENT NOTIFICATIONS
# =========================================================

@app.route("/patient/notifications")
def patient_notifications():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT id
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    notifications = conn.execute("""
        SELECT
            notifications.id,
            notifications.title,
            notifications.message,
            notifications.notification_type,
            notifications.appointment_id,
            notifications.is_read,
            notifications.created_at,
            appointments.token_number,
            appointments.appointment_date
        FROM notifications
        LEFT JOIN appointments
            ON notifications.appointment_id = appointments.id
        WHERE notifications.patient_id = ?
        ORDER BY
            notifications.created_at DESC,
            notifications.id DESC
    """, (patient["id"],)).fetchall()

    unread_count = get_unread_notification_count(
        conn,
        patient["id"]
    )

    conn.close()

    return render_template(
        "patient_notifications.html",
        notifications=notifications,
        unread_count=unread_count
    )


@app.route(
    "/patient/notifications/read/<int:notification_id>",
    methods=["POST"]
)
def patient_mark_notification_read(notification_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT id
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    result = conn.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE id = ?
          AND patient_id = ?
    """, (
        notification_id,
        patient["id"]
    ))

    conn.commit()
    conn.close()

    if result.rowcount == 0:
        flash(
            "Notification not found.",
            "error"
        )

    return redirect(
        url_for("patient_notifications")
    )


@app.route(
    "/patient/notifications/read-all",
    methods=["POST"]
)
def patient_mark_all_notifications_read():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT id
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    conn.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE patient_id = ?
          AND is_read = 0
    """, (patient["id"],))

    conn.commit()
    conn.close()

    flash(
        "All notifications marked as read.",
        "success"
    )

    return redirect(
        url_for("patient_notifications")
    )



# =========================================================
# PATIENT PROFILE
# =========================================================

@app.route("/patient/profile", methods=["GET", "POST"])
def patient_profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT
            patients.id AS patient_id,
            patients.age,
            patients.gender,
            users.id AS user_id,
            users.name,
            users.email,
            users.phone
        FROM patients
        JOIN users
            ON patients.user_id = users.id
        WHERE patients.user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        age_text = request.form.get("age", "").strip()
        gender = request.form.get("gender", "").strip()

        if not all([name, phone, age_text, gender]):
            conn.close()

            flash(
                "Please fill in all profile fields.",
                "error"
            )

            return redirect(
                url_for("patient_profile")
            )

        try:
            age = int(age_text)

            if age < 1 or age > 120:
                raise ValueError

        except ValueError:
            conn.close()

            flash(
                "Please enter a valid age between 1 and 120.",
                "error"
            )

            return redirect(
                url_for("patient_profile")
            )

        existing_phone = conn.execute("""
            SELECT id
            FROM users
            WHERE phone = ?
              AND id != ?
        """, (
            phone,
            patient["user_id"]
        )).fetchone()

        if existing_phone:
            conn.close()

            flash(
                "That phone number is already registered.",
                "error"
            )

            return redirect(
                url_for("patient_profile")
            )

        conn.execute("""
            UPDATE users
            SET name = ?,
                phone = ?
            WHERE id = ?
        """, (
            name,
            phone,
            patient["user_id"]
        ))

        conn.execute("""
            UPDATE patients
            SET age = ?,
                gender = ?
            WHERE user_id = ?
        """, (
            age,
            gender,
            patient["user_id"]
        ))

        conn.commit()
        conn.close()

        flash(
            "Profile updated successfully.",
            "success"
        )

        return redirect(
            url_for("patient_profile")
        )

    conn.close()

    return render_template(
        "patient_profile.html",
        patient=patient
    )


@app.route(
    "/patient/profile/change-password",
    methods=["POST"]
)
def patient_change_password():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    current_password = request.form.get(
        "current_password",
        ""
    )

    new_password = request.form.get(
        "new_password",
        ""
    )

    confirm_password = request.form.get(
        "confirm_password",
        ""
    )

    if not all([
        current_password,
        new_password,
        confirm_password
    ]):

        flash(
            "Please fill in all password fields.",
            "error"
        )

        return redirect(
            url_for("patient_profile")
        )

    if len(new_password) < 6:

        flash(
            "New password must contain at least 6 characters.",
            "error"
        )

        return redirect(
            url_for("patient_profile")
        )

    if new_password != confirm_password:

        flash(
            "New password and confirmation do not match.",
            "error"
        )

        return redirect(
            url_for("patient_profile")
        )

    conn = get_db()

    user = conn.execute("""
        SELECT password
        FROM users
        WHERE id = ?
          AND role = 'patient'
    """, (session["user_id"],)).fetchone()

    if not user:
        conn.close()
        return "Patient account not found.", 404

    if not check_password_hash(
        user["password"],
        current_password
    ):

        conn.close()

        flash(
            "Current password is incorrect.",
            "error"
        )

        return redirect(
            url_for("patient_profile")
        )

    conn.execute("""
        UPDATE users
        SET password = ?
        WHERE id = ?
          AND role = 'patient'
    """, (
        generate_password_hash(new_password),
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    flash(
        "Password changed successfully.",
        "success"
    )

    return redirect(
        url_for("patient_profile")
    )



# =========================================================
# PATIENT MY QUEUE
# =========================================================

@app.route("/patient/my-queue")
def patient_my_queue():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    # Find the patient's currently active appointment.
    appointment = conn.execute("""
        SELECT id
        FROM appointments
        WHERE patient_id = ?
          AND status IN ('WAITING', 'CALLED', 'IN_PROGRESS')
        ORDER BY appointment_date DESC, token_number DESC
        LIMIT 1
    """, (patient["id"],)).fetchone()

    conn.close()

    if not appointment:
        return """
        <div style="
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 60px 20px;
        ">
            <h2>No Active Queue</h2>
            <p>You don't currently have an active appointment.</p>
            <br>
            <a href="/patient/appointments">
                View My Appointments
            </a>
        </div>
        """

    return redirect(
        url_for(
            "patient_live_queue",
            appointment_id=appointment["id"]
        )
    )



# =========================================================
# PATIENT LIVE QUEUE
# =========================================================

@app.route("/patient/appointment/<int:appointment_id>/cancel", methods=["POST"])
def patient_cancel_appointment(appointment_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    # -----------------------------------------------------
    # Find the logged-in patient's database ID
    # -----------------------------------------------------

    patient = conn.execute("""
        SELECT id
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    # -----------------------------------------------------
    # Find ONLY this patient's appointment
    # -----------------------------------------------------

    appointment = conn.execute("""
        SELECT
            appointments.id,
            appointments.status,
            appointments.appointment_date,
            appointments.token_number,
            users.name AS doctor_name
        FROM appointments
        JOIN doctors
            ON appointments.doctor_id = doctors.id
        JOIN users
            ON doctors.user_id = users.id
        WHERE appointments.id = ?
          AND appointments.patient_id = ?
    """, (appointment_id, patient["id"])).fetchone()

    if not appointment:
        conn.close()
        return "Appointment not found.", 404

    # -----------------------------------------------------
    # Cancellation is allowed only before treatment starts
    # -----------------------------------------------------

    if appointment["status"] not in ["WAITING", "CALLED"]:
        conn.close()

        flash(
            "This appointment cannot be cancelled because it is already being processed or finished.",
            "error"
        )

        return redirect(
            url_for("patient_appointments")
        )

    # -----------------------------------------------------
    # Cancel appointment
    # -----------------------------------------------------

    conn.execute("""
        UPDATE appointments
        SET status = 'CANCELLED'
        WHERE id = ?
          AND patient_id = ?
          AND status IN ('WAITING', 'CALLED')
    """, (
        appointment_id,
        patient["id"]
    ))

    create_notification(
        conn,
        patient["id"],
        "Appointment Cancelled",
        f"Your appointment with Dr. {appointment['doctor_name']} "
        f"on {appointment['appointment_date']} "
        f"(Token {appointment['token_number']}) has been cancelled.",
        "CANCELLED",
        appointment_id
    )

    conn.commit()
    conn.close()

    flash(
        f"Appointment Token {appointment['token_number']} cancelled successfully.",
        "success"
    )

    return redirect(
        url_for("patient_appointments")
    )


@app.route("/patient/queue/<int:appointment_id>")
def patient_live_queue(appointment_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "patient":
        return "Access denied.", 403

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return "Patient profile not found.", 404

    appointment = conn.execute("""
        SELECT
            appointments.*,
            users.name AS doctor_name,
            doctors.department,
            doctors.specialization
        FROM appointments
        JOIN doctors
            ON appointments.doctor_id = doctors.id
        JOIN users
            ON doctors.user_id = users.id
        WHERE appointments.id = ?
          AND appointments.patient_id = ?
    """, (appointment_id, patient["id"])).fetchone()

    conn.close()

    if not appointment:
        return "Appointment not found.", 404

    return render_template(
        "patient_live_queue.html",
        appointment=appointment
    )


# =========================================================
# PATIENT LIVE QUEUE API
# =========================================================

@app.route("/patient/queue/<int:appointment_id>/status")
def patient_live_queue_status(appointment_id):

    if "user_id" not in session:
        return {"error": "Login required."}, 401

    if session.get("role") != "patient":
        return {"error": "Access denied."}, 403

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not patient:
        conn.close()
        return {"error": "Patient profile not found."}, 404

    appointment = conn.execute("""
        SELECT
            appointments.*,
            users.name AS doctor_name,
            doctors.department,
            doctors.specialization
        FROM appointments
        JOIN doctors
            ON appointments.doctor_id = doctors.id
        JOIN users
            ON doctors.user_id = users.id
        WHERE appointments.id = ?
          AND appointments.patient_id = ?
    """, (appointment_id, patient["id"])).fetchone()

    if not appointment:
        conn.close()
        return {"error": "Appointment not found."}, 404

    doctor_id = appointment["doctor_id"]
    appointment_date = appointment["appointment_date"]
    own_token = appointment["token_number"]
    own_status = appointment["status"]

    # Find the patient currently being served.
    current = conn.execute("""
        SELECT token_number, status
        FROM appointments
        WHERE doctor_id = ?
          AND appointment_date = ?
          AND status IN ('CALLED', 'IN_PROGRESS')
        ORDER BY token_number ASC
        LIMIT 1
    """, (doctor_id, appointment_date)).fetchone()

    if current:
        current_token = current["token_number"]
    else:
        # If nobody is currently being served, show the last
        # completed/skipped token.
        last_served = conn.execute("""
            SELECT MAX(token_number) AS token_number
            FROM appointments
            WHERE doctor_id = ?
              AND appointment_date = ?
              AND status IN ('COMPLETED', 'SKIPPED')
        """, (doctor_id, appointment_date)).fetchone()

        current_token = (
            last_served["token_number"]
            if last_served and last_served["token_number"] is not None
            else 0
        )

    # Count active patients before this patient's token.
    patients_ahead = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE doctor_id = ?
          AND appointment_date = ?
          AND token_number < ?
          AND status IN ('WAITING', 'CALLED', 'IN_PROGRESS')
    """, (
        doctor_id,
        appointment_date,
        own_token
    )).fetchone()["count"]

    conn.close()

    # Once this patient's appointment is called or started,
    # nobody is ahead.
    if own_status in ("CALLED", "IN_PROGRESS"):
        patients_ahead = 0

    # Completed/skipped/cancelled appointments don't need a wait time.
    if own_status in ("COMPLETED", "SKIPPED", "CANCELLED"):
        estimated_wait = 0
    else:
        # Demo estimate: approximately 10 minutes per patient ahead.
        estimated_wait = patients_ahead * 10

    return {
        "appointment_id": appointment["id"],
        "doctor_name": appointment["doctor_name"],
        "department": appointment["department"],
        "specialization": appointment["specialization"],
        "appointment_date": appointment_date,
        "your_token": own_token,
        "current_token": current_token,
        "patients_ahead": patients_ahead,
        "status": own_status,
        "estimated_wait": estimated_wait
    }



# =========================================================
# DOCTOR AVAILABILITY
# =========================================================

@app.route("/doctor/availability", methods=["GET", "POST"])
def doctor_availability():

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    conn = get_db()

    doctor = conn.execute("""
        SELECT *
        FROM doctors
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor profile not found.", 404

    if doctor["status"] != "approved":
        conn.close()

        flash(
            "Only approved doctors can manage availability.",
            "error"
        )

        return redirect(url_for("doctor_dashboard"))

    if request.method == "POST":

        for day_number in range(7):

            is_available = 1 if request.form.get(
                f"available_{day_number}"
            ) else 0

            start_time = request.form.get(
                f"start_{day_number}",
                "09:00"
            ).strip()

            end_time = request.form.get(
                f"end_{day_number}",
                "17:00"
            ).strip()

            if is_available:

                if not start_time or not end_time:
                    conn.close()

                    flash(
                        f"Please provide working hours for "
                        f"{DAY_NAMES[day_number]}.",
                        "error"
                    )

                    return redirect(
                        url_for("doctor_availability")
                    )

                if start_time >= end_time:
                    conn.close()

                    flash(
                        f"End time must be after start time for "
                        f"{DAY_NAMES[day_number]}.",
                        "error"
                    )

                    return redirect(
                        url_for("doctor_availability")
                    )

            conn.execute("""
                INSERT INTO doctor_availability
                (
                    doctor_id,
                    day_of_week,
                    start_time,
                    end_time,
                    is_available
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(doctor_id, day_of_week)
                DO UPDATE SET
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    is_available = excluded.is_available
            """, (
                doctor["id"],
                day_number,
                start_time,
                end_time,
                is_available
            ))

        conn.commit()

        conn.close()

        flash(
            "Weekly availability updated successfully.",
            "success"
        )

        return redirect(
            url_for("doctor_availability")
        )

    schedule_rows = conn.execute("""
        SELECT
            day_of_week,
            start_time,
            end_time,
            is_available
        FROM doctor_availability
        WHERE doctor_id = ?
        ORDER BY day_of_week
    """, (doctor["id"],)).fetchall()

    schedule_map = {
        row["day_of_week"]: row
        for row in schedule_rows
    }

    days = []

    for number in range(7):

        row = schedule_map.get(number)

        days.append({
            "number": number,
            "name": DAY_NAMES[number],
            "start_time": row["start_time"] if row else "09:00",
            "end_time": row["end_time"] if row else "17:00",
            "is_available": bool(row["is_available"]) if row else False
        })

    unavailable_dates = conn.execute("""
        SELECT
            id,
            unavailable_date,
            reason
        FROM doctor_unavailable_dates
        WHERE doctor_id = ?
        ORDER BY unavailable_date
    """, (doctor["id"],)).fetchall()

    conn.close()

    return render_template(
        "doctor_availability.html",
        days=days,
        unavailable_dates=unavailable_dates,
        today=date.today().isoformat()
    )


@app.route(
    "/doctor/availability/unavailable/add",
    methods=["POST"]
)
def doctor_add_unavailable_date():

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    unavailable_date = request.form.get(
        "unavailable_date",
        ""
    ).strip()

    reason = request.form.get(
        "reason",
        ""
    ).strip()

    try:
        selected_date = date.fromisoformat(
            unavailable_date
        )

    except ValueError:
        flash(
            "Invalid unavailable date.",
            "error"
        )

        return redirect(
            url_for("doctor_availability")
        )

    if selected_date < date.today():

        flash(
            "You cannot block a past date.",
            "error"
        )

        return redirect(
            url_for("doctor_availability")
        )

    conn = get_db()

    doctor = conn.execute("""
        SELECT id, status
        FROM doctors
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor profile not found.", 404

    if doctor["status"] != "approved":
        conn.close()

        flash(
            "Only approved doctors can manage availability.",
            "error"
        )

        return redirect(
            url_for("doctor_dashboard")
        )

    try:

        conn.execute("""
            INSERT INTO doctor_unavailable_dates
            (
                doctor_id,
                unavailable_date,
                reason
            )
            VALUES (?, ?, ?)
        """, (
            doctor["id"],
            unavailable_date,
            reason
        ))

        conn.commit()

        flash(
            f"{unavailable_date} has been marked unavailable.",
            "success"
        )

    except sqlite3.IntegrityError:

        conn.rollback()

        flash(
            "That date is already marked unavailable.",
            "error"
        )

    conn.close()

    return redirect(
        url_for("doctor_availability")
    )


@app.route(
    "/doctor/availability/unavailable/<int:unavailable_id>/remove",
    methods=["POST"]
)
def doctor_remove_unavailable_date(unavailable_id):

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    conn = get_db()

    doctor = conn.execute("""
        SELECT id
        FROM doctors
        WHERE user_id = ?
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor profile not found.", 404

    conn.execute("""
        DELETE FROM doctor_unavailable_dates
        WHERE id = ?
          AND doctor_id = ?
    """, (
        unavailable_id,
        doctor["id"]
    ))

    conn.commit()
    conn.close()

    flash(
        "Unavailable date removed.",
        "success"
    )

    return redirect(
        url_for("doctor_availability")
    )



# =========================================================
# DOCTOR DASHBOARD
# =========================================================

# =========================================================
# DOCTOR QUEUE DASHBOARD
# =========================================================

@app.route("/doctor/dashboard")
def doctor_dashboard():

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    today = date.today().isoformat()

    conn = get_db()

    doctor = conn.execute("""
        SELECT
            doctors.*,
            users.name,
            users.email,
            users.phone
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.user_id = ?
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor profile not found.", 404

    # Today's queue
    appointments = conn.execute("""
        SELECT
            appointments.id,
            appointments.token_number,
            appointments.status,
            appointments.appointment_date,
            users.name AS patient_name,
            patients.age,
            patients.gender
        FROM appointments
        JOIN patients
            ON appointments.patient_id = patients.id
        JOIN users
            ON patients.user_id = users.id
        WHERE appointments.doctor_id = ?
          AND appointments.appointment_date = ?
        ORDER BY appointments.token_number ASC
    """, (
        doctor["id"],
        today
    )).fetchall()

    conn.close()

    return render_template(
        "doctor_dashboard.html",
        doctor=doctor,
        appointments=appointments,
        today=today
    )


# =========================================================
# DOCTOR CALL NEXT PATIENT
# =========================================================

@app.route("/doctor/queue/call-next", methods=["POST"])
def doctor_call_next():

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    today = date.today().isoformat()

    conn = get_db()

    doctor = conn.execute("""
        SELECT
            doctors.*,
            users.name AS doctor_name
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.user_id = ?
          AND doctors.status = 'approved'
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor not found.", 404

    # Do not call another patient while one is active
    active = conn.execute("""
        SELECT *
        FROM appointments
        WHERE doctor_id = ?
          AND appointment_date = ?
          AND status IN ('CALLED', 'IN_PROGRESS')
        LIMIT 1
    """, (
        doctor["id"],
        today
    )).fetchone()

    if active:
        conn.close()

        flash(
            f"Token {active['token_number']} is currently active.",
            "error"
        )

        return redirect(url_for("doctor_dashboard"))

    # Find the first waiting patient
    next_patient = conn.execute("""
        SELECT *
        FROM appointments
        WHERE doctor_id = ?
          AND appointment_date = ?
          AND status = 'WAITING'
        ORDER BY token_number ASC
        LIMIT 1
    """, (
        doctor["id"],
        today
    )).fetchone()

    if not next_patient:
        conn.close()

        flash(
            "There are no waiting patients in today's queue.",
            "error"
        )

        return redirect(url_for("doctor_dashboard"))

    conn.execute("""
        UPDATE appointments
        SET
            status = 'CALLED',
            called_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (next_patient["id"],))

    create_notification(
        conn,
        next_patient["patient_id"],
        "Your Token Has Been Called",
        f"Token {next_patient['token_number']} has been called by "
        f"Dr. {doctor['doctor_name']}. "
        f"Please proceed to the consultation area.",
        "CALL",
        next_patient["id"]
    )

    conn.commit()
    conn.close()

    flash(
        f"Token {next_patient['token_number']} has been called.",
        "success"
    )

    return redirect(url_for("doctor_dashboard"))


# =========================================================
# DOCTOR ACCEPT PATIENT
# =========================================================

@app.route(
    "/doctor/queue/<int:appointment_id>/accept",
    methods=["POST"]
)
def doctor_accept_patient(appointment_id):

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    conn = get_db()

    doctor = conn.execute("""
        SELECT
            doctors.*,
            users.name AS doctor_name
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.user_id = ?
          AND doctors.status = 'approved'
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor not found.", 404

    result = conn.execute("""
        UPDATE appointments
        SET status = 'IN_PROGRESS'
        WHERE id = ?
          AND doctor_id = ?
          AND status = 'CALLED'
    """, (
        appointment_id,
        doctor["id"]
    ))

    if result.rowcount == 0:
        conn.commit()
        conn.close()

        flash(
            "This patient cannot be accepted right now.",
            "error"
        )

        return redirect(url_for("doctor_dashboard"))

    appointment = conn.execute("""
        SELECT
            patient_id,
            token_number
        FROM appointments
        WHERE id = ?
    """, (appointment_id,)).fetchone()

    if appointment:
        create_notification(
            conn,
            appointment["patient_id"],
            "Consultation Started",
            f"Your Token {appointment['token_number']} is now "
            f"IN PROGRESS with Dr. {doctor['doctor_name']}.",
            "START",
            appointment_id
        )

    conn.commit()
    conn.close()

    flash(
        "Patient is now IN PROGRESS.",
        "success"
    )

    return redirect(url_for("doctor_dashboard"))


# =========================================================
# DOCTOR COMPLETE PATIENT
# =========================================================

@app.route(
    "/doctor/queue/<int:appointment_id>/complete",
    methods=["POST"]
)
def doctor_complete_patient(appointment_id):

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    conn = get_db()

    doctor = conn.execute("""
        SELECT
            doctors.*,
            users.name AS doctor_name
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.user_id = ?
          AND doctors.status = 'approved'
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor not found.", 404

    result = conn.execute("""
        UPDATE appointments
        SET
            status = 'COMPLETED',
            completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
          AND doctor_id = ?
          AND status = 'IN_PROGRESS'
    """, (
        appointment_id,
        doctor["id"]
    ))

    if result.rowcount == 0:
        conn.commit()
        conn.close()

        flash(
            "This patient cannot be completed right now.",
            "error"
        )

        return redirect(url_for("doctor_dashboard"))

    appointment = conn.execute("""
        SELECT
            patient_id,
            token_number
        FROM appointments
        WHERE id = ?
    """, (appointment_id,)).fetchone()

    if appointment:
        create_notification(
            conn,
            appointment["patient_id"],
            "Appointment Completed",
            f"Your Token {appointment['token_number']} "
            f"consultation with Dr. {doctor['doctor_name']} "
            f"has been completed successfully.",
            "COMPLETED",
            appointment_id
        )

    conn.commit()
    conn.close()

    flash(
        "Patient appointment completed successfully.",
        "success"
    )

    return redirect(url_for("doctor_dashboard"))


# =========================================================
# DOCTOR SKIP PATIENT
# =========================================================

@app.route(
    "/doctor/queue/<int:appointment_id>/skip",
    methods=["POST"]
)
def doctor_skip_patient(appointment_id):

    if "user_id" not in session:
        return redirect(url_for("doctor_login"))

    if session.get("role") != "doctor":
        return "Access denied.", 403

    conn = get_db()

    doctor = conn.execute("""
        SELECT
            doctors.*,
            users.name AS doctor_name
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.user_id = ?
          AND doctors.status = 'approved'
    """, (session["user_id"],)).fetchone()

    if not doctor:
        conn.close()
        return "Doctor not found.", 404

    result = conn.execute("""
        UPDATE appointments
        SET status = 'SKIPPED'
        WHERE id = ?
          AND doctor_id = ?
          AND status IN ('WAITING', 'CALLED', 'IN_PROGRESS')
    """, (
        appointment_id,
        doctor["id"]
    ))

    if result.rowcount == 0:
        conn.commit()
        conn.close()

        flash(
            "This patient cannot be skipped right now.",
            "error"
        )

        return redirect(url_for("doctor_dashboard"))

    appointment = conn.execute("""
        SELECT
            patient_id,
            token_number
        FROM appointments
        WHERE id = ?
    """, (appointment_id,)).fetchone()

    if appointment:
        create_notification(
            conn,
            appointment["patient_id"],
            "Appointment Skipped",
            f"Your Token {appointment['token_number']} "
            f"appointment with Dr. {doctor['doctor_name']} "
            f"has been skipped.",
            "SKIPPED",
            appointment_id
        )

    conn.commit()
    conn.close()

    flash(
        "Patient has been skipped.",
        "success"
    )

    return redirect(url_for("doctor_dashboard"))


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin/dashboard")
def admin_dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    conn = get_db()

    # =====================================================
    # HOSPITAL STATISTICS
    # =====================================================

    total_patients = conn.execute("""
        SELECT COUNT(*) AS count
        FROM patients
    """).fetchone()["count"]

    total_doctors = conn.execute("""
        SELECT COUNT(*) AS count
        FROM doctors
    """).fetchone()["count"]

    approved_doctors = conn.execute("""
        SELECT COUNT(*) AS count
        FROM doctors
        WHERE status = 'approved'
    """).fetchone()["count"]

    pending_doctors_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM doctors
        WHERE status = 'pending'
    """).fetchone()["count"]

    blocked_doctors = conn.execute("""
        SELECT COUNT(*) AS count
        FROM doctors
        WHERE status = 'blocked'
    """).fetchone()["count"]

    # =====================================================
    # TODAY'S APPOINTMENT STATISTICS
    # =====================================================

    from datetime import date

    today = date.today().isoformat()

    todays_appointments = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE appointment_date = ?
    """, (today,)).fetchone()["count"]

    waiting_appointments = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE appointment_date = ?
          AND status = 'WAITING'
    """, (today,)).fetchone()["count"]

    called_appointments = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE appointment_date = ?
          AND status = 'CALLED'
    """, (today,)).fetchone()["count"]

    in_progress_appointments = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE appointment_date = ?
          AND status = 'IN_PROGRESS'
    """, (today,)).fetchone()["count"]

    completed_appointments = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE appointment_date = ?
          AND status = 'COMPLETED'
    """, (today,)).fetchone()["count"]

    skipped_appointments = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE appointment_date = ?
          AND status = 'SKIPPED'
    """, (today,)).fetchone()["count"]

    cancelled_appointments = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appointments
        WHERE appointment_date = ?
          AND status = 'CANCELLED'
    """, (today,)).fetchone()["count"]

    # =====================================================
    # PENDING DOCTOR REGISTRATIONS
    # =====================================================

    pending_doctors = conn.execute("""
        SELECT
            doctors.id AS doctor_id,
            doctors.department,
            doctors.specialization,
            doctors.qualification,
            doctors.experience,
            users.name,
            users.email,
            users.phone
        FROM doctors
        JOIN users
            ON doctors.user_id = users.id
        WHERE doctors.status = 'pending'
        ORDER BY doctors.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "admin_dashboard.html",
        name=session.get("name"),

        total_patients=total_patients,
        total_doctors=total_doctors,
        approved_doctors=approved_doctors,
        pending_doctors_count=pending_doctors_count,
        blocked_doctors=blocked_doctors,

        todays_appointments=todays_appointments,
        waiting_appointments=waiting_appointments,
        called_appointments=called_appointments,
        in_progress_appointments=in_progress_appointments,
        completed_appointments=completed_appointments,
        skipped_appointments=skipped_appointments,
        cancelled_appointments=cancelled_appointments,

        pending_doctors=pending_doctors
    )


# =========================================================
# ADMIN - ALL PATIENTS
# =========================================================

@app.route("/admin/patients")
def admin_patients():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    conn = get_db()

    patients = conn.execute("""
        SELECT
            patients.id AS patient_id,
            users.name,
            users.email,
            users.phone,
            patients.age,
            patients.gender,
            users.created_at
        FROM patients
        JOIN users
            ON patients.user_id = users.id
        ORDER BY patients.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "admin_patients.html",
        patients=patients
    )



# =========================================================

# =====================================================
# ADMIN - VIEW ALL DOCTORS
# =====================================================

@app.route("/admin/doctors")
def admin_doctors():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    status = request.args.get("status", "").lower()

    allowed_statuses = [
        "pending",
        "approved",
        "blocked"
    ]

    conn = get_db()

    if status in allowed_statuses:

        doctors = conn.execute("""
            SELECT
                doctors.id AS doctor_id,
                doctors.department,
                doctors.specialization,
                doctors.qualification,
                doctors.experience,
                doctors.status,
                users.name,
                users.email,
                users.phone
            FROM doctors
            JOIN users
                ON doctors.user_id = users.id
            WHERE doctors.status = ?
            ORDER BY doctors.id DESC
        """, (status,)).fetchall()

        page_title = status.title() + " Doctors"

    else:

        doctors = conn.execute("""
            SELECT
                doctors.id AS doctor_id,
                doctors.department,
                doctors.specialization,
                doctors.qualification,
                doctors.experience,
                doctors.status,
                users.name,
                users.email,
                users.phone
            FROM doctors
            JOIN users
                ON doctors.user_id = users.id
            ORDER BY doctors.id DESC
        """).fetchall()

        page_title = "All Doctors"

    conn.close()

    return render_template(
        "admin_doctors.html",
        doctors=doctors,
        page_title=page_title,
        selected_status=status
    )



@app.route("/admin/appointments")
def admin_appointments():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    status = request.args.get("status", "").upper()

    allowed_statuses = [
        "WAITING",
        "CALLED",
        "IN_PROGRESS",
        "COMPLETED",
        "SKIPPED",
        "CANCELLED"
    ]

    conn = get_db()

    if status in allowed_statuses:

        appointments = conn.execute("""
            SELECT
                appointments.id AS appointment_id,
                appointments.appointment_date,
                appointments.token_number,
                appointments.status,
                appointments.created_at,
                appointments.called_at,
                appointments.completed_at,

                patients.id AS patient_id,
                patient_users.name AS patient_name,
                patient_users.email AS patient_email,
                patient_users.phone AS patient_phone,

                doctors.id AS doctor_id,
                doctor_users.name AS doctor_name,
                doctors.department,
                doctors.specialization

            FROM appointments

            JOIN patients
                ON appointments.patient_id = patients.id

            JOIN users AS patient_users
                ON patients.user_id = patient_users.id

            JOIN doctors
                ON appointments.doctor_id = doctors.id

            JOIN users AS doctor_users
                ON doctors.user_id = doctor_users.id

            WHERE appointments.status = ?

            ORDER BY
                appointments.appointment_date DESC,
                appointments.token_number ASC
        """, (status,)).fetchall()

        page_title = status.replace("_", " ").title()

    else:

        appointments = conn.execute("""
            SELECT
                appointments.id AS appointment_id,
                appointments.appointment_date,
                appointments.token_number,
                appointments.status,
                appointments.created_at,
                appointments.called_at,
                appointments.completed_at,

                patients.id AS patient_id,
                patient_users.name AS patient_name,
                patient_users.email AS patient_email,
                patient_users.phone AS patient_phone,

                doctors.id AS doctor_id,
                doctor_users.name AS doctor_name,
                doctors.department,
                doctors.specialization

            FROM appointments

            JOIN patients
                ON appointments.patient_id = patients.id

            JOIN users AS patient_users
                ON patients.user_id = patient_users.id

            JOIN doctors
                ON appointments.doctor_id = doctors.id

            JOIN users AS doctor_users
                ON doctors.user_id = doctor_users.id

            ORDER BY
                appointments.appointment_date DESC,
                appointments.token_number ASC
        """).fetchall()

        page_title = "All Appointments"

    conn.close()

    return render_template(
        "admin_appointments.html",
        appointments=appointments,
        page_title=page_title,
        selected_status=status
    )


# =====================================================
# ADMIN - BLOCK DOCTOR
# =====================================================

@app.route("/admin/doctor/<int:doctor_id>/block", methods=["POST"])
def block_doctor(doctor_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    conn = get_db()

    conn.execute("""
        UPDATE doctors
        SET status = 'blocked'
        WHERE id = ?
    """, (doctor_id,))

    conn.commit()
    conn.close()

    return redirect(url_for(
        "admin_doctors",
        status="approved"
    ))


# =====================================================
# ADMIN - UNBLOCK DOCTOR
# =====================================================

@app.route("/admin/doctor/<int:doctor_id>/unblock", methods=["POST"])
def unblock_doctor(doctor_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    conn = get_db()

    conn.execute("""
        UPDATE doctors
        SET status = 'approved'
        WHERE id = ?
    """, (doctor_id,))

    conn.commit()
    conn.close()

    return redirect(url_for(
        "admin_doctors",
        status="blocked"
    ))



# =====================================================
# ADMIN - REPORTS & APPOINTMENT HISTORY
# =====================================================

@app.route("/admin/analytics")
def admin_analytics():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    conn = get_db()

    # =====================================================
    # OVERALL APPOINTMENT STATISTICS
    # =====================================================

    total_appointments = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
    """).fetchone()[0]

    waiting = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'WAITING'
    """).fetchone()[0]

    called = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'CALLED'
    """).fetchone()[0]

    in_progress = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'IN_PROGRESS'
    """).fetchone()[0]

    completed = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'COMPLETED'
    """).fetchone()[0]

    skipped = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'SKIPPED'
    """).fetchone()[0]

    cancelled = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'CANCELLED'
    """).fetchone()[0]

    active_queue = waiting + called + in_progress

    if total_appointments > 0:
        completion_rate = round(
            (completed / total_appointments) * 100,
            1
        )

        skip_rate = round(
            (skipped / total_appointments) * 100,
            1
        )

        cancellation_rate = round(
            (cancelled / total_appointments) * 100,
            1
        )

    else:
        completion_rate = 0
        skip_rate = 0
        cancellation_rate = 0

    # =====================================================
    # HOSPITAL PERFORMANCE SCORE
    # =====================================================

    performance_score = round(
        (
            completion_rate * 0.60
            + max(0, 100 - skip_rate) * 0.20
            + max(0, 100 - cancellation_rate) * 0.20
        ),
        1
    )

    if performance_score >= 90:
        performance_label = "Excellent"
    elif performance_score >= 75:
        performance_label = "Very Good"
    elif performance_score >= 60:
        performance_label = "Good"
    elif performance_score >= 40:
        performance_label = "Needs Improvement"
    else:
        performance_label = "Critical"

    # =====================================================
    # PATIENT / DOCTOR COUNTS
    # =====================================================

    total_patients = conn.execute("""
        SELECT COUNT(*)
        FROM patients
    """).fetchone()[0]

    active_doctors = conn.execute("""
        SELECT COUNT(*)
        FROM doctors
        WHERE status = 'approved'
    """).fetchone()[0]

    # =====================================================
    # STATUS DISTRIBUTION
    # =====================================================

    status_stats = conn.execute("""
        SELECT
            status,
            COUNT(*) AS total
        FROM appointments
        GROUP BY status
        ORDER BY total DESC
    """).fetchall()

    # =====================================================
    # DAILY APPOINTMENT TREND
    # =====================================================

    daily_stats = conn.execute("""
        SELECT
            appointment_date,
            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN status = 'COMPLETED'
                    THEN 1 ELSE 0
                END
            ) AS completed,

            SUM(
                CASE
                    WHEN status = 'SKIPPED'
                    THEN 1 ELSE 0
                END
            ) AS skipped,

            SUM(
                CASE
                    WHEN status = 'CANCELLED'
                    THEN 1 ELSE 0
                END
            ) AS cancelled

        FROM appointments

        GROUP BY appointment_date

        ORDER BY appointment_date DESC

        LIMIT 14
    """).fetchall()

    # Display oldest to newest for the visual trend
    daily_stats = list(reversed(daily_stats))

    # =====================================================
    # DOCTOR PERFORMANCE
    # =====================================================

    doctor_stats = conn.execute("""
        SELECT

            doctors.id AS doctor_id,

            doctor_users.name AS doctor_name,

            doctors.department,

            doctors.specialization,

            COUNT(appointments.id) AS total,

            SUM(
                CASE
                    WHEN appointments.status = 'COMPLETED'
                    THEN 1 ELSE 0
                END
            ) AS completed,

            SUM(
                CASE
                    WHEN appointments.status = 'SKIPPED'
                    THEN 1 ELSE 0
                END
            ) AS skipped,

            SUM(
                CASE
                    WHEN appointments.status = 'CANCELLED'
                    THEN 1 ELSE 0
                END
            ) AS cancelled

        FROM doctors

        JOIN users AS doctor_users
            ON doctors.user_id = doctor_users.id

        LEFT JOIN appointments
            ON appointments.doctor_id = doctors.id

        WHERE doctors.status = 'approved'

        GROUP BY doctors.id

        ORDER BY total DESC
    """).fetchall()

    doctor_stats = [dict(row) for row in doctor_stats]

    for doctor in doctor_stats:

        total = doctor["total"] or 0
        completed_count = doctor["completed"] or 0

        if total > 0:
            doctor["completion_rate"] = round(
                (completed_count / total) * 100,
                1
            )
        else:
            doctor["completion_rate"] = 0

    doctor_stats.sort(
        key=lambda x: (
            x["completion_rate"],
            x["completed"],
            x["total"]
        ),
        reverse=True
    )

    # =====================================================
    # DEPARTMENT PERFORMANCE
    # =====================================================

    department_stats = conn.execute("""
        SELECT

            doctors.department,

            COUNT(appointments.id) AS total,

            SUM(
                CASE
                    WHEN appointments.status = 'COMPLETED'
                    THEN 1 ELSE 0
                END
            ) AS completed,

            SUM(
                CASE
                    WHEN appointments.status = 'SKIPPED'
                    THEN 1 ELSE 0
                END
            ) AS skipped,

            SUM(
                CASE
                    WHEN appointments.status = 'CANCELLED'
                    THEN 1 ELSE 0
                END
            ) AS cancelled

        FROM doctors

        LEFT JOIN appointments
            ON appointments.doctor_id = doctors.id

        WHERE doctors.status = 'approved'

        GROUP BY doctors.department

        ORDER BY total DESC
    """).fetchall()

    department_stats = [dict(row) for row in department_stats]

    for department in department_stats:

        total = department["total"] or 0
        completed_count = department["completed"] or 0

        if total > 0:
            department["completion_rate"] = round(
                (completed_count / total) * 100,
                1
            )
        else:
            department["completion_rate"] = 0

    # =====================================================
    # TOP DOCTORS
    # =====================================================

    top_doctors = doctor_stats[:5]

    # =====================================================
    # TODAY'S STATISTICS
    # =====================================================

    from datetime import date

    today = date.today().isoformat()

    today_total = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE appointment_date = ?
    """, (today,)).fetchone()[0]

    today_completed = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE appointment_date = ?
          AND status = 'COMPLETED'
    """, (today,)).fetchone()[0]

    today_active = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE appointment_date = ?
          AND status IN (
              'WAITING',
              'CALLED',
              'IN_PROGRESS'
          )
    """, (today,)).fetchone()[0]

    conn.close()

    return render_template(
        "admin_analytics.html",

        total_patients=total_patients,
        active_doctors=active_doctors,

        total_appointments=total_appointments,

        waiting=waiting,
        called=called,
        in_progress=in_progress,
        completed=completed,
        skipped=skipped,
        cancelled=cancelled,

        active_queue=active_queue,

        completion_rate=completion_rate,
        skip_rate=skip_rate,
        cancellation_rate=cancellation_rate,

        performance_score=performance_score,
        performance_label=performance_label,

        status_stats=status_stats,
        daily_stats=daily_stats,

        doctor_stats=doctor_stats,
        department_stats=department_stats,
        top_doctors=top_doctors,

        today=today,
        today_total=today_total,
        today_completed=today_completed,
        today_active=today_active
    )


@app.route("/admin/reports")
def admin_reports():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    selected_date = request.args.get("date", "")
    selected_status = request.args.get("status", "").upper()

    allowed_statuses = [
        "WAITING",
        "CALLED",
        "IN_PROGRESS",
        "COMPLETED",
        "SKIPPED",
        "CANCELLED"
    ]

    conn = get_db()

    # =================================================
    # SUMMARY STATISTICS
    # =================================================

    total_patients = conn.execute("""
        SELECT COUNT(*)
        FROM patients
    """).fetchone()[0]

    total_doctors = conn.execute("""
        SELECT COUNT(*)
        FROM doctors
        WHERE status = 'approved'
    """).fetchone()[0]

    total_appointments = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
    """).fetchone()[0]

    completed = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'COMPLETED'
    """).fetchone()[0]

    skipped = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'SKIPPED'
    """).fetchone()[0]

    cancelled = conn.execute("""
        SELECT COUNT(*)
        FROM appointments
        WHERE status = 'CANCELLED'
    """).fetchone()[0]

    # =================================================
    # APPOINTMENT HISTORY
    # =================================================

    query = """
        SELECT
            appointments.id AS appointment_id,
            appointments.appointment_date,
            appointments.token_number,
            appointments.status,

            patient_users.name AS patient_name,

            doctor_users.name AS doctor_name,

            doctors.department,
            doctors.specialization

        FROM appointments

        JOIN patients
            ON appointments.patient_id = patients.id

        JOIN users AS patient_users
            ON patients.user_id = patient_users.id

        JOIN doctors
            ON appointments.doctor_id = doctors.id

        JOIN users AS doctor_users
            ON doctors.user_id = doctor_users.id

        WHERE 1 = 1
    """

    params = []

    if selected_date:
        query += """
            AND appointments.appointment_date = ?
        """
        params.append(selected_date)

    if selected_status in allowed_statuses:
        query += """
            AND appointments.status = ?
        """
        params.append(selected_status)

    query += """
        ORDER BY
            appointments.appointment_date DESC,
            appointments.token_number ASC
    """

    appointments = conn.execute(
        query,
        params
    ).fetchall()

    # =================================================
    # DOCTOR-WISE REPORT
    # =================================================

    doctor_stats = conn.execute("""
        SELECT
            doctors.id AS doctor_id,
            doctor_users.name AS doctor_name,
            doctors.department,

            COUNT(appointments.id) AS total,

            SUM(
                CASE
                    WHEN appointments.status = 'COMPLETED'
                    THEN 1 ELSE 0
                END
            ) AS completed,

            SUM(
                CASE
                    WHEN appointments.status = 'SKIPPED'
                    THEN 1 ELSE 0
                END
            ) AS skipped

        FROM doctors

        JOIN users AS doctor_users
            ON doctors.user_id = doctor_users.id

        LEFT JOIN appointments
            ON appointments.doctor_id = doctors.id

        GROUP BY
            doctors.id

        ORDER BY
            total DESC
    """).fetchall()

    # =================================================
    # DEPARTMENT-WISE REPORT
    # =================================================

    department_stats = conn.execute("""
        SELECT
            doctors.department,

            COUNT(appointments.id) AS total,

            SUM(
                CASE
                    WHEN appointments.status = 'COMPLETED'
                    THEN 1 ELSE 0
                END
            ) AS completed,

            SUM(
                CASE
                    WHEN appointments.status = 'SKIPPED'
                    THEN 1 ELSE 0
                END
            ) AS skipped

        FROM doctors

        LEFT JOIN appointments
            ON appointments.doctor_id = doctors.id

        GROUP BY
            doctors.department

        ORDER BY
            total DESC
    """).fetchall()

    conn.close()

    return render_template(
        "admin_reports.html",

        total_patients=total_patients,
        total_doctors=total_doctors,
        total_appointments=total_appointments,
        completed=completed,
        skipped=skipped,
        cancelled=cancelled,

        appointments=appointments,

        doctor_stats=doctor_stats,
        department_stats=department_stats,

        selected_date=selected_date,
        selected_status=selected_status
    )


# ADMIN APPROVE DOCTOR
# =========================================================

@app.route("/admin/doctor/<int:doctor_id>/approve", methods=["POST"])
def approve_doctor(doctor_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        return "Access denied.", 403

    conn = get_db()

    conn.execute("""
        UPDATE doctors
        SET status = 'approved'
        WHERE id = ?
    """, (doctor_id,))

    conn.commit()
    conn.close()

    flash("Doctor approved successfully.", "success")

    return redirect(url_for("admin_dashboard"))


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out.", "success")

    return redirect(url_for("login"))


# =========================================================
# START SERVER
# =========================================================

init_database()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )

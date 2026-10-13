import sqlite3
from werkzeug.security import generate_password_hash

DATABASE = "hospital.db"

patients = [
    ("Rahul Kumar", "rahul@gmail.com", "9000000001", 22, "Male"),
    ("Priya Sharma", "priya@gmail.com", "9000000002", 25, "Female"),
    ("Arjun Reddy", "arjun@gmail.com", "9000000003", 28, "Male"),
    ("Sneha Rao", "sneha@gmail.com", "9000000004", 24, "Female"),
    ("Kiran Kumar", "kiran@gmail.com", "9000000005", 31, "Male"),
    ("Anjali Devi", "anjali@gmail.com", "9000000006", 27, "Female"),
    ("Vikram Singh", "vikram@gmail.com", "9000000007", 35, "Male"),
    ("Pooja Reddy", "pooja@gmail.com", "9000000008", 23, "Female"),
    ("Rohit Verma", "rohit@gmail.com", "9000000009", 29, "Male"),
    ("Divya Sharma", "divya@gmail.com", "9000000010", 26, "Female"),
    ("Sai Krishna", "sai@gmail.com", "9000000011", 30, "Male"),
    ("Meena Kumari", "meena@gmail.com", "9000000012", 33, "Female"),
    ("Naveen Reddy", "naveen@gmail.com", "9000000013", 21, "Male"),
    ("Kavya Rao", "kavya@gmail.com", "9000000014", 25, "Female"),
    ("Aditya Kumar", "aditya@gmail.com", "9000000015", 32, "Male"),
    ("Lakshmi Devi", "lakshmi@gmail.com", "9000000016", 40, "Female"),
    ("Manoj Kumar", "manoj@gmail.com", "9000000017", 38, "Male"),
    ("Harini Reddy", "harini@gmail.com", "9000000018", 29, "Female"),
    ("Suresh Babu", "suresh@gmail.com", "9000000019", 45, "Male"),
    ("Neha Singh", "neha@gmail.com", "9000000020", 34, "Female"),
]

doctors = [
    ("Dr. Rajesh Kumar", "dr.rajesh@gmail.com", "9100000001", "General Medicine", "MBBS, MD", 12),
    ("Dr. Priya Sharma", "dr.priya@gmail.com", "9100000002", "Cardiology", "MBBS, MD", 10),
    ("Dr. Arvind Rao", "dr.arvind@gmail.com", "9100000003", "Dermatology", "MBBS, MD", 8),
    ("Dr. Sneha Reddy", "dr.sneha@gmail.com", "9100000004", "Pediatrics", "MBBS, DCH", 9),
    ("Dr. Kiran Singh", "dr.kiran@gmail.com", "9100000005", "Orthopedics", "MBBS, MS", 15),
    ("Dr. Anjali Devi", "dr.anjali@gmail.com", "9100000006", "Gynecology", "MBBS, MD", 11),
    ("Dr. Vikram Rao", "dr.vikram@gmail.com", "9100000007", "ENT", "MBBS, MS", 7),
    ("Dr. Pooja Kumar", "dr.pooja@gmail.com", "9100000008", "Ophthalmology", "MBBS, MS", 13),
    ("Dr. Rahul Reddy", "dr.rahul@gmail.com", "9100000009", "Neurology", "MBBS, MD", 14),
    ("Dr. Meena Sharma", "dr.meena@gmail.com", "9100000010", "Dentistry", "BDS, MDS", 6),
]

password = "123456"

conn = sqlite3.connect(DATABASE)
cursor = conn.cursor()

patient_count = 0
doctor_count = 0

# Insert patients
for name, email, phone, age, gender in patients:
    try:
        cursor.execute("""
            INSERT INTO users (name, email, phone, password, role)
            VALUES (?, ?, ?, ?, 'patient')
        """, (
            name,
            email,
            phone,
            generate_password_hash(password)
        ))

        user_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO patients (user_id, age, gender)
            VALUES (?, ?, ?)
        """, (user_id, age, gender))

        patient_count += 1

    except sqlite3.IntegrityError:
        pass


# Insert doctors
for name, email, phone, department, qualification, experience in doctors:
    try:
        cursor.execute("""
            INSERT INTO users (name, email, phone, password, role)
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
            (user_id, department, specialization, qualification, experience, status)
            VALUES (?, ?, ?, ?, ?, 'approved')
        """, (
            user_id,
            department,
            department,
            qualification,
            experience
        ))

        doctor_count += 1

    except sqlite3.IntegrityError:
        pass


conn.commit()
conn.close()

print()
print("===================================")
print("       MediQueue Demo Data")
print("===================================")
print(f"Patients added : {patient_count}")
print(f"Doctors added  : {doctor_count}")
print("Default password: 123456")
print("===================================")

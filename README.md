# MediQueue 🏥

**Hospital Appointment and Real-Time Queue Management System**

MediQueue is a web application designed to simplify hospital appointments and help patients and doctors track appointment queues.

## Features

### Patient
- Patient registration and login
- Browse available doctors
- Book and view appointments
- Track appointment tokens and queue status
- Cancel eligible appointments

### Doctor
- Doctor registration with administrator approval
- Secure doctor login
- Manage availability
- Call, complete, and skip patients
- Track appointment queues

### Administrator
- Separate administrator login
- Dashboard with appointment statistics
- Manage patients and doctors
- Review doctor approval status
- View analytics and reports
- Monitor appointment history and performance

## Technology Stack

- Frontend: HTML, CSS, JavaScript
- Backend: Python and Flask
- Database: SQLite
- Testing: pytest

## Run Locally

1. Install Python 3 and Git.
2. Clone the repository:

   ```bash
   git clone https://github.com/BALAJIIRLA/MediQueue.git
   cd MediQueue
   ```

3. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Set a secret key and start the app:

   ```bash
   export MEDIQUEUE_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
   python app.py
   ```

6. Open `http://127.0.0.1:5000` in your browser.

The application initializes its database on startup. Keep `hospital.db` in the intended working directory and back it up before upgrades.

For production, configure `MEDIQUEUE_SECRET_KEY` in the hosting platform's environment settings and use a production WSGI server such as Gunicorn. Do not run Flask's development server with debug mode enabled in production.

## Testing

Run the test suite with:

```bash
PYTHONPATH="$PWD/tests" python -m pytest -q tests --import-mode=importlib
```

## Data and Security

- Never commit real patient records, database files, passwords, or secret keys.
- Configure a strong secret key for deployment.
- Use persistent storage or a managed database in production.
- Keep encrypted, access-controlled backups of important data.
- Use HTTPS for deployed applications.
- Use fictional data for demonstrations and college presentations.

## Deployment

Deployment instructions will be added after the production hosting and persistent database configuration are finalized.

## Project Purpose

Created as a college project to demonstrate appointment booking, role-based access, and real-time hospital queue management.

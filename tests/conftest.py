"""
Safety: these tests DROP AND RECREATE ALL TABLES. They must never touch a real
database, so this file forces a throwaway SQLite file and dummy credentials
BEFORE the app is imported, whatever your .env says.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)          # lets plain `pytest` find main.py

_db_file = os.path.join(tempfile.gettempdir(), "hr_backend_pytest.db").replace("\\", "/")

# Environment variables take priority over .env, so these always win.
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_db_file}",
    "OPENAI_API_KEY": "sk-test-not-real",
    "SMTP_HOST": "localhost", "SMTP_PORT": "2525", "SMTP_FROM": "test@example.com",
    "SMTP_USERNAME": "test@example.com", "SMTP_PASSWORD": "not-real",
    "SENDER_EMAIL": "", "SENDER_PASSWORD": "",
    "SECRET_KEY": "pytest-only-secret-key-0123456789-abcdefghij",
    "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "admin",
    "SCORE_THRESHOLD": "25",
    "REDIS_URL": "redis://localhost:1",
})

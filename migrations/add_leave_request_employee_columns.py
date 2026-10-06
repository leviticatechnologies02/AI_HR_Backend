"""
Adds the columns the leave service already relies on to leave_requests:
employee_id, is_half_day, approved_by, rejection_reason, applied_at, updated_at.
Safe to run more than once.   Usage:  python migrations/add_leave_request_employee_columns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from core.database import engine

COLUMNS = [
    ("employee_id",      "INTEGER REFERENCES employees(id)"),
    ("is_half_day",      "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("approved_by",      "INTEGER"),
    ("rejection_reason", "VARCHAR"),
    ("applied_at",       "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("updated_at",       "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
]


def run_schema_migration():
    existing = {c["name"] for c in inspect(engine).get_columns("leave_requests")}
    with engine.connect() as conn:
        for name, ddl in COLUMNS:
            if name in existing:
                print(f"leave_requests.{name} already exists - skipping.")
                continue
            print(f"Adding leave_requests.{name} ...")
            conn.execute(text(f"ALTER TABLE leave_requests ADD COLUMN {name} {ddl}"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_leave_requests_employee_id ON leave_requests (employee_id)"
        ))
        conn.commit()


if __name__ == "__main__":
    run_schema_migration()
    print("Done.")

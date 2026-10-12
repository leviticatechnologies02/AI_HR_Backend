"""
Gives every job a branch.

1. Adds job.location_id (the app also does this at startup; running it here is harmless).
2. Backfills existing jobs, so a company user who selects a branch sees them:
     a) the branch whose name appears in the job's free-text location ("Hitech City, Hyderabad" -> Hyderabad);
     b) otherwise the recruiter's own branch.
   Jobs that match neither stay without a branch; they still show under "All Branches".

Safe to run more than once.   Usage:  python migrations/add_job_location_id.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from core.database import engine


def run():
    with engine.begin() as conn:
        cols = [c["name"] for c in inspect(conn).get_columns("job")]
        if "location_id" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN location_id INTEGER REFERENCES company_locations(id)"))
            print("Added job.location_id")
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_job_location_id ON job(location_id)"))

        by_text = conn.execute(text("""
            UPDATE job SET location_id = (
                SELECT cl.id FROM company_locations cl
                JOIN "user" u ON u.tenant_id = cl.tenant_id
                WHERE u.id = job.recruiter_id AND cl.is_active = TRUE
                  AND lower(job.location) LIKE '%' || lower(trim(cl.name)) || '%'
                ORDER BY cl.is_default DESC, cl.id LIMIT 1)
            WHERE location_id IS NULL AND location IS NOT NULL AND trim(location) <> ''
        """)).rowcount
        by_recruiter = conn.execute(text("""
            UPDATE job SET location_id = (SELECT u.location_id FROM "user" u WHERE u.id = job.recruiter_id)
            WHERE location_id IS NULL
              AND (SELECT u.location_id FROM "user" u WHERE u.id = job.recruiter_id) IS NOT NULL
        """)).rowcount
        left = conn.execute(text("SELECT count(*) FROM job WHERE location_id IS NULL")).scalar()
    print(f"Backfilled {by_text} job(s) from their location text, {by_recruiter} from the recruiter's branch; {left} left without a branch.")


if __name__ == "__main__":
    run()

import os

from dotenv import load_dotenv

load_dotenv()

# Sender account for aptitude-test OTP emails. Set in .env; never hard-code.
# Falls back to the main SMTP account so one mailbox can serve everything.
SENDER_EMAIL = os.getenv("SENDER_EMAIL") or os.getenv("SMTP_USERNAME", "")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD") or os.getenv("SMTP_PASSWORD", "")

OTP_EXPIRY = 300
EXAM_DURATION = 30 * 60
PASS_THRESHOLD = 30

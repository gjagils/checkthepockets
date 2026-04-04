import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://checkthepockets:checkthepockets@db:5432/checkthepockets",
)
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "86400"))  # 24 hours

# Sprint 14 — Auth & security
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "noreply@check-your-pockets.com")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")
REGISTRATION_OPEN = os.getenv("REGISTRATION_OPEN", "true").lower() == "true"
REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"

# Sprint 16 — Encryption at-rest
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY", "")

# Super admin — can never be deactivated or de-admin'd
SUPER_ADMIN_USERNAME = os.getenv("SUPER_ADMIN_USERNAME", "")

# Sprint 17 — AI rule suggestions
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Sprint 18 — Google OAuth login
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://checkthepockets:checkthepockets@db:5432/checkthepockets",
)
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE") or "86400")  # 24 hours; een lege waarde telt als niet gezet

# Sprint 14 — Auth & security
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "noreply@check-your-pockets.com")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() == "true" or APP_URL.lower().startswith("https://")
CSRF_ENFORCE = ENVIRONMENT in {"production", "prod"} or os.getenv("CSRF_ENFORCE", "false").lower() == "true"
REGISTRATION_OPEN = os.getenv("REGISTRATION_OPEN", "true").lower() == "true"
REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"

# Sprint 16 — Encryption at-rest
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY", "")

# Super admin — can never be deactivated or de-admin'd
SUPER_ADMIN_USERNAME = os.getenv("SUPER_ADMIN_USERNAME", "")

# Sprint 17 — AI rule suggestions
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Model voor AI-suggesties; overschrijfbaar zodat een uitgefaseerd model geen codewijziging vraagt.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5-5"

# Sprint 18 — Google OAuth login
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Enable Banking — PSD2 bank connection
ENABLE_BANKING_APP_ID = os.getenv("ENABLE_BANKING_APP_ID", "")
ENABLE_BANKING_PRIVATE_KEY_PATH = os.getenv("ENABLE_BANKING_PRIVATE_KEY_PATH", "")


def validate_production_config() -> None:
    """Fail fast instead of starting with an unsafe production setup."""
    if ENVIRONMENT not in {"production", "prod"}:
        return
    errors = []
    if not SECRET_KEY or SECRET_KEY in {"change-me-in-production", "verander-dit-in-een-lang-willekeurig-wachtwoord"} or len(SECRET_KEY) < 32:
        errors.append("SECRET_KEY must be a unique value of at least 32 characters")
    if not APP_URL.lower().startswith("https://"):
        errors.append("APP_URL must use https:// in production")
    if not COOKIE_SECURE:
        errors.append("COOKIE_SECURE must be true in production")
    if not FIELD_ENCRYPTION_KEY:
        errors.append("FIELD_ENCRYPTION_KEY must be configured in production")
    else:
        try:
            from cryptography.fernet import Fernet
            Fernet(FIELD_ENCRYPTION_KEY.encode())
        except Exception:
            errors.append("FIELD_ENCRYPTION_KEY is not a valid Fernet key")
    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))

# Background scheduler (jobs: bank sync, digests, ...). Zet op false in alle processen behalve één als
# er meerdere workers/containers draaien; de advisory lock in logged_job voorkomt dubbel draaien ook zo.
SCHEDULER_ENABLED = (os.getenv("SCHEDULER_ENABLED") or "true").lower() != "false"
# PostgreSQL advisory lock per job (voorkomt dubbel draaien). Standaard uit: sessie-locks zijn onbetrouwbaar
# achter een transaction-pooler (bijv. een Neon "-pooler"-verbinding) en kunnen daar een job blijven blokkeren.
# Zet alleen aan met een directe (niet-gepoolde) databaseverbinding.
SCHEDULER_LOCK = (os.getenv("SCHEDULER_LOCK") or "false").lower() == "true"

# bunq API (ACT-31). Zet op https://public-api.sandbox.bunq.com/v1 om te testen met nepgeld.
BUNQ_API_BASE = os.getenv("BUNQ_API_BASE") or "https://api.bunq.com/v1"

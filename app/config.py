import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://checkthepockets:checkthepockets@db:5432/checkthepockets",
)
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "86400"))  # 24 hours

# Plaid Bank Account Data API
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")  # "sandbox" or "production"

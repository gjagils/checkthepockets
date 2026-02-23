import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://checkthepockets:checkthepockets@db:5432/checkthepockets",
)
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "86400"))  # 24 hours

# GoCardless / Nordigen Bank Account Data API
NORDIGEN_SECRET_ID = os.getenv("NORDIGEN_SECRET_ID", "")
NORDIGEN_SECRET_KEY = os.getenv("NORDIGEN_SECRET_KEY", "")
NORDIGEN_BASE_URL = os.getenv("NORDIGEN_BASE_URL", "https://bankaccountdata.gocardless.com/api/v2")

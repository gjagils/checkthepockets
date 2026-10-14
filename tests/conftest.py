"""Gedeelde testconfiguratie (ACT-39).

Pytest laadt dit bestand vóór alle testmodules. Daardoor bestaat er precies één engine met één
tijdelijke SQLite-database voor de hele run (voorheen zette elk van de ~40 modules zelf
`DATABASE_URL` en won alleen de eerste), en dwingen alle tests foreign keys af zoals PostgreSQL.
"""
import os
import tempfile

# Moet vóór de eerste `import app...` staan: de engine wordt bij import aangemaakt.
_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB_FILE.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.name}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENVIRONMENT"] = "development"

import pytest  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402


@event.listens_for(engine, "connect")
def _enforce_foreign_keys(dbapi_connection, _record):
    """SQLite negeert foreign keys standaard; PostgreSQL (productie) niet. Gelijk trekken."""
    dbapi_connection.execute("PRAGMA foreign_keys=ON")


@pytest.fixture(autouse=True)
def _fresh_schema():
    """Elke test begint met lege tabellen (en laat er geen achter)."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def db_session(db):
    """Oudere naam voor `db`; beide geven dezelfde sessie."""
    return db

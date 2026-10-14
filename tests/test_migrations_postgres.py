"""ACT-41: migraties en modellen op een echte PostgreSQL. Draait alleen met POSTGRES_TEST_URL gezet
(de CI-job `postgres-migrations` doet dat); de database wordt bij elke test leeggemaakt."""
import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

URL = os.environ.get("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="POSTGRES_TEST_URL niet gezet")


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


def _config():
    return Config("alembic.ini")


def test_upgrade_matches_the_models_exactly(pg):
    """Autogenerate geeft een lege diff (server defaults buiten beschouwing: de modellen gebruiken Python-defaults)."""
    from app.database import Base
    import app.models  # noqa: F401

    command.upgrade(_config(), "head")
    with pg.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": False})
        assert compare_metadata(context, Base.metadata) == []


def test_up_down_up(pg):
    command.upgrade(_config(), "head")
    command.downgrade(_config(), "base")
    assert set(inspect(pg).get_table_names()) <= {"alembic_version"}
    command.upgrade(_config(), "head")


def test_global_category_index_is_created_when_the_data_allows(pg):
    command.upgrade(_config(), "head")
    names = {ix["name"] for ix in inspect(pg).get_indexes("categories")}
    assert "uq_user_category_global_name" in names


def test_upgrade_skips_the_unique_index_when_duplicates_exist(pg):
    """Bestaande dubbele globale namen laten de deploy niet falen en worden niet stilletjes aangepast."""
    command.upgrade(_config(), "068")
    with pg.begin() as conn:
        conn.execute(text("INSERT INTO users (username, password_hash) VALUES ('u', 'x')"))
        for _ in range(2):
            conn.execute(text("INSERT INTO categories (user_id, name) SELECT id, 'Dubbel' FROM users"))
    command.upgrade(_config(), "069")
    names = {ix["name"] for ix in inspect(pg).get_indexes("categories")}
    assert "uq_user_category_global_name" not in names
    with pg.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM categories WHERE name = 'Dubbel'")).scalar() == 2

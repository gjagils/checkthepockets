"""Small PostgreSQL smoke check used after an Alembic upgrade."""

import os
import sys

from sqlalchemy import create_engine, inspect


REQUIRED_TABLES = {"users", "accounts", "transactions", "alembic_version"}


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        print("DATABASE_URL must point to PostgreSQL", file=sys.stderr)
        return 1
    inspector = inspect(create_engine(url, pool_pre_ping=True))
    tables = set(inspector.get_table_names())
    missing = REQUIRED_TABLES - tables
    if missing:
        print(f"Missing migrated tables: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1
    transaction_columns = {c["name"] for c in inspector.get_columns("transactions")}
    for column in ("account_id", "import_hash", "amount", "date"):
        if column not in transaction_columns:
            print(f"transactions.{column} is missing", file=sys.stderr)
            return 1
    unique_constraints = inspector.get_unique_constraints("transactions")
    indexes = inspector.get_indexes("transactions")
    has_import_identity = any(
        set(item.get("column_names") or ()) == {"import_hash"}
        for item in unique_constraints
    ) or any(
        set(item.get("column_names") or ()) == {"import_hash"}
        for item in indexes
        if item.get("unique") is True
    )
    if not has_import_identity:
        print("transactions.import_hash has no unique identity constraint/index", file=sys.stderr)
        return 1
    print(f"PostgreSQL schema OK: {len(tables)} tables, migrated constraints visible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

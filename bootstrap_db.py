"""
Run once per environment (UAT, then Prod) after setting DATABASE_URL in
.env to the SQL Server connection string: python bootstrap_db.py

Creates the TicketTracekr schema if it's missing and then creates every
table via SQLAlchemy's create_all(). Safe to run more than once -- it
only ever adds what's missing, never touches existing tables or data.

Does nothing useful against SQLite (there's no schema to create and
create_all() already runs automatically on app startup there) -- this
script exists specifically for the SQL Server deploy path.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from db import db, SQLSERVER_SCHEMA  # noqa: E402
from sqlalchemy import text  # noqa: E402


def main():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        print("DATABASE_URL is SQLite -- nothing to bootstrap, create_all() already "
              "runs automatically on every app start for SQLite. Set DATABASE_URL to "
              "the mssql+pyodbc:// connection string in .env first.")
        return

    with app.app_context():
        with db.engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM sys.schemas WHERE name = :name"),
                {"name": SQLSERVER_SCHEMA},
            ).fetchone()
            if exists is None:
                conn.execute(text(f"CREATE SCHEMA {SQLSERVER_SCHEMA}"))
                conn.commit()
                print(f"[OK] Schema '{SQLSERVER_SCHEMA}' created.")
            else:
                print(f"[OK] Schema '{SQLSERVER_SCHEMA}' already exists.")

        print("Creating tables...")
        db.create_all()
        print("[DONE] All tables created (or already existed).")

        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names(schema=SQLSERVER_SCHEMA)
        print(f"\n{SQLSERVER_SCHEMA} schema has {len(tables)} tables:")
        for t in sorted(tables):
            print(f"  - {t}")


if __name__ == "__main__":
    main()

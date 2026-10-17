# run once per env (UAT then prod) after setting DATABASE_URL in .env
# to the sql server conn string: python bootstrap_db.py
#
# creates the schema if missing + all tables via create_all(). safe to
# rerun, only adds what's missing. no-op on sqlite since create_all()
# already runs on app startup there.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from db import db, SQLSERVER_SCHEMA  # noqa: E402
from sqlalchemy import text  # noqa: E402

def main():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        print("sqlite - nothing to bootstrap, create_all() runs automatically. set DATABASE_URL to mssql+pyodbc:// first.")
        return

    with app.app_context():
        with db.engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM sys.schemas WHERE name = :name"), {"name": SQLSERVER_SCHEMA}).fetchone()
            if exists is None:
                conn.execute(text(f"CREATE SCHEMA {SQLSERVER_SCHEMA}"))
                conn.commit()
                print(f"[OK] schema '{SQLSERVER_SCHEMA}' created")
            else:
                print(f"[OK] schema '{SQLSERVER_SCHEMA}' already exists")

        print("creating tables...")
        db.create_all()
        print("[DONE] all tables created (or already existed)")

        insp = db.inspect(db.engine)
        tables = insp.get_table_names(schema=SQLSERVER_SCHEMA)
        print(f"\n{SQLSERVER_SCHEMA} schema has {len(tables)} tables:")
        for t in sorted(tables):
            print("  -", t)

if __name__=="__main__":
    main()

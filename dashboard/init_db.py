"""Create the schema and load the seed data into restaurant_db.

Run once (or whenever you want to reset the sample data):
    python dashboard/init_db.py
"""
from pathlib import Path

from db import get_conn

HERE = Path(__file__).parent


def run_sql_file(cur, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    # Strip -- line comments first (they may contain ';'), then split on ';'.
    sql = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    for statement in (s.strip() for s in sql.split(";")):
        if statement:
            cur.execute(statement)


def main() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        print("Applying schema.sql ...")
        run_sql_file(cur, HERE / "schema.sql")
        print("Applying seed.sql ...")
        run_sql_file(cur, HERE / "seed.sql")
        conn.commit()

    with get_conn() as conn, conn.cursor() as cur:
        for table in ("menu_items", "restaurant_tables", "bookings"):
            cur.execute(f"SELECT count(*) AS n FROM {table}")
            print(f"  {table}: {cur.fetchone()['n']} rows")

    print("Database initialized OK")


if __name__ == "__main__":
    main()

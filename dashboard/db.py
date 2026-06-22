"""Database connection helper for the admin dashboard."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

# Load the project's .env (one level up from this dashboard/ folder), no matter
# which directory the app is launched from.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add a line like this to your .env file:\n"
        "DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/restaurant_db"
    )


def get_conn():
    """Open a new PostgreSQL connection whose rows come back as dicts."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

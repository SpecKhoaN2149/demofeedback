"""SQLite database connection factory and initialization for Spectrum Feedback."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Database path configurable via environment variable
DB_PATH: str = os.environ.get("SUBMISSIONS_DB_PATH", "submissions.db")

# Path to schema.sql relative to this module
_SCHEMA_PATH: Path = Path(__file__).parent / "schema.sql"


def _ensure_db_dir() -> None:
    """Ensure the directory holding the SQLite file exists.

    When ``SUBMISSIONS_DB_PATH`` points at a mounted volume (e.g.
    ``/data/submissions.db`` in production), the parent directory may not exist
    yet on first boot — SQLite would then fail to open the file with
    "unable to open database file". Creating it up front makes startup robust
    regardless of whether the mount pre-creates the path.
    """
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a sqlite3 connection with WAL mode and foreign keys enabled.

    Usage:
        with get_connection() as conn:
            conn.execute("SELECT ...")
    """
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initialize the database by creating all tables defined in schema.sql.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    """
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.executescript(schema_sql)

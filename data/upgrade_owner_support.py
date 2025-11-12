#!/usr/bin/env python3
"""Upgrade script to enable course-owner management features."""

from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "teetimevn_dev.db"


def ensure_database() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_course_owner_table(conn: sqlite3.Connection) -> bool:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS course_owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, owner_id),
            FOREIGN KEY (course_id) REFERENCES golf_course(id) ON DELETE CASCADE,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    return True


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def main() -> int:
    conn = ensure_database()
    changed = False

    ensure_course_owner_table(conn)
    changed = True

    changed |= ensure_column(conn, "bookings", "check_in_at", "TIMESTAMP")
    changed |= ensure_column(conn, "bookings", "check_out_at", "TIMESTAMP")
    changed |= ensure_column(conn, "bookings", "checked_in_by", "TEXT")
    changed |= ensure_column(conn, "bookings", "checked_out_by", "TEXT")
    changed |= ensure_column(conn, "bookings", "no_show", "INTEGER NOT NULL DEFAULT 0")

    if changed:
        conn.commit()
        print("Owner upgrade complete.")
    else:
        print("Owner upgrade already applied.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

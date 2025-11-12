#!/usr/bin/env python3
"""Upgrade script to add flexible cancellation fields to bookings."""

import sqlite3
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "teetimevn_dev.db"

ADDITIONAL_COLUMNS = {
    "payment_status": "ALTER TABLE bookings ADD COLUMN payment_status VARCHAR(20) DEFAULT 'unpaid'",
    "payment_method": "ALTER TABLE bookings ADD COLUMN payment_method VARCHAR(50)",
    "paid_amount": "ALTER TABLE bookings ADD COLUMN paid_amount REAL DEFAULT 0",
    "refund_status": "ALTER TABLE bookings ADD COLUMN refund_status VARCHAR(20) DEFAULT 'not_applicable'",
    "refund_amount": "ALTER TABLE bookings ADD COLUMN refund_amount REAL DEFAULT 0",
    "credit_amount": "ALTER TABLE bookings ADD COLUMN credit_amount REAL DEFAULT 0",
    "cancellation_reason": "ALTER TABLE bookings ADD COLUMN cancellation_reason TEXT",
    "cancelled_at": "ALTER TABLE bookings ADD COLUMN cancelled_at TIMESTAMP",
    "last_rescheduled_at": "ALTER TABLE bookings ADD COLUMN last_rescheduled_at TIMESTAMP"
}

BACKFILL_STATEMENTS = [
    "UPDATE bookings SET payment_status = COALESCE(payment_status, 'unpaid')",
    "UPDATE bookings SET refund_status = COALESCE(refund_status, 'not_applicable')",
    "UPDATE bookings SET paid_amount = COALESCE(paid_amount, 0)",
    "UPDATE bookings SET refund_amount = COALESCE(refund_amount, 0)",
    "UPDATE bookings SET credit_amount = COALESCE(credit_amount, 0)"
]

def column_exists(cursor, column_name):
    cursor.execute("PRAGMA table_info(bookings)")
    return any(row[1] == column_name for row in cursor.fetchall())

def upgrade():
    if not DB_PATH.exists():
        print(f"Database file not found: {DB_PATH}")
        return False

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        print(f"Connected to database: {DB_PATH}")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bookings'")
        if not cursor.fetchone():
            print("Table 'bookings' does not exist. Run create_bookings_table.py first.")
            return False

        for column, statement in ADDITIONAL_COLUMNS.items():
            if column_exists(cursor, column):
                print(f"Column '{column}' already exists. Skipping.")
                continue
            print(f"Adding column '{column}'...")
            cursor.execute(statement)

        for statement in BACKFILL_STATEMENTS:
            print(f"Running backfill: {statement}")
            cursor.execute(statement)

        conn.commit()
        print("Upgrade completed successfully.")
        return True

    except sqlite3.Error as exc:
        if conn:
            conn.rollback()
        print(f"SQLite error: {exc}")
        return False
    finally:
        if conn:
            conn.close()
            print("Closed database connection.")

if __name__ == "__main__":
    print("Starting bookings table upgrade...")
    print("=" * 60)
    if upgrade():
        print("Done.")
    else:
        print("Upgrade failed.")

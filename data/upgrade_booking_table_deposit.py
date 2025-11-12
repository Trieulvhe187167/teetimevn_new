
"""Upgrade script to add deposit and payment gateway fields to bookings."""

import sqlite3
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "teetimevn_dev.db"

NEW_COLUMNS = {
    'deposit_amount': "ALTER TABLE bookings ADD COLUMN deposit_amount REAL DEFAULT 0",
    'balance_due': "ALTER TABLE bookings ADD COLUMN balance_due REAL DEFAULT 0",
    'payment_gateway': "ALTER TABLE bookings ADD COLUMN payment_gateway VARCHAR(50)",
    'payment_reference': "ALTER TABLE bookings ADD COLUMN payment_reference VARCHAR(64)",
    'payment_gateway_ref': "ALTER TABLE bookings ADD COLUMN payment_gateway_ref VARCHAR(64)",
    'payment_verified_at': "ALTER TABLE bookings ADD COLUMN payment_verified_at TIMESTAMP"
}


def column_exists(cursor, column_name: str) -> bool:
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

        for column, statement in NEW_COLUMNS.items():
            if column_exists(cursor, column):
                print(f"Column '{column}' already exists. Skipping.")
                continue
            print(f"Adding column '{column}'...")
            cursor.execute(statement)

        print('Backfilling balances where missing...')
        cursor.execute(
            """
            UPDATE bookings
            SET balance_due = CASE
                WHEN balance_due IS NULL OR balance_due = 0 THEN total_amount - COALESCE(paid_amount, 0)
                ELSE balance_due
            END,
                deposit_amount = COALESCE(deposit_amount, 0)
            """
        )

        conn.commit()
        print('Upgrade completed successfully.')
        return True

    except sqlite3.Error as exc:
        if conn:
            conn.rollback()
        print(f"SQLite error: {exc}")
        return False
    finally:
        if conn:
            conn.close()
            print('Closed database connection.')


if __name__ == '__main__':
    print('Starting bookings table deposit upgrade...')
    print('=' * 60)
    if upgrade():
        print('Done.')
    else:
        print('Upgrade failed.')

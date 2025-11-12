#!/usr/bin/env python3
"""
Script to create the bookings table in the SQLite database.
"""

import sqlite3
from pathlib import Path

# 1) Resolve project root and database path
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent  # data/ -> project root
DB_PATH = PROJECT_ROOT / "data" / "teetimevn_dev.db"

def create_bookings_table():
    """Create the bookings table and related indexes."""

    if not DB_PATH.exists():
        print(f"Database file not found: {DB_PATH}")
        return False

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        print(f"Connected to database: {DB_PATH}")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                play_date DATE NOT NULL,
                play_time TIME NOT NULL,
                players INTEGER NOT NULL DEFAULT 1,
                has_caddy BOOLEAN DEFAULT 0,
                has_cart BOOLEAN DEFAULT 0,
                has_rent_clubs BOOLEAN DEFAULT 0,
                green_fee REAL NOT NULL,
                services_fee REAL NOT NULL,
                insurance_fee REAL NOT NULL,
                total_amount REAL NOT NULL,
                payment_status VARCHAR(20) DEFAULT 'unpaid',
                payment_method VARCHAR(50),
                paid_amount REAL DEFAULT 0,
                refund_status VARCHAR(20) DEFAULT 'not_applicable',
                refund_amount REAL DEFAULT 0,
                credit_amount REAL DEFAULT 0,
                deposit_amount REAL DEFAULT 0,
                balance_due REAL DEFAULT 0,
                payment_gateway VARCHAR(50),
                payment_reference VARCHAR(64),
                payment_gateway_ref VARCHAR(64),
                payment_verified_at TIMESTAMP,
                status VARCHAR(20) DEFAULT 'pending',
                cancellation_reason TEXT,
                cancelled_at TIMESTAMP,
                last_rescheduled_at TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (course_id) REFERENCES golf_course(id)
            )
        """)
        print("Created bookings table (if not existing).")

        indexes = [
            ("idx_bookings_user_id", "bookings(user_id)"),
            ("idx_bookings_course_id", "bookings(course_id)"),
            ("idx_bookings_play_date", "bookings(play_date)"),
            ("idx_bookings_status", "bookings(status)")
        ]

        for name, definition in indexes:
            try:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {definition}")
                print(f"Ensured index {name} exists.")
            except sqlite3.Error as exc:
                print(f"Index {name} may already exist: {exc}")

        conn.commit()

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'bookings'
        """)
        if cursor.fetchone():
            print("\nBookings table structure:")
            cursor.execute("PRAGMA table_info(bookings)")
            for col in cursor.fetchall():
                name, col_type, not_null, default = col[1], col[2], col[3], col[4]
                nullability = "NOT NULL" if not_null else "NULL"
                default_clause = f"DEFAULT {default}" if default is not None else ""
                print(f"  {name:<22} {col_type:<15} {nullability:<8} {default_clause}")

        return True

    except sqlite3.Error as exc:
        print(f"SQLite error: {exc}")
        return False
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        return False
    finally:
        if conn:
            conn.close()
            print("\nClosed database connection.")

def check_existing_bookings():
    """Return the number of records currently stored in bookings."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bookings")
        count = cursor.fetchone()[0]
        if count:
            print(f"\nCurrent bookings count: {count}")
        else:
            print("\nBookings table is currently empty.")
        conn.close()
        return count
    except sqlite3.Error as exc:
        print(f"SQLite error: {exc}")
        return 0

if __name__ == "__main__":
    print("Starting bookings table creation...")
    print("=" * 60)

    if create_bookings_table():
        check_existing_bookings()
        print("\nDone. The bookings table is ready to use.")
    else:
        print("\nTable creation failed.")

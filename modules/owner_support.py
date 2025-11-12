# file: modules/owner_support.py

"""
Utility helpers shared by owner-facing features.

This module intentionally keeps its dependencies minimal so it can be imported
from both booking and owner blueprints without circular imports.
"""

from __future__ import annotations

from typing import Iterable, Sequence

SCHEMA_ENSURED = False

# Default services seeded automatically for every course when the services
# catalog is first initialised.
DEFAULT_SERVICE_DEFINITIONS = [
    {
        "code": "rent_clubs",
        "name": "Rental Clubs",
        "charge_type": "per_player",
        "price": 1_200_000,
        "is_required": 0,
        "sort_order": 1,
    },
    {
        "code": "caddy",
        "name": "Caddy",
        "charge_type": "per_player",
        "price": 500_000,
        "is_required": 0,
        "sort_order": 2,
    },
    {
        "code": "cart",
        "name": "Golf Cart",
        "charge_type": "per_player",
        "price": 700_000,
        "is_required": 0,
        "sort_order": 3,
    },
    {
        "code": "insurance",
        "name": "Insurance",
        "charge_type": "per_player",
        "price": 100_000,
        "is_required": 1,
        "sort_order": 4,
    },
]


def ensure_owner_schema(db) -> None:
    """
    Ensure supporting tables/columns for the owner area exist.

    The check is cached per interpreter process to avoid repeated PRAGMA calls.
    """

    global SCHEMA_ENSURED
    if SCHEMA_ENSURED:
        return

    schema_updated = False

    db.execute(
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
    schema_updated = True

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS course_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            charge_type TEXT NOT NULL DEFAULT 'per_player',
            price INTEGER NOT NULL DEFAULT 0,
            is_required INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, code),
            FOREIGN KEY (course_id) REFERENCES golf_course(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_course_services_course
            ON course_services(course_id)
        """
    )

    existing_services = db.execute(
        "SELECT COUNT(*) AS total FROM course_services"
    ).fetchone()
    if existing_services and existing_services["total"] == 0:
        course_ids = [
            row["id"] for row in db.execute("SELECT id FROM golf_course").fetchall()
        ]
        for course_id in course_ids:
            for definition in DEFAULT_SERVICE_DEFINITIONS:
                db.execute(
                    """
                    INSERT INTO course_services (
                        course_id, code, name, charge_type, price,
                        is_required, sort_order, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        course_id,
                        definition["code"],
                        definition["name"],
                        definition["charge_type"],
                        definition["price"],
                        definition["is_required"],
                        definition["sort_order"],
                    ),
                )
        schema_updated = True

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS course_blackouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            start_at TIMESTAMP NOT NULL,
            end_at TIMESTAMP NOT NULL,
            reason TEXT,
            type TEXT DEFAULT 'maintenance',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES golf_course(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_course_blackouts_range
            ON course_blackouts(course_id, start_at, end_at)
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS course_promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            discount_type TEXT NOT NULL DEFAULT 'percentage',
            discount_value REAL NOT NULL DEFAULT 0,
            start_at TIMESTAMP NOT NULL,
            end_at TIMESTAMP NOT NULL,
            days_of_week TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES golf_course(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_course_promotions_active
            ON course_promotions(course_id, active, start_at, end_at)
        """
    )

    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(bookings)").fetchall()
    }
    if "check_in_at" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN check_in_at TIMESTAMP")
        schema_updated = True
    if "check_out_at" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN check_out_at TIMESTAMP")
        schema_updated = True
    if "checked_in_by" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN checked_in_by TEXT")
        schema_updated = True
    if "checked_out_by" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN checked_out_by TEXT")
        schema_updated = True
    if "no_show" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN no_show INTEGER NOT NULL DEFAULT 0")
        schema_updated = True
    if "service_items_json" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN service_items_json TEXT")
        schema_updated = True
    if "promotion_id" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN promotion_id INTEGER")
        schema_updated = True
    if "promotion_snapshot" not in columns:
        db.execute("ALTER TABLE bookings ADD COLUMN promotion_snapshot TEXT")
        schema_updated = True

    if schema_updated:
        db.commit()

    SCHEMA_ENSURED = True


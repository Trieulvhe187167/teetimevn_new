"""
Utility script to bring the local SQLite database up-to-date with the
owner-portal schema requirements.

Run:
    python data/upgrade_owner_portal_schema.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Ensure project root is on sys.path so we can reuse the helper.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.owner_support import ensure_owner_schema  # noqa: E402

DEFAULT_DB_PATH = ROOT / "data" / "teetimevn_dev.db"


def upgrade(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create any missing owner tables/columns in the target database."""
    if not db_path.exists():
        raise SystemExit(f"Database file not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_owner_schema(conn)
    finally:
        conn.close()

    print(f"Owner portal schema ensured for {db_path}")


if __name__ == "__main__":
    upgrade()

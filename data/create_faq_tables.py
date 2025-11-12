from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'teetimevn_dev.db'

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS faq (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               slug TEXT UNIQUE,
               sort_order INTEGER DEFAULT 0
           )'''
    )

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS faq_i18n (
               faq_id INTEGER NOT NULL,
               lang   TEXT NOT NULL,
               question TEXT NOT NULL,
               answer   TEXT NOT NULL,
               PRIMARY KEY (faq_id, lang),
               FOREIGN KEY (faq_id) REFERENCES faq(id) ON DELETE CASCADE
           )'''
    )

    conn.commit()
    conn.close()
    print('FAQ tables ensured.')

if __name__ == '__main__':
    main()


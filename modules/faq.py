from pathlib import Path
import sqlite3
from flask import Blueprint, render_template, g, request


script_path = Path(__file__).resolve()
project_root = script_path.parent.parent
DB_PATH = project_root / "data" / "teetimevn_dev.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db:
        db.close()


def fetch_i18n(db, faq_id: int, lang: str):
    # Fallback: requested lang -> English -> Simplified Chinese
    for code in (lang, 'en', 'zh-CN'):
        row = db.execute(
            "SELECT question, answer FROM faq_i18n WHERE faq_id=? AND lang=?",
            (faq_id, code)
        ).fetchone()
        if row:
            return row
    return None


def create_bp():
    bp = Blueprint('faq', __name__, url_prefix='/<lang>/faq')

    @bp.before_app_request
    def before():
        # ensure connection
        get_db()

    @bp.teardown_app_request
    def after(exc):
        close_db()

    @bp.route('/')
    def faq_page(lang):
        db = get_db()
        rows = db.execute(
            "SELECT id, slug FROM faq ORDER BY sort_order, id"
        ).fetchall()

        faqs = []
        for r in rows:
            text = fetch_i18n(db, r['id'], lang)
            if not text:
                # skip if no text at all
                continue
            faqs.append({
                'slug': r['slug'],
                'question': text['question'],
                'answer': text['answer'],
            })

        return render_template('faq.html', lang=lang, faqs=faqs)

    return bp


faq_bp = create_bp()


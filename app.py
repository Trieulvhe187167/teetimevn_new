from flask import Flask, redirect, request, url_for, render_template, send_from_directory
from flask_babel import Babel
from flask_mail import Mail
from modules.courses import courses_bp, extract_city, COUNTRY_LABELS
from modules.admin import admin_bp
from modules.faq import faq_bp
from modules.booking import booking_bp
from modules.payments import payments_bp
from modules.auth import auth_bp
from modules.owner import owner_bp
import os
import sqlite3

# Khởi tạo Mail ở cấp module, để có thể import từ modules khác
mail = Mail()

SUPPORTED_URL_LANGS = ["zh-CN", "zh-TW", "en", "vi", "ja", "ko"]
DEFAULT_LANG = "en"

def url_to_locale(code: str) -> str:
    return code.replace("-", "_")

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')

    # ---------- Cấu hình Flask-Mail ----------
    # Ví dụ: nếu bạn dùng Gmail, cần set đúng biến môi trường:
    #   MAIL_USERNAME: địa chỉ Gmail hoặc App Password
    #   MAIL_PASSWORD: App Password
    app.config['MAIL_SERVER'] = "smtp.gmail.com"
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = "levantrieu170604@gmail.com"
    app.config['MAIL_PASSWORD'] = "jskfdqalznzuulhp"
    app.config['MAIL_DEFAULT_SENDER'] = "levantrieu170604@gmail.com"

    # Booking policy defaults
    app.config.setdefault('BOOKING_CANCEL_WINDOW_HOURS', 24)
    app.config.setdefault('BOOKING_RESCHEDULE_WINDOW_HOURS', 12)
    app.config.setdefault('BOOKING_SLOT_CAPACITY', 4)
    app.config.setdefault('BOOKING_ALERT_EMAIL', app.config['MAIL_DEFAULT_SENDER'])
    app.config.setdefault('BOOKING_DEPOSIT_PERCENT', int(os.environ.get('BOOKING_DEPOSIT_PERCENT', 20)))
    app.config.setdefault('VNPAY_TMN_CODE', os.environ.get('VNPAY_TMN_CODE', ''))
    app.config.setdefault('VNPAY_HASH_SECRET', os.environ.get('VNPAY_HASH_SECRET', ''))
    app.config.setdefault('VNPAY_PAYMENT_URL', os.environ.get('VNPAY_PAYMENT_URL', 'https://sandbox.vnpayment.vn/paymentv2/vpcpay.html'))
    app.config.setdefault('VNPAY_RETURN_URL', os.environ.get('VNPAY_RETURN_URL'))
    app.config.setdefault('VNPAY_IPN_URL', os.environ.get('VNPAY_IPN_URL'))



    app.config.setdefault('BANK_TRANSFER_ACCOUNT_NUMBER', os.environ.get('BANK_TRANSFER_ACCOUNT_NUMBER', '1024520080'))
    app.config.setdefault('BANK_TRANSFER_ACCOUNT_NAME', os.environ.get('BANK_TRANSFER_ACCOUNT_NAME', 'LE VAN TRIEU'))
    app.config.setdefault('BANK_TRANSFER_BANK_NAME', os.environ.get('BANK_TRANSFER_BANK_NAME', 'Vietcombank'))
    app.config.setdefault('BANK_TRANSFER_BANK_CODE', os.environ.get('BANK_TRANSFER_BANK_CODE', 'VCB'))
    app.config.setdefault('BANK_TRANSFER_QR_URL', os.environ.get('BANK_TRANSFER_QR_URL', ''))
    # Khởi tạo Mail với app
    mail.init_app(app)

    # ---------- Cấu hình Babel ----------
    app.config.update(
        BABEL_DEFAULT_LOCALE=url_to_locale(DEFAULT_LANG),
        BABEL_TRANSLATION_DIRECTORIES="translations"
    )

    @app.context_processor
    def inject_utils():
        parts = request.path.split("/", 2)
        current = parts[1] if len(parts) > 1 else DEFAULT_LANG
        if current not in SUPPORTED_URL_LANGS:
            current = DEFAULT_LANG

        def switch_lang(new_lang):
            p = request.path.split("/", 2)
            if len(p) > 1 and p[1] in SUPPORTED_URL_LANGS:
                p[1] = new_lang
            else:
                p.insert(1, new_lang)
            return "/".join(p)

        return dict(
            switch_lang=switch_lang,
            lang=current,
            supported_langs=SUPPORTED_URL_LANGS
        )

    def select_locale():
        parts = request.path.split("/", 2)
        prefix = parts[1] if len(parts) > 1 else DEFAULT_LANG
        if prefix not in SUPPORTED_URL_LANGS:
            prefix = DEFAULT_LANG
        return url_to_locale(prefix)

    Babel(app, locale_selector=select_locale)

    # Đăng ký blueprint
    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(booking_bp)
    app.register_blueprint(faq_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(owner_bp)

    @app.route("/")
    def root():
        best = request.accept_languages.best_match(SUPPORTED_URL_LANGS)
        lang = best if best in SUPPORTED_URL_LANGS else DEFAULT_LANG
        return redirect(f"/{lang}/")

    @app.route("/<lang>/")
    def index(lang):
        if lang not in SUPPORTED_URL_LANGS:
            lang = DEFAULT_LANG

        db_path = os.path.join(app.root_path, "data", "teetimevn_dev.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        seo = conn.execute(
            "SELECT * FROM static_page_i18n WHERE page_id = ? AND lang = ?",
            ('home', lang)
        ).fetchone()

        # Top-rated courses: compute average score and take top 6
        avg_expr = (
            "(ce.design_layout + ce.turf_maintenance + ce.facilities_services + "
            "ce.landscape_environment + ce.playability_access) / 5.0"
        )
        top_rows = conn.execute(
            f"""
            SELECT gc.id, gc.slug, ROUND(AVG({avg_expr}), 1) AS avg_rating
            FROM golf_course gc
            JOIN course_evaluation ce ON gc.id = ce.course_id
            GROUP BY gc.id, gc.slug
            ORDER BY avg_rating DESC
            LIMIT 6
            """
        ).fetchall()

        courses = []
        for r in top_rows:
            text = conn.execute(
                "SELECT name, address FROM golf_course_i18n WHERE course_id = ? AND lang = ?",
                (r['id'], lang)
            ).fetchone()
            if text:
                courses.append({
                    'slug': r['slug'],
                    'name': text['name'],
                    'address': text['address'],
                    'avg_rating': r['avg_rating']
                })

        conn.close()
        return render_template(
            "index.html",
            lang=lang,
            seo=seo,
            courses=courses,
            banner=True
        )

    @app.route("/sitemap.xml")
    def sitemap():
        db_path = os.path.join(app.root_path, "data", "teetimevn_dev.db")
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT slug FROM golf_course").fetchall()
        conn.close()

        slugs = [row[0] for row in rows]
        base = request.url_root.rstrip('/')
        urls = []

        for slug in slugs:
            for lang in SUPPORTED_URL_LANGS:
                urls.append((lang, f"{base}/{lang}/courses/{slug}/"))

        return render_template(
            "sitemap.xml",
            urls=urls,
            DEFAULT_LANG=DEFAULT_LANG,
            supported_langs=SUPPORTED_URL_LANGS
        ), 200, {'Content-Type': 'application/xml'}

    @app.route("/robots.txt")
    def robots():
        return send_from_directory(app.static_folder, "robots.txt")

    @app.route("/debug-seo/<lang>")
    def debug_seo(lang):
        if lang not in SUPPORTED_URL_LANGS:
            return "⛔ Unsupported language", 400

        db_path = os.path.join(app.root_path, "data", "teetimevn_dev.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            "SELECT * FROM static_page_i18n WHERE page_id = ? AND lang = ?",
            ("home", lang)
        ).fetchone()
        conn.close()

        if not row:
            return f"⚠️ No SEO record found for lang = '{lang}'"

        return f"""
        <h1>SEO for page_id = 'home' ({lang})</h1>
        <ul>
          <li><strong>Title:</strong> {row['title']}</li>
          <li><strong>Description:</strong> {row['description']}</li>
          <li><strong>Keywords:</strong> {row['keywords']}</li>
        </ul>
        """

    return app

if __name__ == "__main__":
    create_app().run(debug=True)


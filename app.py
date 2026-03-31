"""
app.py — RecrutAI SaaS — Flask Application
==========================================
Usage:
  Local dev:  python app.py
  Production: gunicorn app:app --workers 2 --threads 4 --timeout 120

Environment variables (required):
  RESUMEPARSER_API_KEY   — resumeparser.app API key
  SECRET_KEY             — Flask secret key (random string)
  PADDLE_VENDOR_ID       — Paddle vendor ID
  PADDLE_PRODUCT_ID      — Paddle product/price ID
  PADDLE_WEBHOOK_SECRET  — Paddle webhook secret (Billing) or public key (Classic)
  DATABASE_URL           — SQLite by default; set to postgres:// for production
"""

import os
from flask import Flask, redirect, url_for
from flask_login import LoginManager

from models import db, User
from auth import auth_bp
from dashboard import dash_bp
from payment import payment_bp



# ─── APP FACTORY ──────────────────────────────────────────────────────────────

def create_app() -> Flask:
    app = Flask(__name__)

    # ── Config ────────────────────────────────────────────────────────────────
    app.config["SECRET_KEY"]            = os.environ.get("SECRET_KEY", "change-me-in-production-please")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///recrut_saas.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # CV analysis API
    app.config["RESUMEPARSER_API_KEY"]  = os.environ.get("RESUMEPARSER_API_KEY", "")

    # Paddle
    app.config["PADDLE_VENDOR_ID"]      = os.environ.get("PADDLE_VENDOR_ID", "")
    app.config["PADDLE_PRODUCT_ID"]     = os.environ.get("PADDLE_PRODUCT_ID", "")
    app.config["PADDLE_WEBHOOK_SECRET"] = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
    app.config["PADDLE_PUBLIC_KEY"]     = os.environ.get("PADDLE_PUBLIC_KEY", "")  # Classic only
    app.config["PADDLE_ENV"]            = os.environ.get("PADDLE_ENV", "sandbox")  # sandbox | production

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view     = "auth.login"
    login_manager.login_message  = "Connectez-vous pour continuer."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(payment_bp)

    # ── Root redirect ─────────────────────────────────────────────────────────
    @app.route("/")
    def root():
        return redirect(url_for("dashboard.index"))

    # ── Create DB tables ──────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()

    return app


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

app = create_app()

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"\n{'='*52}\n  🎯 RecrutAI SaaS\n  📍 http://localhost:{port}\n{'='*52}\n")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)

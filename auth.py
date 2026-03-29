"""
auth.py — Authentication blueprint (register / login / logout)
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
import re

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))

def _valid_password(pw: str) -> bool:
    return len(pw) >= 8


# ─── REGISTER ─────────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        # Validation
        if not _valid_email(email):
            flash("Adresse email invalide.", "error")
            return render_template("auth/register.html")

        if not _valid_password(password):
            flash("Mot de passe trop court (8 caractères min).", "error")
            return render_template("auth/register.html")

        if password != confirm:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template("auth/register.html")

        # Anti-abuse: one account per email
        if User.query.filter_by(email=email).first():
            flash("Un compte existe déjà avec cet email.", "error")
            return render_template("auth/register.html")

        # Create user — trial starts automatically (see model defaults)
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        flash(f"Bienvenue ! Votre essai Pro gratuit de 5 jours est activé. 🎉", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html")


# ─── LOGIN ────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("Email ou mot de passe incorrect.", "error")
            return render_template("auth/login.html")

        login_user(user, remember=remember)
        next_page = request.args.get("next")
        return redirect(next_page or url_for("dashboard.index"))

    return render_template("auth/login.html")


# ─── LOGOUT ───────────────────────────────────────────────────────────────────

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Déconnecté avec succès.", "info")
    return redirect(url_for("auth.login"))

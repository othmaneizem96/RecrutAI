"""
payment.py — Paddle payment blueprint
Handles: checkout success, webhook verification, plan upgrade
"""

import hashlib
import hmac
import json
import os
from datetime import datetime

from flask import (Blueprint, request, jsonify, redirect,
                   url_for, flash, current_app)
from flask_login import login_required, current_user

from models import db, User, Transaction

payment_bp = Blueprint("payment", __name__, url_prefix="/payment")


# ─── SUCCESS REDIRECT (after Paddle checkout) ─────────────────────────────────

@payment_bp.route("/success")
@login_required
def success():
    """
    Paddle redirects here after a successful purchase.
    NOTE: Do NOT upgrade the user here — use the webhook below.
    This page is just a "thank you" redirect.
    """
    flash("Paiement reçu ! Votre plan Pro est en cours d'activation.", "success")
    return redirect(url_for("dashboard.index"))


# ─── PADDLE WEBHOOK ───────────────────────────────────────────────────────────

@payment_bp.route("/webhook", methods=["POST"])
def paddle_webhook():
    """
    Paddle sends POST webhooks for events:
    - payment_completed  → upgrade user to Pro
    - subscription_cancelled → (optional) downgrade
    - refund             → (optional) downgrade

    Paddle Classic uses form data + p_signature for verification.
    Paddle Billing uses JSON body + Paddle-Signature header.

    This implementation supports BOTH formats.
    """
    content_type = request.content_type or ""

    # ── Paddle Classic (form data) ────────────────────────────────────────────
    if "application/x-www-form-urlencoded" in content_type:
        data = request.form.to_dict()
        if not _verify_paddle_classic(data):
            current_app.logger.warning("Paddle Classic: signature invalide")
            return jsonify({"error": "Invalid signature"}), 400
        return _handle_classic_event(data)

    # ── Paddle Billing (JSON) ──────────────────────────────────────────────────
    else:
        payload   = request.get_data(as_text=True)
        signature = request.headers.get("Paddle-Signature", "")
        if not _verify_paddle_billing(payload, signature):
            current_app.logger.warning("Paddle Billing: signature invalide")
            return jsonify({"error": "Invalid signature"}), 400
        data = json.loads(payload)
        return _handle_billing_event(data)


# ─── PADDLE CLASSIC HANDLER ───────────────────────────────────────────────────

def _verify_paddle_classic(data: dict) -> bool:
    """
    Verify Paddle Classic webhook signature.
    https://developer.paddle.com/classic/api-reference/ZG9jOjI1MzU0MDI1-verifying-webhooks
    """
    public_key = current_app.config.get("PADDLE_PUBLIC_KEY", "")
    if not public_key:
        current_app.logger.warning("PADDLE_PUBLIC_KEY not set — skipping verification (DEV only)")
        return True   # Remove this in production!

    import base64
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA1

    try:
        signature = base64.b64decode(data.pop("p_signature", ""))
        sorted_data = "&".join(f"{k}={v}" for k, v in sorted(data.items()))
        key  = RSA.import_key(public_key)
        h    = SHA1.new(sorted_data.encode("utf-8"))
        pkcs1_15.new(key).verify(h, signature)
        return True
    except Exception as e:
        current_app.logger.error(f"Paddle Classic verify error: {e}")
        return False


def _handle_classic_event(data: dict):
    alert = data.get("alert_name", "")

    if alert == "payment_succeeded":
        order_id  = data.get("order_id", "")
        passthrough = data.get("passthrough", "{}")
        try:
            meta = json.loads(passthrough)
        except Exception:
            meta = {}

        user_id  = meta.get("user_id")
        amount   = float(data.get("sale_gross", 9.99))
        currency = data.get("currency", "USD")

        _upgrade_user(user_id, order_id, amount, currency)

    return jsonify({"status": "ok"}), 200


# ─── PADDLE BILLING HANDLER ───────────────────────────────────────────────────

def _verify_paddle_billing(payload: str, signature: str) -> bool:
    """
    Verify Paddle Billing webhook signature.
    https://developer.paddle.com/webhooks/overview
    Format: ts=timestamp;h1=signature
    """
    secret = current_app.config.get("PADDLE_WEBHOOK_SECRET", "")
    if not secret:
        current_app.logger.warning("PADDLE_WEBHOOK_SECRET not set — skipping (DEV only)")
        return True   # Remove in production!

    try:
        parts = dict(p.split("=", 1) for p in signature.split(";"))
        ts    = parts.get("ts", "")
        h1    = parts.get("h1", "")
        msg   = f"{ts}:{payload}"
        expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, h1)
    except Exception as e:
        current_app.logger.error(f"Paddle Billing verify error: {e}")
        return False


def _handle_billing_event(data: dict):
    event_type = data.get("event_type", "")

    if event_type in ("transaction.completed", "subscription.activated"):
        txn      = data.get("data", {})
        order_id = txn.get("id", "")
        custom   = txn.get("custom_data") or {}
        user_id  = custom.get("user_id")
        amount   = float(txn.get("details", {}).get("totals", {}).get("grand_total", 9.99)) / 100
        currency = txn.get("currency_code", "USD")
        _upgrade_user(user_id, order_id, amount, currency)

    return jsonify({"status": "ok"}), 200


# ─── CORE UPGRADE LOGIC ───────────────────────────────────────────────────────

def _upgrade_user(user_id, order_id: str, amount: float, currency: str):
    """Upgrade user to Pro and record transaction."""
    if not user_id:
        current_app.logger.error("Paddle webhook: user_id manquant dans passthrough")
        return

    user = User.query.get(int(user_id))
    if not user:
        current_app.logger.error(f"Paddle webhook: user {user_id} introuvable")
        return

    # Idempotency: skip if already processed
    if order_id and Transaction.query.filter_by(paddle_order_id=order_id).first():
        current_app.logger.info(f"Paddle webhook: order {order_id} déjà traité")
        return

    # Upgrade
    user.upgrade_to_pro()

    # Record transaction
    txn = Transaction(
        user_id         = user.id,
        paddle_order_id = order_id,
        amount          = amount,
        currency        = currency,
        plan            = "pro",
        status          = "completed",
    )
    db.session.add(txn)
    db.session.commit()
    current_app.logger.info(f"✅ User {user.email} upgraded to Pro (order {order_id})")


# ─── MANUAL UPGRADE (DEV / TEST ONLY) ────────────────────────────────────────

@payment_bp.route("/dev/upgrade")
@login_required
def dev_upgrade():
    """
    DEV-ONLY: manually upgrade current user to Pro.
    Remove this route in production!
    """
    if not current_app.config.get("DEBUG"):
        return jsonify({"error": "Not available in production"}), 403

    current_user.upgrade_to_pro()
    txn = Transaction(user_id=current_user.id, paddle_order_id=f"DEV-{current_user.id}",
                      amount=0.0, plan="pro", status="dev")
    db.session.add(txn); db.session.commit()
    flash("✅ Plan Pro activé (mode dev).", "success")
    return redirect(url_for("dashboard.index"))

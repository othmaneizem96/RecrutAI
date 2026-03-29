"""
models.py — Database models
"""

from datetime import datetime, date, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

PLAN_LIMITS = {
    "free":  30,
    "pro":   50,
    "trial": 50,   # Trial = Pro limits
}
TRIAL_DAYS = 5


# ─── USER MODEL ───────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id               = db.Column(db.Integer, primary_key=True)
    email            = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash    = db.Column(db.String(256), nullable=False)

    # Plan
    plan             = db.Column(db.String(20), default="free")   # free | pro

    # Trial
    is_trial_active  = db.Column(db.Boolean, default=True)
    trial_start_date = db.Column(db.Date, default=date.today)

    # Usage
    daily_usage_count = db.Column(db.Integer, default=0)
    last_reset_date   = db.Column(db.Date, default=date.today)

    # Meta
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    transactions     = db.relationship("Transaction", backref="user", lazy=True)

    # ── Password ──────────────────────────────────────────────────────────────

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ── Trial logic ───────────────────────────────────────────────────────────

    @property
    def trial_days_left(self) -> int:
        if not self.is_trial_active or not self.trial_start_date:
            return 0
        elapsed = (date.today() - self.trial_start_date).days
        return max(0, TRIAL_DAYS - elapsed)

    def check_and_expire_trial(self):
        """Call before any plan check — auto-expire trial after 5 days."""
        if self.is_trial_active and self.trial_days_left == 0:
            self.is_trial_active = False
            db.session.commit()

    # ── Effective plan ────────────────────────────────────────────────────────

    @property
    def effective_plan(self) -> str:
        """Returns 'trial', 'pro', or 'free' based on current state."""
        self.check_and_expire_trial()
        if self.is_trial_active:
            return "trial"
        return self.plan   # 'pro' or 'free'

    @property
    def daily_limit(self) -> int:
        return PLAN_LIMITS.get(self.effective_plan, 30)

    @property
    def plan_badge(self) -> str:
        p = self.effective_plan
        return {"trial": "Trial", "pro": "Pro", "free": "Free"}[p]

    # ── Usage ─────────────────────────────────────────────────────────────────

    def reset_daily_usage_if_needed(self):
        """Reset counter if last reset was before today."""
        today = date.today()
        if self.last_reset_date != today:
            self.daily_usage_count = 0
            self.last_reset_date   = today
            db.session.commit()

    @property
    def usage_remaining(self) -> int:
        return max(0, self.daily_limit - self.daily_usage_count)

    @property
    def usage_percent(self) -> int:
        if self.daily_limit == 0:
            return 100
        return min(100, int(self.daily_usage_count / self.daily_limit * 100))

    def can_analyze(self, count: int = 1) -> bool:
        self.reset_daily_usage_if_needed()
        return (self.daily_usage_count + count) <= self.daily_limit

    def increment_usage(self, count: int = 1):
        self.reset_daily_usage_if_needed()
        self.daily_usage_count += count
        db.session.commit()

    # ── Upgrade ───────────────────────────────────────────────────────────────

    def upgrade_to_pro(self):
        self.plan            = "pro"
        self.is_trial_active = False   # trial superseded by real Pro
        db.session.commit()

    # ── Anti-abuse: already had trial? ────────────────────────────────────────

    @staticmethod
    def email_already_used_trial(email: str) -> bool:
        """Basic check: one trial per email."""
        u = User.query.filter_by(email=email).first()
        return u is not None

    def __repr__(self):
        return f"<User {self.email} plan={self.effective_plan}>"


# ─── TRANSACTION MODEL ────────────────────────────────────────────────────────

class Transaction(db.Model):
    __tablename__ = "transactions"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    paddle_order_id = db.Column(db.String(100), unique=True)
    amount          = db.Column(db.Float, nullable=False)      # e.g. 9.99
    currency        = db.Column(db.String(10), default="USD")
    plan            = db.Column(db.String(20), default="pro")
    status          = db.Column(db.String(20), default="completed")  # completed | refunded
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Transaction user={self.user_id} ${self.amount}>"

from datetime import datetime, timezone, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

# Indian Standard Time (IST: UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_time():
    """Returns current Indian Standard Time (IST) as naive datetime for local database storage."""
    return datetime.now(IST).replace(tzinfo=None)

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    transaction_pin = db.Column(db.String(10), default="1234")
    credit_score = db.Column(db.Integer, default=760)  # CIBIL Credit Score (300 - 900)
    monthly_income = db.Column(db.Float, default=75000.0)  # Net monthly verifiable income in INR
    role = db.Column(db.String(20), default="customer")  # 'customer', 'admin'
    created_at = db.Column(db.DateTime, default=get_ist_time)

    # Relationships
    accounts = db.relationship('Account', backref='owner', lazy=True, cascade="all, delete-orphan")
    loans = db.relationship('Loan', backref='borrower', lazy=True, cascade="all, delete-orphan")
    savings_goals = db.relationship('SavingsGoal', backref='user', lazy=True, cascade="all, delete-orphan")
    cards = db.relationship('VirtualCard', backref='cardholder', lazy=True, cascade="all, delete-orphan")
    beneficiaries = db.relationship('Beneficiary', backref='owner', lazy=True, cascade="all, delete-orphan")
    activity_logs = db.relationship('ActivityLog', backref='user', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def primary_account(self):
        for acc in self.accounts:
            if acc.account_type == 'checking' and acc.status == 'active':
                return acc
        return self.accounts[0] if self.accounts else None

    @property
    def total_balance(self):
        return sum(acc.balance for acc in self.accounts if acc.status == 'active')

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'phone': self.phone,
            'total_balance': self.total_balance
        }


class Account(db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    account_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    account_type = db.Column(db.String(30), default="checking")  # 'checking', 'savings'
    balance = db.Column(db.Float, default=0.0, nullable=False)
    currency = db.Column(db.String(5), default="INR")
    status = db.Column(db.String(20), default="active")  # 'active', 'dormant', 'closed'
    interest_rate = db.Column(db.Float, nullable=True, default=None)
    last_interest_accrual_date = db.Column(db.String(10), nullable=True)  # YYYY-MM-DD
    total_interest_earned = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=get_ist_time)

    @property
    def effective_interest_rate(self):
        if self.interest_rate is not None and self.interest_rate > 0:
            return self.interest_rate
        defaults = {'savings': 6.5, 'fixed_deposit': 7.25, 'business': 4.0, 'checking': 3.5}
        return defaults.get(self.account_type, 3.5)

    @property
    def formatted_number(self):
        # Format as XXXX-XXXX-XX or neat groups
        raw = self.account_number.replace("-", "")
        if len(raw) >= 10:
            return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
        return self.account_number


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: f"TXN-{uuid.uuid4().hex[:8].upper()}")
    source_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    dest_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)  # 'deposit', 'withdraw', 'transfer', 'loan_disbursement', 'loan_payment', 'interest_credit', 'vault_deposit', 'vault_withdraw'
    category = db.Column(db.String(50), default="General")  # 'Income', 'Transfer', 'Shopping', 'Bills', 'Loan', 'Interest Payout', 'Loan Auto-Debit'
    description = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="completed")  # 'completed', 'pending', 'failed'
    timestamp = db.Column(db.DateTime, default=get_ist_time, index=True)

    source_account = db.relationship('Account', foreign_keys=[source_account_id], backref='outgoing_transactions')
    dest_account = db.relationship('Account', foreign_keys=[dest_account_id], backref='incoming_transactions')


class Loan(db.Model):
    __tablename__ = 'loans'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    loan_reference = db.Column(db.String(36), unique=True, nullable=False, default=lambda: f"LN-{uuid.uuid4().hex[:6].upper()}")
    amount = db.Column(db.Float, nullable=False)
    interest_rate = db.Column(db.Float, nullable=False)  # e.g., 7.5 for 7.5% per annum
    term_months = db.Column(db.Integer, nullable=False)
    monthly_emi = db.Column(db.Float, nullable=False)
    total_payable = db.Column(db.Float, nullable=False)
    amount_paid = db.Column(db.Float, default=0.0)
    category = db.Column(db.String(50), default="personal")  # 'home', 'auto', 'business', 'education', 'personal'
    credit_score_at_application = db.Column(db.Integer, nullable=True)  # CIBIL score when evaluated
    monthly_income = db.Column(db.Float, nullable=True)  # Declared income
    max_eligible_amount = db.Column(db.Float, nullable=True)  # Maximum borrowing power calculated
    last_emi_deducted_date = db.Column(db.String(10), nullable=True)  # YYYY-MM-DD
    next_emi_due_date = db.Column(db.String(10), nullable=True)  # YYYY-MM-DD
    auto_debit_enabled = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default="active")  # 'pending', 'active', 'completed', 'rejected'
    purpose = db.Column(db.String(150), nullable=False)
    applied_at = db.Column(db.DateTime, default=get_ist_time)
    approved_at = db.Column(db.DateTime, default=get_ist_time)

    @property
    def remaining_amount(self):
        return max(0.0, self.total_payable - self.amount_paid)

    @property
    def progress_percentage(self):
        if self.total_payable <= 0:
            return 100.0
        return min(100.0, round((self.amount_paid / self.total_payable) * 100, 1))


class SavingsGoal(db.Model):
    __tablename__ = 'savings_goals'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    target_amount = db.Column(db.Float, nullable=False)
    current_amount = db.Column(db.Float, default=0.0)
    color = db.Column(db.String(20), default="#10B981")  # Emerald accent
    icon = db.Column(db.String(30), default="target")
    deadline = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=get_ist_time)

    @property
    def progress_percentage(self):
        if self.target_amount <= 0:
            return 100.0
        return min(100.0, round((self.current_amount / self.target_amount) * 100, 1))


class VirtualCard(db.Model):
    __tablename__ = 'virtual_cards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    card_number = db.Column(db.String(19), nullable=False)  # formatted 16 digits
    cardholder_name = db.Column(db.String(100), nullable=False)
    expiry_date = db.Column(db.String(7), nullable=False)  # MM/YY
    cvv = db.Column(db.String(4), nullable=False)
    card_type = db.Column(db.String(30), default="Visa Platinum")
    status = db.Column(db.String(20), default="active")  # 'active', 'frozen'
    daily_limit = db.Column(db.Float, default=2500.0)
    current_spent = db.Column(db.Float, default=340.0)
    created_at = db.Column(db.DateTime, default=get_ist_time)


class Beneficiary(db.Model):
    __tablename__ = 'beneficiaries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    account_number = db.Column(db.String(20), nullable=False)
    bank_name = db.Column(db.String(100), default="NeoBank")
    nickname = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=get_ist_time)


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(50), default="127.0.0.1")
    timestamp = db.Column(db.DateTime, default=get_ist_time)


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=get_ist_time)


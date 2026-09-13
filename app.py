import os
import csv
import io
import random
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response

import threading
import time
import uuid

from dotenv import load_dotenv
from models import db, User, Account, Transaction, Loan, SavingsGoal, VirtualCard, Beneficiary, ActivityLog, SystemSetting, get_ist_time
from supabase_client import get_database_uri, get_engine_options, get_supabase_client

load_dotenv()

def execute_daily_banking_cycle(target_date_str=None, force=False, user_id=None):
    """
    Autonomous Daily Banking Engine:
    1. Runs automatically every 12:00 AM midnight in the background (no browser or user interaction required).
    2. Calculates and credits daily interest to all interest-bearing accounts (Savings @ 6.5%, FD @ 7.25%, Checking @ 3.5%, Business @ 4.0%).
       Formula: daily_interest = round(balance * (interest_rate / 100.0) / 365.0, 2)
       Creates an 'interest_credit' transaction under category 'Interest Payout'.
    3. Automatically deducts monthly EMI for all active loans with auto_debit_enabled=True.
       Debits borrower's liquid checking/savings account, credits loan.amount_paid,
       marks loan as 'completed' once fully repaid,
       and logs a 'loan_payment' transaction under category 'Loan Auto-Debit'.
    4. Updates SystemSetting 'last_daily_batch_date' to guarantee exactly-once execution per calendar day.
    """
    today_str = target_date_str or get_ist_time().strftime('%Y-%m-%d')
    
    setting = SystemSetting.query.filter_by(key='last_daily_batch_date').first()
    if not setting:
        setting = SystemSetting(key='last_daily_batch_date', value=None)
        db.session.add(setting)
        db.session.flush()

    if not force and setting.value == today_str:
        return {
            'success': True,
            'status': 'already_processed',
            'date': today_str,
            'message': f'12:00 AM Midnight Banking Cycle for {today_str} has already completed.',
            'accounts_credited': 0,
            'total_interest_credited': 0.0,
            'loans_debited': 0,
            'total_emi_debited': 0.0,
            'failed_debits': 0,
            'user_stats': {
                'accounts_credited': 0,
                'interest_credited': 0.0,
                'loans_debited': 0,
                'emi_debited': 0.0
            } if user_id is not None else None
        }

    # 1. Autonomous Daily Interest Accrual
    accounts = Account.query.filter(Account.status == 'active', Account.balance > 0).all()
    accounts_credited = 0
    total_interest = 0.0
    user_accounts_credited = 0
    user_interest = 0.0

    for acc in accounts:
        # Check if interest already accrued today (unless force=True)
        if acc.last_interest_accrual_date == today_str and not force:
            continue

        rate = acc.effective_interest_rate
        if rate and rate > 0:
            # Daily interest formula: balance * (rate% / 365)
            daily_amt = round(acc.balance * (rate / 100.0) / 365.0, 2)
            if daily_amt < 0.01 and acc.balance >= 10.0:
                daily_amt = 0.01

            if daily_amt > 0:
                old_balance = acc.balance
                acc.balance = round(acc.balance + daily_amt, 2)
                acc.total_interest_earned = round((acc.total_interest_earned or 0.0) + daily_amt, 2)
                acc.last_interest_accrual_date = today_str

                txn = Transaction(
                    reference_id=f"INT-{uuid.uuid4().hex[:8].upper()}",
                    dest_account_id=acc.id,
                    source_account_id=None,
                    amount=daily_amt,
                    transaction_type='interest_credit',
                    category='Interest Payout',
                    description=f"Daily Interest Payout @ {rate:.2f}% p.a. on balance ₹{old_balance:,.2f}",
                    status='completed',
                    timestamp=get_ist_time()
                )
                db.session.add(txn)
                accounts_credited += 1
                total_interest += daily_amt

                if user_id is not None and acc.user_id == user_id:
                    user_accounts_credited += 1
                    user_interest += daily_amt

    # 2. Autonomous Loan EMI Auto-Debit
    active_loans = Loan.query.filter(Loan.status.in_(['active', 'approved'])).all()
    loans_debited = 0
    total_emi = 0.0
    failed_debits = 0
    user_loans_debited = 0
    user_emi = 0.0

    for loan in active_loans:
        if not getattr(loan, 'auto_debit_enabled', True):
            continue

        # Prevent duplicate deduction on the same day unless forced
        if loan.last_emi_deducted_date == today_str and not force:
            continue

        remaining = loan.remaining_amount
        if remaining <= 0.01:
            loan.status = 'completed'
            continue

        # Calculate exact per-day loan interest based on actual remaining loan balance
        loan_balance = loan.remaining_amount

        # Daily interest formula: loan_balance * (rate% / 365)
        daily_interest = round(loan_balance * (loan.interest_rate / 100.0) / 365.0, 2)
        if daily_interest < 0.01 and remaining >= 1.0:
            daily_interest = 0.01

        debit_amt = round(min(daily_interest, remaining), 2)
        if debit_amt <= 0:
            continue

        # Look up borrower's active liquid accounts
        user_accounts = Account.query.filter_by(user_id=loan.user_id, status='active').all()
        debit_acc = None

        # Hierarchy: Checking first, then savings, then any account with enough balance
        for acc in user_accounts:
            if acc.account_type == 'checking' and acc.balance >= debit_amt:
                debit_acc = acc
                break
        if not debit_acc:
            for acc in user_accounts:
                if acc.account_type == 'savings' and acc.balance >= debit_amt:
                    debit_acc = acc
                    break
        if not debit_acc:
            for acc in user_accounts:
                if acc.balance >= debit_amt:
                    debit_acc = acc
                    break

        if debit_acc:
            debit_acc.balance = round(debit_acc.balance - debit_amt, 2)
            loan.amount_paid = round((loan.amount_paid or 0.0) + debit_amt, 2)
            loan.last_emi_deducted_date = today_str

            if loan.amount_paid >= (loan.total_payable - 0.01):
                loan.status = 'completed'
                loan.monthly_emi = 0.0
            else:
                # Recalculate Monthly EMI based on updated balance and remaining tenure
                target_tenure = max(1, round((loan.total_payable - loan.amount_paid) / loan.monthly_emi)) if (loan.monthly_emi and loan.monthly_emi > 0) else getattr(loan, 'term_months', 12)
                r = (loan.interest_rate / 100.0) / 12.0
                old_emi = loan.monthly_emi
                if r > 0 and target_tenure > 0:
                    pv_principal = old_emi * (1 - (1 + r) ** (-target_tenure)) / r
                    new_principal = max(0.0, pv_principal - debit_amt)
                    if new_principal > 0:
                        new_emi = (new_principal * r * ((1 + r) ** target_tenure)) / (((1 + r) ** target_tenure) - 1)
                    else:
                        new_emi = 0.0
                else:
                    new_principal = max(0.0, loan.remaining_amount)
                    new_emi = new_principal / target_tenure if target_tenure > 0 else 0.0

                new_emi_rounded = round(new_emi, 2)
                # Ensure monthly EMI is updated (even minor update of at least 1 paisa if rounding matches)
                if new_emi_rounded >= old_emi and debit_amt > 0 and old_emi > 0.01:
                    new_emi_rounded = round(old_emi - 0.01, 2)

                loan.monthly_emi = new_emi_rounded

            txn = Transaction(
                reference_id=f"INT-LN-{uuid.uuid4().hex[:8].upper()}",
                source_account_id=debit_acc.id,
                dest_account_id=None,
                amount=debit_amt,
                transaction_type='loan_payment',
                category='Loan Auto-Debit',
                description=f"Daily Loan Interest @ {loan.interest_rate:.2f}% p.a. for Loan {loan.loan_reference} ({loan.category.capitalize()})",
                status='completed',
                timestamp=get_ist_time()
            )
            db.session.add(txn)

            log = ActivityLog(
                user_id=loan.user_id,
                action="Loan Auto-Debit",
                details=f"Daily Loan Interest ₹{debit_amt:,.2f} deducted for Loan {loan.loan_reference} from {debit_acc.account_type.capitalize()} A/C. Monthly EMI: ₹{loan.monthly_emi:,.2f}",
                ip_address="127.0.0.1"
            )
            db.session.add(log)

            loans_debited += 1
            total_emi += debit_amt

            if user_id is not None and loan.user_id == user_id:
                user_loans_debited += 1
                user_emi += debit_amt
        else:
            failed_debits += 1
            log = ActivityLog(
                user_id=loan.user_id,
                action="Auto-Debit Insufficient Balance",
                details=f"Daily Loan Interest of ₹{debit_amt:,.2f} skipped due to insufficient account balance for Loan {loan.loan_reference}",
                ip_address="127.0.0.1"
            )
            db.session.add(log)

    setting.value = today_str
    setting.updated_at = get_ist_time()
    db.session.commit()

    return {
        'success': True,
        'status': 'executed',
        'date': today_str,
        'message': f"12:00 AM Banking Cycle for {today_str} completed successfully.",
        'accounts_credited': accounts_credited,
        'total_interest_credited': round(total_interest, 2),
        'loans_debited': loans_debited,
        'total_emi_debited': round(total_emi, 2),
        'failed_debits': failed_debits,
        'user_stats': {
            'accounts_credited': user_accounts_credited,
            'interest_credited': round(user_interest, 2),
            'loans_debited': user_loans_debited,
            'emi_debited': round(user_emi, 2)
        } if user_id is not None else None
    }

_scheduler_started = False
AUTO_CYCLE_CHECK_INTERVAL_SECONDS = 3600  # Run every 1 hour (3600 seconds)

def start_midnight_scheduler(app):
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    interval = app.config.get('AUTO_CYCLE_CHECK_INTERVAL_SECONDS', AUTO_CYCLE_CHECK_INTERVAL_SECONDS)

    def scheduler_worker():
        # Short initial delay to ensure app boot completes smoothly
        time.sleep(3)
        while True:
            try:
                with app.app_context():
                    now = get_ist_time()
                    today_str = now.strftime('%Y-%m-%d')
                    setting = SystemSetting.query.filter_by(key='last_daily_batch_date').first()
                    last_date = setting.value if setting else None

                    # If date rolls over to midnight or today hasn't executed yet
                    if last_date != today_str:
                        print(f"[Autonomous 12:00 AM Daemon] Date rollover detected ({today_str}). Executing midnight banking cycle...", flush=True)
                        result = execute_daily_banking_cycle(target_date_str=today_str)
                        print(f"[Autonomous 12:00 AM Daemon] Cycle finished: {result}", flush=True)
            except Exception as e:
                print(f"[Autonomous 12:00 AM Daemon Error] {e}", flush=True)

            # Check every 1 hour (3600 seconds)
            time.sleep(interval)

    thread = threading.Thread(target=scheduler_worker, daemon=True, name="DailyMidnightSchedulerThread")
    thread.start()

def create_app(test_config=None):
    app = Flask(__name__)

    db_uri = get_database_uri()
    engine_opts = get_engine_options(db_uri)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'neobank-ultra-secure-key-9284729184')
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    if engine_opts:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_opts

    if test_config:
        app.config.update(test_config)

    db.init_app(app)

    # --- Custom Jinja Template Filters ---
    @app.template_filter('currency')
    def currency_filter(value):
        try:
            return f"₹{float(value):,.2f}"
        except (ValueError, TypeError):
            return "₹0.00"

    @app.template_filter('datetime_format')
    def datetime_format(value, format='%b %d, %Y %I:%M %p'):
        if isinstance(value, datetime):
            return value.strftime(format)
        return value or ""

    @app.template_filter('date_format')
    def date_format(value, format='%b %d, %Y'):
        if isinstance(value, datetime):
            return value.strftime(format)
        return value or ""

    # --- Auth Helper Decorator ---
    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please authenticate to access your NeoBank dashboard.', 'warning')
                return redirect(url_for('login', next=request.url))
            return f(*args, **kwargs)
        return decorated_function

    def log_activity(user_id, action, details=None):
        try:
            ip = request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1')
            log = ActivityLog(user_id=user_id, action=action, details=details, ip_address=ip)
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()

    @app.context_processor
    def inject_current_user():
        if 'user_id' in session:
            current_user = db.session.get(User, session['user_id'])
            return {'current_user': current_user}
        return {'current_user': None}

    # --- Autonomous 12:00 AM Midnight Scheduler Startup ---
    if not app.config.get('TESTING'):
        if os.environ.get('WERKZEUG_RUN_MAIN') != 'false':
            start_midnight_scheduler(app)

    @app.before_request
    def ensure_daily_banking_cycle():
        # High-reliability catch-up hook for missed midnight cycles
        if request.endpoint and 'static' not in request.endpoint and not app.config.get('TESTING'):
            try:
                today_str = get_ist_time().strftime('%Y-%m-%d')
                setting = SystemSetting.query.filter_by(key='last_daily_batch_date').first()
                if not setting or setting.value != today_str:
                    execute_daily_banking_cycle(target_date_str=today_str)
            except Exception:
                db.session.rollback()

    # --- Autonomous Daily Banking Cycle Endpoints ---
    @app.route('/api/auto-cycle/run-daily', methods=['GET', 'POST'])
    def run_daily_cycle_api():
        """
        Triggers or tests the 12:00 AM daily banking cycle.
        Crediting daily interest to savings/FD/checking and auto-debiting loan EMIs.
        """
        force = request.args.get('force', 'true').lower() in ['1', 'true', 'yes']
        target_date = request.args.get('date', None)
        user_id = session.get('user_id')
        result = execute_daily_banking_cycle(target_date_str=target_date, force=force, user_id=user_id)
        return jsonify(result)

    @app.route('/api/auto-cycle/status')
    def auto_cycle_status():
        """
        Reports the operational state of the 12:00 AM autonomous banking scheduler.
        """
        today_str = get_ist_time().strftime('%Y-%m-%d')
        setting = SystemSetting.query.filter_by(key='last_daily_batch_date').first()
        last_date = setting.value if setting else None
        return jsonify({
            'scheduler_active': True,
            'check_interval_seconds': AUTO_CYCLE_CHECK_INTERVAL_SECONDS,
            'schedule': 'Every 1 hour (Autonomous 12:00 AM Midnight Banking Cycle)',
            'current_date': today_str,
            'last_daily_batch_date': last_date,
            'completed_for_today': (last_date == today_str)
        })

    # --- Routes ---

    @app.route('/')
    def index():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        return redirect(url_for('login'))

    # Auth: Login
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            identifier = request.form.get('identifier', '').strip()
            password = request.form.get('password', '')

            # Check by username, email, or account number
            user = None
            if '@' in identifier:
                user = User.query.filter_by(email=identifier).first()
            else:
                user = User.query.filter_by(username=identifier).first()
                if not user:
                    acc = Account.query.filter_by(account_number=identifier.replace("-", "")).first()
                    if acc:
                        user = acc.owner

            if user and user.check_password(password):
                session['user_id'] = user.id
                session['username'] = user.username
                session['full_name'] = user.full_name
                log_activity(user.id, "Session Login", "Successful login via Web Client")
                flash(f"Welcome back, {user.full_name.split()[0]}!", "success")
                next_url = request.args.get('next')
                return redirect(next_url or url_for('dashboard'))
            else:
                flash("Invalid login credentials. Please verify your details or use demo access.", "error")

        return render_template('auth/login.html')

    # Auth: Register
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            username = request.form.get('username', '').strip().lower()
            email = request.form.get('email', '').strip().lower()
            full_name = request.form.get('full_name', '').strip()
            phone = request.form.get('phone', '').strip()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            initial_deposit = float(request.form.get('initial_deposit', 0.0) or 0.0)
            account_type = request.form.get('account_type', 'checking')

            # Validation
            if not username or not email or not full_name or not password:
                flash("Please fill in all mandatory fields.", "error")
                return render_template('auth/register.html')

            if password != confirm_password:
                flash("Passwords do not match.", "error")
                return render_template('auth/register.html')

            if len(password) < 6:
                flash("Password must be at least 6 characters long.", "error")
                return render_template('auth/register.html')

            if User.query.filter_by(username=username).first():
                flash("This username is already taken. Please pick another.", "error")
                return render_template('auth/register.html')

            if User.query.filter_by(email=email).first():
                flash("An account with this email already exists.", "error")
                return render_template('auth/register.html')

            # Create User
            new_user = User(
                username=username,
                email=email,
                full_name=full_name,
                phone=phone
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.flush()

            # Generate distinct 10-digit Account Number
            while True:
                acc_num = str(random.randint(1000000000, 9999999999))
                if not Account.query.filter_by(account_number=acc_num).first():
                    break

            # Create primary account
            rate_map = {'savings': 6.5, 'fixed_deposit': 7.25, 'business': 4.0, 'checking': 3.5}
            deposit_amount = max(0.0, initial_deposit)
            primary_account = Account(
                user_id=new_user.id,
                account_number=acc_num,
                account_type=account_type,
                balance=deposit_amount,
                interest_rate=rate_map.get(account_type, 3.5)
            )
            db.session.add(primary_account)
            db.session.flush()

            # Issue a virtual debit card automatically
            card_num = f"6521 {random.randint(1000, 9999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}"
            exp_year = (get_ist_time().year + 4) % 100
            exp_month = f"{random.randint(1, 12):02d}"
            v_card = VirtualCard(
                user_id=new_user.id,
                account_id=primary_account.id,
                card_number=card_num,
                cardholder_name=full_name.upper(),
                expiry_date=f"{exp_month}/{exp_year}",
                cvv=str(random.randint(100, 999)),
                card_type="RuPay Platinum",
                daily_limit=50000.0
            )
            db.session.add(v_card)

            # Record initial deposit if provided
            if deposit_amount > 0:
                init_txn = Transaction(
                    dest_account_id=primary_account.id,
                    amount=deposit_amount,
                    transaction_type='deposit',
                    category='Account Opening',
                    description='Initial starter balance deposit',
                    status='completed'
                )
                db.session.add(init_txn)

            # If user also selected to open a savings account (dual accounts)
            also_open_savings = request.form.get('also_open_savings')
            if also_open_savings in ['yes', '1', 'true', 'on']:
                secondary_type = 'savings' if account_type != 'savings' else 'checking'
                while True:
                    sec_acc_num = f"88{random.randint(10000000, 99999999)}"[:10]
                    if not Account.query.filter_by(account_number=sec_acc_num).first() and sec_acc_num != acc_num:
                        break

                sec_account = Account(
                    user_id=new_user.id,
                    account_number=sec_acc_num,
                    account_type=secondary_type,
                    balance=15000.0,
                    currency='INR',
                    interest_rate=rate_map.get(secondary_type, 6.5 if secondary_type == 'savings' else 3.5)
                )
                db.session.add(sec_account)
                db.session.flush()

                sec_txn = Transaction(
                    dest_account_id=sec_account.id,
                    amount=15000.0,
                    transaction_type='deposit',
                    category='Account Opening',
                    description=f'Linked {secondary_type.capitalize()} Account Welcome Deposit',
                    status='completed'
                )
                db.session.add(sec_txn)
                log_activity(new_user.id, "Account Created", f"Linked {secondary_type.capitalize()} Account {sec_acc_num} opened")

            log_activity(new_user.id, "Account Created", f"Account {acc_num} opened")
            db.session.commit()

            session['user_id'] = new_user.id
            session['username'] = new_user.username
            session['full_name'] = new_user.full_name
            flash(f"Account created successfully! Welcome to NeoBank, {full_name}.", "success")
            return redirect(url_for('dashboard'))

        return render_template('auth/register.html')

    # Auth: Logout
    @app.route('/logout')
    def logout():
        user_id = session.get('user_id')
        if user_id:
            log_activity(user_id, "Session Logout", "Signed out cleanly")
        session.clear()
        flash("You have been signed out safely.", "info")
        return redirect(url_for('login'))

    # Dashboard
    @app.route('/dashboard')
    @login_required
    def dashboard():
        user = db.session.get(User, session['user_id'])
        primary_acc = user.primary_account
        
        # All account IDs for this user
        account_ids = [acc.id for acc in user.accounts]
        
        # Recent 6 transactions
        recent_transactions = Transaction.query.filter(
            (Transaction.source_account_id.in_(account_ids)) | 
            (Transaction.dest_account_id.in_(account_ids))
        ).order_by(Transaction.timestamp.desc()).limit(6).all()

        # Monthly income and expense calculations (last 30 days)
        total_income = 0.0
        total_expense = 0.0
        all_user_txns = Transaction.query.filter(
            (Transaction.source_account_id.in_(account_ids)) | 
            (Transaction.dest_account_id.in_(account_ids))
        ).all()

        for t in all_user_txns:
            if t.dest_account_id in account_ids and t.source_account_id not in account_ids:
                total_income += t.amount
            elif t.source_account_id in account_ids and t.dest_account_id not in account_ids:
                total_expense += t.amount

        # Primary card
        primary_card = user.cards[0] if user.cards else None

        # Active loans
        active_loans = [l for l in user.loans if l.status in ['active', 'approved']]

        # Savings vaults
        vaults = user.savings_goals[:3]

        # Beneficiaries
        beneficiaries = user.beneficiaries[:4]

        return render_template(
            'dashboard.html',
            user=user,
            primary_account=primary_acc,
            recent_transactions=recent_transactions,
            total_income=total_income,
            total_expense=total_expense,
            primary_card=primary_card,
            active_loans=active_loans,
            vaults=vaults,
            beneficiaries=beneficiaries
        )

    # My Accounts Hub
    @app.route('/accounts')
    @login_required
    def accounts_hub():
        user = db.session.get(User, session['user_id'])
        return render_template('accounts.html', user=user, accounts=user.accounts)

    # Single Account Detail & Statement View
    @app.route('/accounts/<int:account_id>')
    @login_required
    def account_detail(account_id):
        user = db.session.get(User, session['user_id'])
        account = Account.query.filter_by(id=account_id, user_id=user.id).first()
        if not account:
            flash("Account not found.", "error")
            return redirect(url_for('accounts_hub'))
        
        # Account specific transactions
        transactions = Transaction.query.filter(
            (Transaction.source_account_id == account.id) |
            (Transaction.dest_account_id == account.id)
        ).order_by(Transaction.timestamp.desc()).all()

        return render_template('account_detail.html', user=user, account=account, transactions=transactions)

    # Self-Transfer (Internal transfer between user's own checking and savings accounts)
    @app.route('/accounts/self-transfer', methods=['POST'])
    @login_required
    def self_transfer():
        user = db.session.get(User, session['user_id'])
        source_id = request.form.get('source_account_id')
        dest_id = request.form.get('dest_account_id')
        amount = float(request.form.get('amount', 0.0) or 0.0)
        remark = request.form.get('remark', '').strip() or "Self Account Fund Transfer"

        if amount <= 0:
            flash("Please enter a valid transfer amount greater than ₹0.", "error")
            return redirect(url_for('accounts_hub'))

        if source_id == dest_id:
            flash("Source and Destination accounts cannot be the same.", "error")
            return redirect(url_for('accounts_hub'))

        source_acc = Account.query.filter_by(id=source_id, user_id=user.id).first()
        dest_acc = Account.query.filter_by(id=dest_id, user_id=user.id).first()

        if not source_acc or not dest_acc:
            flash("Invalid account selection.", "error")
            return redirect(url_for('accounts_hub'))

        if source_acc.balance < amount:
            flash(f"Insufficient funds in {source_acc.account_type.capitalize()} Account (Balance: ₹{source_acc.balance:,.2f})", "error")
            return redirect(url_for('accounts_hub'))

        source_acc.balance -= amount
        dest_acc.balance += amount

        ref = Transaction().reference_id
        txn = Transaction(
            reference_id=ref,
            source_account_id=source_acc.id,
            dest_account_id=dest_acc.id,
            amount=amount,
            transaction_type='transfer',
            category='Self Transfer',
            description=f"Internal Sweep: {source_acc.account_type.capitalize()} to {dest_acc.account_type.capitalize()} - {remark}",
            status='completed'
        )
        db.session.add(txn)
        log_activity(user.id, "Self Transfer", f"Moved ₹{amount:,.2f} from {source_acc.account_type} to {dest_acc.account_type}")
        db.session.commit()

        flash(f"Transferred ₹{amount:,.2f} from {source_acc.account_type.capitalize()} to {dest_acc.account_type.capitalize()} successfully!", "success")
        return redirect(url_for('accounts_hub'))

    # Open / Create Additional Account
    @app.route('/accounts/open', methods=['GET', 'POST'])
    @app.route('/accounts/create', methods=['GET', 'POST'])
    @login_required
    def open_account():
        user = db.session.get(User, session['user_id'])
        if request.method == 'POST':
            account_type = request.form.get('account_type', 'savings').lower().strip()
            initial_deposit = float(request.form.get('initial_deposit', 0.0) or 0.0)
            funding_source = request.form.get('funding_source', 'existing')
            source_account_id = request.form.get('source_account_id')
            transaction_pin = request.form.get('transaction_pin', '').strip()

            valid_types = ['savings', 'checking', 'fixed_deposit', 'business']
            if account_type not in valid_types:
                flash("Invalid account scheme selected.", "error")
                return redirect(url_for('open_account'))

            if not user.transaction_pin or user.transaction_pin != transaction_pin:
                flash("Incorrect 4-digit transaction PIN. Authorization failed.", "error")
                return redirect(url_for('open_account'))

            if initial_deposit < 0:
                flash("Initial deposit amount cannot be negative.", "error")
                return redirect(url_for('open_account'))

            source_account = None
            if funding_source == 'existing' and initial_deposit > 0:
                if not source_account_id:
                    flash("Please select an existing account to debit initial funds from.", "error")
                    return redirect(url_for('open_account'))
                source_account = Account.query.filter_by(id=source_account_id, user_id=user.id).first()
                if not source_account:
                    flash("Selected funding account was not found.", "error")
                    return redirect(url_for('open_account'))
                if source_account.balance < initial_deposit:
                    flash(f"Insufficient funds in selected {source_account.account_type.capitalize()} Account (Available: ₹{source_account.balance:,.2f}).", "error")
                    return redirect(url_for('open_account'))

            # Generate unique 10-digit account number
            prefix_map = {'savings': '88', 'checking': '48', 'fixed_deposit': '77', 'business': '55'}
            prefix = prefix_map.get(account_type, '66')
            while True:
                rand_part = str(random.randint(10000000, 99999999))
                acc_num = f"{prefix}{rand_part}"[:10]
                if not Account.query.filter_by(account_number=acc_num).first():
                    break

            rate_map = {'savings': 6.5, 'fixed_deposit': 7.25, 'business': 4.0, 'checking': 3.5}
            new_acc = Account(
                user_id=user.id,
                account_number=acc_num,
                account_type=account_type,
                balance=initial_deposit,
                currency="INR",
                status="active",
                interest_rate=rate_map.get(account_type, 3.5)
            )
            db.session.add(new_acc)
            db.session.flush()

            # Record transactions
            if initial_deposit > 0:
                if funding_source == 'existing' and source_account:
                    source_account.balance -= initial_deposit
                    ref = Transaction().reference_id
                    txn = Transaction(
                        reference_id=ref,
                        source_account_id=source_account.id,
                        dest_account_id=new_acc.id,
                        amount=initial_deposit,
                        transaction_type='transfer',
                        category='Account Opening',
                        description=f"Initial funding for new {account_type.capitalize()} A/C {new_acc.formatted_number}",
                        status='completed'
                    )
                    db.session.add(txn)
                else:
                    ref = Transaction().reference_id
                    txn = Transaction(
                        reference_id=ref,
                        dest_account_id=new_acc.id,
                        amount=initial_deposit,
                        transaction_type='deposit',
                        category='Account Opening',
                        description=f"Initial opening deposit for {account_type.capitalize()} Account",
                        status='completed'
                    )
                    db.session.add(txn)

            log_activity(user.id, "Account Opened", f"Opened new {account_type.capitalize()} Account #{acc_num}")
            db.session.commit()

            flash(f"🎉 New {account_type.capitalize()} Account (#{new_acc.formatted_number}) successfully opened with initial balance of ₹{initial_deposit:,.2f}!", "success")
            return redirect(url_for('account_detail', account_id=new_acc.id))

        return render_template('open_account.html', user=user, accounts=user.accounts)

    # Deposit Funds
    @app.route('/deposit', methods=['GET', 'POST'])
    @login_required
    def deposit():
        user = db.session.get(User, session['user_id'])
        if request.method == 'POST':
            account_id = request.form.get('account_id')
            amount = float(request.form.get('amount', 0.0) or 0.0)
            category = request.form.get('category', 'Direct Deposit')
            description = request.form.get('description', '').strip() or f"Electronic Deposit - {category}"

            if amount <= 0:
                flash("Please enter a valid deposit amount greater than ₹0.", "error")
                return redirect(url_for('deposit'))

            account = Account.query.filter_by(id=account_id, user_id=user.id).first()
            if not account:
                flash("Selected account not found.", "error")
                return redirect(url_for('deposit'))

            account.balance += amount
            txn = Transaction(
                dest_account_id=account.id,
                amount=amount,
                transaction_type='deposit',
                category=category,
                description=description,
                status='completed'
            )
            db.session.add(txn)
            log_activity(user.id, "Funds Deposited", f"Deposited ₹{amount:,.2f} into account {account.formatted_number}")
            db.session.commit()

            flash(f"Successfully deposited ₹{amount:,.2f} into your account!", "success")
            return redirect(url_for('transactions'))

        return render_template('deposit_withdraw.html', user=user, active_tab='deposit')

    # Withdraw Funds
    @app.route('/withdraw', methods=['GET', 'POST'])
    @login_required
    def withdraw():
        user = db.session.get(User, session['user_id'])
        if request.method == 'POST':
            account_id = request.form.get('account_id')
            amount = float(request.form.get('amount', 0.0) or 0.0)
            category = request.form.get('category', 'ATM / Cash')
            description = request.form.get('description', '').strip() or f"Withdrawal - {category}"
            pin = request.form.get('transaction_pin', '').strip()

            if amount <= 0:
                flash("Please enter a valid withdrawal amount greater than ₹0.", "error")
                return redirect(url_for('withdraw'))

            if user.transaction_pin and pin != user.transaction_pin:
                flash("Security PIN verification failed.", "error")
                return redirect(url_for('withdraw'))

            account = Account.query.filter_by(id=account_id, user_id=user.id).first()
            if not account:
                flash("Selected account not found.", "error")
                return redirect(url_for('withdraw'))

            if account.balance < amount:
                flash(f"Insufficient funds. Available balance: ₹{account.balance:,.2f}", "error")
                return redirect(url_for('withdraw'))

            account.balance -= amount
            txn = Transaction(
                source_account_id=account.id,
                amount=amount,
                transaction_type='withdraw',
                category=category,
                description=description,
                status='completed'
            )
            db.session.add(txn)
            log_activity(user.id, "Funds Withdrawn", f"Withdrew ₹{amount:,.2f} from account {account.formatted_number}")
            db.session.commit()

            flash(f"Successfully withdrawn ₹{amount:,.2f}. Updated balance: ₹{account.balance:,.2f}", "success")
            return redirect(url_for('transactions'))

        return render_template('deposit_withdraw.html', user=user, active_tab='withdraw')

    # Transfer Funds
    @app.route('/transfer', methods=['GET', 'POST'])
    @login_required
    def transfer():
        user = db.session.get(User, session['user_id'])
        if request.method == 'POST':
            source_account_id = request.form.get('source_account_id')
            recipient_query = request.form.get('recipient_account', '').strip().replace("-", "")
            amount = float(request.form.get('amount', 0.0) or 0.0)
            note = request.form.get('note', '').strip() or "IMPS Fund Transfer"
            save_beneficiary = request.form.get('save_beneficiary') == '1'
            beneficiary_nickname = request.form.get('beneficiary_nickname', '').strip()
            pin = request.form.get('transaction_pin', '').strip()

            if amount <= 0:
                flash("Please enter a valid transfer amount greater than ₹0.", "error")
                return redirect(url_for('transfer'))

            if user.transaction_pin and pin != user.transaction_pin:
                flash("Incorrect Security PIN. Transfer rejected.", "error")
                return redirect(url_for('transfer'))

            source_account = Account.query.filter_by(id=source_account_id, user_id=user.id).first()
            if not source_account:
                flash("Invalid source account.", "error")
                return redirect(url_for('transfer'))

            if source_account.balance < amount:
                flash(f"Transfer declined: Insufficient funds (Balance: ₹{source_account.balance:,.2f})", "error")
                return redirect(url_for('transfer'))

            # Resolve destination account
            dest_account = None
            dest_account = Account.query.filter_by(account_number=recipient_query).first()
            if not dest_account:
                dest_user = User.query.filter_by(username=recipient_query.lower()).first()
                if dest_user:
                    dest_account = dest_user.primary_account

            if not dest_account:
                flash("Recipient account number or username not found in NeoBank network.", "error")
                return redirect(url_for('transfer'))

            if dest_account.id == source_account.id:
                flash("You cannot transfer funds to the same source account.", "error")
                return redirect(url_for('transfer'))

            # Atomic transaction
            source_account.balance -= amount
            dest_account.balance += amount

            dest_owner_name = dest_account.owner.full_name
            ref = Transaction().reference_id

            # Outgoing transaction record
            out_txn = Transaction(
                reference_id=ref,
                source_account_id=source_account.id,
                dest_account_id=dest_account.id,
                amount=amount,
                transaction_type='transfer',
                category='Transfer',
                description=f"IMPS to {dest_owner_name} ({dest_account.formatted_number}) - {note}",
                status='completed'
            )
            db.session.add(out_txn)

            # Save beneficiary if requested
            if save_beneficiary:
                existing = Beneficiary.query.filter_by(
                    user_id=user.id, 
                    account_number=dest_account.account_number
                ).first()
                if not existing:
                    ben = Beneficiary(
                        user_id=user.id,
                        name=dest_owner_name,
                        account_number=dest_account.account_number,
                        nickname=beneficiary_nickname or dest_owner_name.split()[0]
                    )
                    db.session.add(ben)

            log_activity(user.id, "P2P Transfer Sent", f"Transferred ₹{amount:,.2f} to {dest_owner_name}")
            db.session.commit()

            flash(f"Successfully transferred ₹{amount:,.2f} to {dest_owner_name} (Ref: {ref})", "success")
            return redirect(url_for('transactions'))

        beneficiaries = user.beneficiaries
        return render_template('transfer.html', user=user, beneficiaries=beneficiaries)

    # Transactions Ledger
    @app.route('/transactions')
    @login_required
    def transactions():
        user = db.session.get(User, session['user_id'])
        account_ids = [acc.id for acc in user.accounts]

        txn_type = request.args.get('type', 'all')
        search_query = request.args.get('q', '').strip()
        category = request.args.get('category', 'all')

        query = Transaction.query.filter(
            (Transaction.source_account_id.in_(account_ids)) |
            (Transaction.dest_account_id.in_(account_ids))
        )

        if txn_type != 'all':
            query = query.filter(Transaction.transaction_type == txn_type)

        if category != 'all':
            query = query.filter(Transaction.category == category)

        if search_query:
            query = query.filter(
                (Transaction.description.ilike(f"%{search_query}%")) |
                (Transaction.reference_id.ilike(f"%{search_query}%"))
            )

        transactions_list = query.order_by(Transaction.timestamp.desc()).all()

        return render_template(
            'transactions.html',
            user=user,
            transactions=transactions_list,
            current_type=txn_type,
            current_category=category,
            search_query=search_query
        )

    # Export Transactions to CSV
    @app.route('/transactions/export')
    @login_required
    def export_transactions():
        user = db.session.get(User, session['user_id'])
        account_ids = [acc.id for acc in user.accounts]

        transactions_list = Transaction.query.filter(
            (Transaction.source_account_id.in_(account_ids)) |
            (Transaction.dest_account_id.in_(account_ids))
        ).order_by(Transaction.timestamp.desc()).all()

        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['Reference ID', 'Date & Time', 'Type', 'Category', 'Description', 'Direction', 'Amount (INR)', 'Status'])

        for t in transactions_list:
            is_credit = t.dest_account_id in account_ids and t.source_account_id not in account_ids
            direction = 'CREDIT (+)' if is_credit else 'DEBIT (-)'
            formatted_date = t.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            cw.writerow([
                t.reference_id,
                formatted_date,
                t.transaction_type.capitalize(),
                t.category,
                t.description,
                direction,
                f"{t.amount:.2f}",
                t.status.capitalize()
            ])

        output = si.getvalue()
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename=NeoBank_Statement_{get_ist_time().strftime('%Y%m%d')}.csv"}
        )

    # --- Category-Aware Credit Underwriting & Loan Facility Engine ---
    LOAN_CATEGORIES = {
        'home': {
            'name': 'Home Loan',
            'description': 'Mortgage, plot acquisition, or home construction/renovation',
            'max_amount_cap': 15000000.0,  # ₹1.5 Crore
            'min_amount': 50000.0,
            'max_tenure_months': 300,      # 25 Years (300 Months)
            'min_tenure_months': 24,       # 2 Years
            'default_term': 240,           # 20 Years
            'default_amount': 5000000.0,   # ₹50 Lakh
            'tiers': {
                800: {'multiplier': 75.0, 'max_cap': 15000000.0, 'base_rate': 8.40, 'tier': 'Super Prime'},
                750: {'multiplier': 60.0, 'max_cap': 12500000.0, 'base_rate': 8.65, 'tier': 'Prime'},
                700: {'multiplier': 45.0, 'max_cap': 10000000.0, 'base_rate': 8.95, 'tier': 'Good'},
                650: {'multiplier': 30.0, 'max_cap': 6000000.0,  'base_rate': 9.50, 'tier': 'Fair'},
                600: {'multiplier': 15.0, 'max_cap': 3000000.0,  'base_rate': 10.50, 'tier': 'Subprime Eligible'},
            },
            'income_discounts': [
                (150000, -0.30),
                (100000, -0.20),
                (50000, -0.10),
            ],
            'tenure_adjustments': [
                (180, 0.20),
            ]
        },
        'auto': {
            'name': 'Car & Vehicle Loan',
            'description': 'New/used cars, commercial utility vehicles, and electric vehicles',
            'max_amount_cap': 4000000.0,   # ₹40 Lakh
            'min_amount': 25000.0,
            'max_tenure_months': 84,       # 7 Years (84 Months)
            'min_tenure_months': 12,       # 1 Year
            'default_term': 48,            # 4 Years
            'default_amount': 800000.0,    # ₹8 Lakh
            'tiers': {
                800: {'multiplier': 20.0, 'max_cap': 4000000.0, 'base_rate': 8.75, 'tier': 'Super Prime'},
                750: {'multiplier': 16.0, 'max_cap': 3500000.0, 'base_rate': 9.15, 'tier': 'Prime'},
                700: {'multiplier': 12.0, 'max_cap': 2500000.0, 'base_rate': 9.75, 'tier': 'Good'},
                650: {'multiplier': 8.0,  'max_cap': 1500000.0, 'base_rate': 10.75, 'tier': 'Fair'},
                600: {'multiplier': 4.0,  'max_cap': 800000.0,  'base_rate': 12.00, 'tier': 'Subprime Eligible'},
            },
            'income_discounts': [
                (150000, -0.40),
                (100000, -0.25),
                (50000, -0.15),
            ],
            'tenure_adjustments': [
                (60, 0.25),
            ]
        },
        'business': {
            'name': 'Business Loan',
            'description': 'Working capital, commercial inventory, and equipment scaling',
            'max_amount_cap': 7500000.0,   # ₹75 Lakh
            'min_amount': 50000.0,
            'max_tenure_months': 120,      # 10 Years (120 Months)
            'min_tenure_months': 12,       # 1 Year
            'default_term': 60,            # 5 Years
            'default_amount': 1500000.0,   # ₹15 Lakh
            'tiers': {
                800: {'multiplier': 35.0, 'max_cap': 7500000.0, 'base_rate': 9.75, 'tier': 'Super Prime'},
                750: {'multiplier': 28.0, 'max_cap': 6000000.0, 'base_rate': 10.50, 'tier': 'Prime'},
                700: {'multiplier': 20.0, 'max_cap': 4500000.0, 'base_rate': 11.50, 'tier': 'Good'},
                650: {'multiplier': 12.0, 'max_cap': 2500000.0, 'base_rate': 12.75, 'tier': 'Fair'},
                600: {'multiplier': 6.0,  'max_cap': 1200000.0, 'base_rate': 14.00, 'tier': 'Subprime Eligible'},
            },
            'income_discounts': [
                (150000, -0.50),
                (100000, -0.30),
                (50000, -0.15),
            ],
            'tenure_adjustments': [
                (60, 0.35),
            ]
        },
        'education': {
            'name': 'Higher Education Loan',
            'description': 'Domestic tuition, overseas university programs, and technical certifications',
            'max_amount_cap': 5000000.0,   # ₹50 Lakh
            'min_amount': 25000.0,
            'max_tenure_months': 180,      # 15 Years (180 Months)
            'min_tenure_months': 12,       # 1 Year
            'default_term': 84,            # 7 Years
            'default_amount': 1000000.0,   # ₹10 Lakh
            'tiers': {
                800: {'multiplier': 30.0, 'max_cap': 5000000.0, 'base_rate': 8.50, 'tier': 'Super Prime'},
                750: {'multiplier': 24.0, 'max_cap': 4000000.0, 'base_rate': 8.90, 'tier': 'Prime'},
                700: {'multiplier': 18.0, 'max_cap': 3000000.0, 'base_rate': 9.40, 'tier': 'Good'},
                650: {'multiplier': 10.0, 'max_cap': 1800000.0, 'base_rate': 10.20, 'tier': 'Fair'},
                600: {'multiplier': 5.0,  'max_cap': 1000000.0, 'base_rate': 11.50, 'tier': 'Subprime Eligible'},
            },
            'income_discounts': [
                (150000, -0.40),
                (100000, -0.25),
                (50000, -0.15),
            ],
            'tenure_adjustments': [
                (84, 0.25),
            ]
        },
        'personal': {
            'name': 'Personal Loan',
            'description': 'Short-term personal liquidity, emergency medical expenses, and lifestyle needs',
            'max_amount_cap': 5000000.0,   # ₹50 Lakh max cap
            'min_amount': 10000.0,
            'max_tenure_months': 60,       # 5 Years (60 Months)
            'min_tenure_months': 6,        # 6 Months
            'default_term': 24,            # 2 Years
            'default_amount': 200000.0,    # ₹2 Lakh
            'tiers': {
                800: {'multiplier': 25.0, 'max_cap': 5000000.0, 'base_rate': 7.50, 'tier': 'Super Prime'},
                750: {'multiplier': 18.0, 'max_cap': 3500000.0, 'base_rate': 8.50, 'tier': 'Prime'},
                700: {'multiplier': 12.0, 'max_cap': 2000000.0, 'base_rate': 9.90, 'tier': 'Good'},
                650: {'multiplier': 8.0,  'max_cap': 1000000.0, 'base_rate': 11.75, 'tier': 'Fair'},
                600: {'multiplier': 4.0,  'max_cap': 400000.0,  'base_rate': 13.50, 'tier': 'Subprime Eligible'},
            },
            'income_discounts': [
                (150000, -0.75),
                (100000, -0.50),
                (50000, -0.25),
                (0, 0.50),
            ],
            'tenure_adjustments': [
                (36, 0.50),
                (12, 0.25),
            ]
        }
    }

    def evaluate_loan_eligibility(credit_score, monthly_income, term_months=12, category='personal'):
        """
        Evaluates risk tier, interest rate, and maximum allowable borrowing limit
        strictly based on CIBIL Credit Score, Monthly Net Income, and Loan Category.
        """
        category = (category or 'personal').lower()
        if category not in LOAN_CATEGORIES:
            category = 'personal'
        cat = LOAN_CATEGORIES[category]

        credit_score = int(credit_score or 760)
        monthly_income = float(monthly_income or 0.0)

        # 1. Hard rejection thresholds
        if credit_score < 600:
            return {
                'eligible': False,
                'tier': 'Subprime (Ineligible)',
                'credit_score': credit_score,
                'monthly_income': monthly_income,
                'category': category,
                'category_name': cat['name'],
                'max_amount': 0.0,
                'interest_rate': 0.0,
                'max_tenure_months': cat['max_tenure_months'],
                'min_tenure_months': cat['min_tenure_months'],
                'reason': f"Credit score {credit_score} is below the mandatory minimum CIBIL threshold of 600."
            }

        if monthly_income < 20000:
            return {
                'eligible': False,
                'tier': 'Low Income (Ineligible)',
                'credit_score': credit_score,
                'monthly_income': monthly_income,
                'category': category,
                'category_name': cat['name'],
                'max_amount': 0.0,
                'interest_rate': 0.0,
                'max_tenure_months': cat['max_tenure_months'],
                'min_tenure_months': cat['min_tenure_months'],
                'reason': f"Monthly income of ₹{monthly_income:,.2f} is below the required underwriting baseline of ₹20,000."
            }

        # 2. Maximum Loan Limit strictly determined by Credit Score Tier & Income Multiplier for category
        tier_info = None
        for cutoff in sorted(cat['tiers'].keys(), reverse=True):
            if credit_score >= cutoff:
                tier_info = cat['tiers'][cutoff]
                break
        if not tier_info:
            tier_info = cat['tiers'][600]

        multiplier = tier_info['multiplier']
        max_cap = tier_info['max_cap']
        base_rate = tier_info['base_rate']
        tier = tier_info['tier']

        max_loan_amount = min(max_cap, round(monthly_income * multiplier, -2))
        max_loan_amount = max(cat['min_amount'], max_loan_amount)

        # 3. Monthly Income Interest Rate Concession / Risk Adjustment
        income_discount = 0.0
        if category == 'personal':
            if monthly_income >= 150000:
                income_discount = -0.75  # High net worth discount
            elif monthly_income >= 100000:
                income_discount = -0.50
            elif monthly_income >= 50000:
                income_discount = -0.25
            elif monthly_income < 30000:
                income_discount = 0.50   # Risk premium for low income
        else:
            for inc_threshold, disc in cat['income_discounts']:
                if monthly_income >= inc_threshold:
                    income_discount = disc
                    break

        # 4. Tenure Adjustment
        tenure_adj = 0.0
        for threshold, adj in sorted(cat['tenure_adjustments'], key=lambda x: x[0], reverse=True):
            if term_months > threshold:
                tenure_adj = adj
                break

        final_interest_rate = max(6.99, round(base_rate + income_discount + tenure_adj, 2))

        return {
            'eligible': True,
            'tier': tier,
            'category': category,
            'category_name': cat['name'],
            'credit_score': credit_score,
            'monthly_income': monthly_income,
            'multiplier': multiplier,
            'max_amount': max_loan_amount,
            'max_tenure_months': cat['max_tenure_months'],
            'min_tenure_months': cat['min_tenure_months'],
            'interest_rate': final_interest_rate,
            'reason': None
        }

    # Loan Management
    @app.route('/loans', methods=['GET'])
    @login_required
    def loans():
        user = db.session.get(User, session['user_id'])
        category = request.args.get('category', 'home').lower()
        if category not in LOAN_CATEGORIES:
            category = 'home'
        cat_info = LOAN_CATEGORIES[category]
        eligibility = evaluate_loan_eligibility(user.credit_score or 760, user.monthly_income or 75000.0, cat_info['default_term'], category=category)
        return render_template(
            'loans.html',
            user=user,
            loans=user.loans,
            eligibility=eligibility,
            categories=LOAN_CATEGORIES,
            selected_category=category
        )

    @app.route('/loans/apply', methods=['POST'])
    @login_required
    def apply_loan():
        user = db.session.get(User, session['user_id'])
        amount = float(request.form.get('amount', 0.0) or 0.0)
        term_months = int(request.form.get('term_months', 12) or 12)
        category = request.form.get('category', 'personal').lower()
        purpose = request.form.get('purpose', 'Personal Loan').strip()
        monthly_income = float(request.form.get('monthly_income', user.monthly_income or 75000.0) or 0.0)
        credit_score = int(request.form.get('credit_score', user.credit_score or 760) or 760)

        if category not in LOAN_CATEGORIES:
            category = 'personal'
        cat_info = LOAN_CATEGORIES[category]

        # Check tenure bounds for category
        if term_months > cat_info['max_tenure_months']:
            max_yrs = cat_info['max_tenure_months'] // 12
            flash(f"Application Denied: Tenure of {term_months} months exceeds maximum allowable tenure of {cat_info['max_tenure_months']} months ({max_yrs} Years) for {cat_info['name']}.", "error")
            return redirect(url_for('loans', category=category))

        if term_months < cat_info['min_tenure_months']:
            flash(f"Application Denied: Tenure of {term_months} months is below minimum required tenure of {cat_info['min_tenure_months']} months for {cat_info['name']}.", "error")
            return redirect(url_for('loans', category=category))

        # Underwriting evaluation strictly based on credit score, monthly income, and category
        eligibility = evaluate_loan_eligibility(credit_score, monthly_income, term_months, category=category)
        
        if not eligibility['eligible']:
            flash(f"Application Ineligible: {eligibility['reason']}", "error")
            return redirect(url_for('loans', category=category))

        if amount < cat_info['min_amount']:
            flash(f"Minimum loan amount for {cat_info['name']} is ₹{cat_info['min_amount']:,.2f}.", "error")
            return redirect(url_for('loans', category=category))

        # Hard limit enforcement: max loan amount strictly decided by credit score, income, & category
        if amount > eligibility['max_amount']:
            flash(
                f"Application Denied: Requested loan of ₹{amount:,.2f} exceeds your maximum eligible limit of "
                f"₹{eligibility['max_amount']:,.2f} for {cat_info['name']} calculated from your CIBIL score ({credit_score}) and monthly income (₹{monthly_income:,.2f}).",
                "error"
            )
            return redirect(url_for('loans', category=category))

        interest_rate = eligibility['interest_rate']

        # Monthly EMI Calculation: [P * r * (1+r)^n] / [(1+r)^n - 1]
        monthly_rate = (interest_rate / 100.0) / 12.0
        if monthly_rate > 0:
            emi = (amount * monthly_rate * ((1 + monthly_rate) ** term_months)) / (((1 + monthly_rate) ** term_months) - 1)
        else:
            emi = amount / term_months

        total_payable = emi * term_months

        # Instantly disburse loan funds directly into primary checking account
        primary_account = user.primary_account
        if not primary_account:
            flash("No active checking account available to disburse loan.", "error")
            return redirect(url_for('loans', category=category))

        # Persist updated underwriting metrics to user profile
        user.credit_score = credit_score
        user.monthly_income = monthly_income

        new_loan = Loan(
            user_id=user.id,
            amount=amount,
            interest_rate=interest_rate,
            term_months=term_months,
            monthly_emi=round(emi, 2),
            total_payable=round(total_payable, 2),
            amount_paid=0.0,
            category=category,
            credit_score_at_application=credit_score,
            monthly_income=monthly_income,
            max_eligible_amount=eligibility['max_amount'],
            status='active',
            purpose=purpose
        )
        db.session.add(new_loan)

        primary_account.balance += amount
        disbursement_txn = Transaction(
            dest_account_id=primary_account.id,
            amount=amount,
            transaction_type='loan_disbursement',
            category='Loan Credit',
            description=f"Loan Credit: {purpose} ({cat_info['name']} {new_loan.loan_reference} @ {interest_rate}% p.a.)",
            status='completed'
        )
        db.session.add(disbursement_txn)
        log_activity(user.id, "Loan Disbursed", f"₹{amount:,.2f} disbursed for {purpose} ({cat_info['name']}) @ {interest_rate}% (CIBIL: {credit_score}, Income: ₹{monthly_income:,.2f})")
        db.session.commit()

        flash(f"🎉 Loan application approved! ₹{amount:,.2f} sanctioned for {cat_info['name']} at {interest_rate}% p.a. (CIBIL: {credit_score}) and credited to your account.", "success")
        return redirect(url_for('loans', category=category))

    # Live Credit & Loan Eligibility API
    @app.route('/api/loan-eligibility')
    @login_required
    def api_loan_eligibility():
        user = db.session.get(User, session['user_id'])
        score = int(request.args.get('score', user.credit_score or 760) or 760)
        income = float(request.args.get('income', user.monthly_income or 75000.0) or 75000.0)
        category = request.args.get('category', 'personal').lower()
        if category not in LOAN_CATEGORIES:
            category = 'personal'
        cat_info = LOAN_CATEGORIES[category]

        term = int(request.args.get('term', cat_info['default_term']) or cat_info['default_term'])
        term = max(cat_info['min_tenure_months'], min(cat_info['max_tenure_months'], term))
        amount = float(request.args.get('amount', cat_info['default_amount']) or cat_info['default_amount'])

        eligibility = evaluate_loan_eligibility(score, income, term, category=category)
        rate = eligibility['interest_rate']
        
        calc_amt = min(amount, eligibility['max_amount']) if eligibility['max_amount'] > 0 else amount
        monthly_rate = (rate / 100.0) / 12.0
        if monthly_rate > 0:
            emi = (calc_amt * monthly_rate * ((1 + monthly_rate) ** term)) / (((1 + monthly_rate) ** term) - 1)
        else:
            emi = calc_amt / term
        total_payable = emi * term
        total_interest = total_payable - calc_amt

        return jsonify({
            'eligible': eligibility['eligible'],
            'tier': eligibility['tier'],
            'category': eligibility['category'],
            'category_name': eligibility['category_name'],
            'credit_score': score,
            'monthly_income': income,
            'multiplier': eligibility.get('multiplier', 0),
            'max_amount': eligibility['max_amount'],
            'max_tenure_months': eligibility['max_tenure_months'],
            'min_tenure_months': eligibility['min_tenure_months'],
            'interest_rate': rate,
            'reason': eligibility['reason'],
            'calculated_emi': round(emi, 2),
            'total_payable': round(total_payable, 2),
            'total_interest': round(total_interest, 2)
        })

    @app.route('/loans/pay/<int:loan_id>', methods=['POST'])
    @login_required
    def pay_loan_installment(loan_id):
        user = db.session.get(User, session['user_id'])
        loan = Loan.query.filter_by(id=loan_id, user_id=user.id).first()

        if not loan or loan.status != 'active':
            flash("Active loan record not found.", "error")
            return redirect(url_for('loans'))

        payment_type = request.form.get('payment_type', 'emi')  # 'emi' or 'extra'
        primary_account = user.primary_account

        if payment_type == 'extra':
            # Extra Loan Prepayment with 12.3% fee
            extra_amount = float(request.form.get('extra_amount', 0.0) or 0.0)
            if extra_amount <= 0:
                flash("Please enter a valid extra payment amount greater than ₹0.", "error")
                return redirect(url_for('loans'))

            remaining = loan.remaining_amount
            actual_extra = min(extra_amount, remaining)
            fee = round(actual_extra * 0.123, 2)  # 12.3% prepayment fee
            total_required = actual_extra + fee

            if primary_account.balance < total_required:
                flash(f"Insufficient funds. Required: ₹{total_required:,.2f} (Principal: ₹{actual_extra:,.2f} + 12.3% Fee: ₹{fee:,.2f}). Available: ₹{primary_account.balance:,.2f}", "error")
                return redirect(url_for('loans'))

            primary_account.balance -= total_required
            loan.amount_paid += actual_extra

            # Determine given loan tenure for updated EMI calculation
            given_tenure = request.form.get('tenure_months')
            try:
                target_tenure = int(given_tenure) if given_tenure and int(given_tenure) > 0 else 0
            except (ValueError, TypeError):
                target_tenure = 0

            if target_tenure <= 0:
                target_tenure = max(1, round((loan.total_payable - loan.amount_paid) / loan.monthly_emi)) if loan.monthly_emi > 0 else loan.term_months

            if loan.amount_paid >= loan.total_payable - 0.01:
                loan.status = 'completed'
                loan.monthly_emi = 0.0
                flash(f"Extra payment of ₹{actual_extra:,.2f} completed (12.3% fee: ₹{fee:,.2f}). Loan ({loan.loan_reference}) is now fully paid off!", "success")
            else:
                # Recalculate Monthly EMI based on updated principal and given tenure
                r = (loan.interest_rate / 100.0) / 12.0
                if r > 0 and target_tenure > 0:
                    pv_principal = loan.monthly_emi * (1 - (1 + r) ** (-target_tenure)) / r
                    new_principal = max(0.0, pv_principal - actual_extra)
                    if new_principal > 0:
                        new_emi = (new_principal * r * ((1 + r) ** target_tenure)) / (((1 + r) ** target_tenure) - 1)
                    else:
                        new_emi = 0.0
                else:
                    new_principal = max(0.0, loan.remaining_amount)
                    new_emi = new_principal / target_tenure if target_tenure > 0 else 0.0

                old_emi = loan.monthly_emi
                loan.monthly_emi = round(new_emi, 2)
                loan.total_payable = round(loan.amount_paid + (loan.monthly_emi * target_tenure), 2)
                loan.term_months = target_tenure
                flash(f"Extra payment of ₹{actual_extra:,.2f} applied successfully! (12.3% fee: ₹{fee:,.2f}). Monthly EMI updated from ₹{old_emi:,.2f} to ₹{loan.monthly_emi:,.2f} for given tenure of {target_tenure} months.", "success")

            # Loan Principal Prepayment Transaction
            pay_txn = Transaction(
                source_account_id=primary_account.id,
                amount=actual_extra,
                transaction_type='loan_payment',
                category='Loan Prepayment',
                description=f"Extra Principal Prepayment ({loan.loan_reference})",
                status='completed'
            )
            db.session.add(pay_txn)

            # 12.3% Prepayment Fee Transaction
            if fee > 0:
                fee_txn = Transaction(
                    source_account_id=primary_account.id,
                    amount=fee,
                    transaction_type='withdraw',
                    category='Bank Charges',
                    description=f"12.3% Prepayment Processing Fee ({loan.loan_reference})",
                    status='completed'
                )
                db.session.add(fee_txn)

            log_activity(user.id, "Loan Extra Prepayment", f"Paid ₹{actual_extra:,.2f} + ₹{fee:,.2f} (12.3% fee) for {loan.loan_reference}")
            db.session.commit()
            return redirect(url_for('loans'))

        else:
            # Standard Monthly EMI (no extra fee)
            pay_amount = float(request.form.get('pay_amount', loan.monthly_emi) or loan.monthly_emi)
            remaining = loan.remaining_amount
            actual_pay = min(pay_amount, remaining)

            if primary_account.balance < actual_pay:
                flash(f"Insufficient balance to make EMI payment. Needed: ₹{actual_pay:,.2f}", "error")
                return redirect(url_for('loans'))

            primary_account.balance -= actual_pay
            loan.amount_paid += actual_pay

            if loan.amount_paid >= loan.total_payable - 0.01:
                loan.status = 'completed'
                loan.monthly_emi = 0.0
                flash(f"Loan fully repaid! ({loan.loan_reference}).", "success")
            else:
                flash(f"EMI of ₹{actual_pay:,.2f} paid. Outstanding: ₹{loan.remaining_amount:,.2f}", "success")

            pay_txn = Transaction(
                source_account_id=primary_account.id,
                amount=actual_pay,
                transaction_type='loan_payment',
                category='Loan Repayment',
                description=f"Loan EMI Repayment ({loan.loan_reference})",
                status='completed'
            )
            db.session.add(pay_txn)
            log_activity(user.id, "Loan EMI Paid", f"Paid ₹{actual_pay:,.2f} towards {loan.loan_reference}")
            db.session.commit()
            return redirect(url_for('loans'))

    # Virtual Cards
    @app.route('/cards')
    @login_required
    def cards():
        user = db.session.get(User, session['user_id'])
        return render_template('cards.html', user=user, cards=user.cards)

    @app.route('/cards/toggle-freeze/<int:card_id>', methods=['POST'])
    @login_required
    def toggle_freeze_card(card_id):
        user = db.session.get(User, session['user_id'])
        card = VirtualCard.query.filter_by(id=card_id, user_id=user.id).first()
        if not card:
            flash("Card not found.", "error")
            return redirect(url_for('cards'))

        if card.status == 'active':
            card.status = 'frozen'
            action_desc = "Card Blocked"
            flash("Debit Card blocked temporarily. Transactions disabled.", "warning")
        else:
            card.status = 'active'
            action_desc = "Card Unblocked"
            flash("Debit Card unblocked. Ready for transactions.", "success")

        log_activity(user.id, action_desc, f"Card ending in {card.card_number[-4:]}")
        db.session.commit()
        return redirect(url_for('cards'))

    @app.route('/cards/update-limit/<int:card_id>', methods=['POST'])
    @login_required
    def update_card_limit(card_id):
        user = db.session.get(User, session['user_id'])
        card = VirtualCard.query.filter_by(id=card_id, user_id=user.id).first()
        if not card:
            flash("Card not found.", "error")
            return redirect(url_for('cards'))

        new_limit = float(request.form.get('daily_limit', 50000.0) or 50000.0)
        card.daily_limit = max(1000.0, new_limit)
        log_activity(user.id, "Card Limit Updated", f"New limit: ₹{card.daily_limit:,.2f}")
        db.session.commit()
        flash(f"Daily transaction limit updated to ₹{card.daily_limit:,.2f}", "success")
        return redirect(url_for('cards'))

    # Savings Vaults
    @app.route('/vaults')
    @login_required
    def vaults():
        user = db.session.get(User, session['user_id'])
        return render_template('vaults.html', user=user, vaults=user.savings_goals)

    @app.route('/vaults/create', methods=['POST'])
    @login_required
    def create_vault():
        user = db.session.get(User, session['user_id'])
        name = request.form.get('name', '').strip()
        target_amount = float(request.form.get('target_amount', 0.0) or 0.0)
        initial_stash = float(request.form.get('initial_stash', 0.0) or 0.0)
        color = request.form.get('color', '#1e40af')
        deadline = request.form.get('deadline', '').strip()

        if not name or target_amount <= 0:
            flash("Please provide a valid goal name and target amount.", "error")
            return redirect(url_for('vaults'))

        primary_account = user.primary_account
        if initial_stash > 0:
            if primary_account.balance < initial_stash:
                flash("Insufficient savings balance for initial allocation.", "error")
                return redirect(url_for('vaults'))
            primary_account.balance -= initial_stash

        vault = SavingsGoal(
            user_id=user.id,
            name=name,
            target_amount=target_amount,
            current_amount=initial_stash,
            color=color,
            deadline=deadline
        )
        db.session.add(vault)

        if initial_stash > 0:
            txn = Transaction(
                source_account_id=primary_account.id,
                amount=initial_stash,
                transaction_type='vault_deposit',
                category='Savings',
                description=f"Moved to Goal: {name}",
                status='completed'
            )
            db.session.add(txn)

        log_activity(user.id, "Savings Goal Created", f"Goal: {name} (₹{target_amount:,.2f})")
        db.session.commit()
        flash(f"Savings Goal '{name}' created successfully!", "success")
        return redirect(url_for('vaults'))

    @app.route('/vaults/deposit/<int:goal_id>', methods=['POST'])
    @login_required
    def deposit_vault(goal_id):
        user = User.query.get(session['user_id'])
        vault = SavingsGoal.query.filter_by(id=goal_id, user_id=user.id).first()
        if not vault:
            flash("Goal not found.", "error")
            return redirect(url_for('vaults'))

        amount = float(request.form.get('amount', 0.0) or 0.0)
        primary_account = user.primary_account

        if amount <= 0:
            flash("Please enter an amount greater than ₹0.", "error")
            return redirect(url_for('vaults'))

        if primary_account.balance < amount:
            flash(f"Insufficient funds in account. Available: ₹{primary_account.balance:,.2f}", "error")
            return redirect(url_for('vaults'))

        primary_account.balance -= amount
        vault.current_amount += amount

        txn = Transaction(
            source_account_id=primary_account.id,
            amount=amount,
            transaction_type='vault_deposit',
            category='Savings',
            description=f"Added to Goal: {vault.name}",
            status='completed'
        )
        db.session.add(txn)
        log_activity(user.id, "Allocated to Goal", f"₹{amount:,.2f} added to {vault.name}")
        db.session.commit()
        flash(f"Added ₹{amount:,.2f} to '{vault.name}'. Progress: {vault.progress_percentage}%", "success")
        return redirect(url_for('vaults'))

    @app.route('/vaults/withdraw/<int:goal_id>', methods=['POST'])
    @login_required
    def withdraw_vault(goal_id):
        user = User.query.get(session['user_id'])
        vault = SavingsGoal.query.filter_by(id=goal_id, user_id=user.id).first()
        if not vault:
            flash("Goal not found.", "error")
            return redirect(url_for('vaults'))

        amount = float(request.form.get('amount', 0.0) or 0.0)
        primary_account = user.primary_account

        if amount <= 0:
            flash("Please enter an amount greater than ₹0.", "error")
            return redirect(url_for('vaults'))

        if vault.current_amount < amount:
            flash(f"Insufficient balance in goal. Available: ₹{vault.current_amount:,.2f}", "error")
            return redirect(url_for('vaults'))

        vault.current_amount -= amount
        primary_account.balance += amount

        txn = Transaction(
            dest_account_id=primary_account.id,
            amount=amount,
            transaction_type='vault_withdraw',
            category='Savings',
            description=f"Withdrawn from Goal: {vault.name}",
            status='completed'
        )
        db.session.add(txn)
        log_activity(user.id, "Withdrew from Goal", f"₹{amount:,.2f} moved back from {vault.name}")
        db.session.commit()
        flash(f"Returned ₹{amount:,.2f} from '{vault.name}' back to Account.", "success")
        return redirect(url_for('vaults'))

    # Beneficiaries
    @app.route('/beneficiaries/add', methods=['POST'])
    @login_required
    def add_beneficiary():
        user = User.query.get(session['user_id'])
        account_num = request.form.get('account_number', '').strip().replace("-", "")
        name = request.form.get('name', '').strip()
        nickname = request.form.get('nickname', '').strip()

        target_acc = Account.query.filter_by(account_number=account_num).first()
        if not target_acc:
            flash("Target account number is not registered on NeoBank.", "error")
            return redirect(url_for('transfer'))

        if target_acc.user_id == user.id:
            flash("You cannot add yourself as a beneficiary.", "error")
            return redirect(url_for('transfer'))

        existing = Beneficiary.query.filter_by(user_id=user.id, account_number=account_num).first()
        if existing:
            flash("This contact is already in your beneficiaries list.", "info")
            return redirect(url_for('transfer'))

        ben = Beneficiary(
            user_id=user.id,
            name=name or target_acc.owner.full_name,
            account_number=account_num,
            nickname=nickname or (name or target_acc.owner.full_name).split()[0]
        )
        db.session.add(ben)
        db.session.commit()
        flash(f"Added {ben.name} to quick beneficiaries.", "success")
        return redirect(url_for('transfer'))

    @app.route('/beneficiaries/delete/<int:id>', methods=['POST'])
    @login_required
    def delete_beneficiary(id):
        user = User.query.get(session['user_id'])
        ben = Beneficiary.query.filter_by(id=id, user_id=user.id).first()
        if ben:
            db.session.delete(ben)
            db.session.commit()
            flash("Beneficiary removed.", "info")
        return redirect(url_for('transfer'))

    # Profile & Security Settings
    @app.route('/profile')
    @login_required
    def profile():
        user = User.query.get(session['user_id'])
        logs = ActivityLog.query.filter_by(user_id=user.id).order_by(ActivityLog.timestamp.desc()).limit(15).all()
        return render_template('profile.html', user=user, logs=logs)

    @app.route('/profile/change-password', methods=['POST'])
    @login_required
    def change_password():
        user = User.query.get(session['user_id'])
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not user.check_password(current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for('profile'))

        if len(new_password) < 6:
            flash("New password must be at least 6 characters long.", "error")
            return redirect(url_for('profile'))

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for('profile'))

        user.set_password(new_password)
        log_activity(user.id, "Security: Password Changed", "Updated via security console")
        db.session.commit()
        flash("Password updated successfully.", "success")
        return redirect(url_for('profile'))

    @app.route('/profile/change-pin', methods=['POST'])
    @login_required
    def change_pin():
        user = User.query.get(session['user_id'])
        current_pin = request.form.get('current_pin', '')
        new_pin = request.form.get('new_pin', '').strip()

        if user.transaction_pin and current_pin != user.transaction_pin:
            flash("Current transaction PIN is incorrect.", "error")
            return redirect(url_for('profile'))

        if len(new_pin) != 4 or not new_pin.isdigit():
            flash("Transaction PIN must be exactly 4 digits.", "error")
            return redirect(url_for('profile'))

        user.transaction_pin = new_pin
        log_activity(user.id, "Security: PIN Changed", "4-digit PIN refreshed")
        db.session.commit()
        flash("Transaction PIN updated successfully.", "success")
        return redirect(url_for('profile'))

    # Quick API endpoint for account lookup during transfer (for reactive UX)
    @app.route('/api/lookup-account')
    @login_required
    def lookup_account():
        query = request.args.get('query', '').strip().replace("-", "")
        if not query:
            return jsonify({'found': False})

        acc = Account.query.filter_by(account_number=query).first()
        if not acc:
            u = User.query.filter_by(username=query.lower()).first()
            if u:
                acc = u.primary_account

        if acc and acc.user_id != session['user_id']:
            return jsonify({
                'found': True,
                'name': acc.owner.full_name,
                'account_number': acc.formatted_number,
                'account_type': acc.account_type.capitalize()
            })
        return jsonify({'found': False})

    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        target_db = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if '@' in target_db:
            # Mask password in logs
            proto_and_creds, host_part = target_db.split('@', 1)
            masked_target = f"{proto_and_creds.split(':')[0]}://****@{host_part}"
        else:
            masked_target = target_db
        print(f"[*] NeoBank Engine initializing with DB: {masked_target}")
        db.create_all()
    app.run(debug=True, port=5000)

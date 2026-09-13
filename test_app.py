import unittest
import json
from app import create_app
from models import db, User, Account, Transaction, Loan, SavingsGoal, VirtualCard

class NeoBankTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SECRET_KEY': 'test-secret',
            'WTF_CSRF_ENABLED': False
        })
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create test user 1 (Alice)
            u1 = User(
                username='alice',
                email='alice@bank.test',
                full_name='Alice Wonderland',
                phone='+1234567890',
                transaction_pin='1234'
            )
            u1.set_password('pass123')
            db.session.add(u1)
            db.session.flush()

            a1 = Account(
                user_id=u1.id,
                account_number='1111222233',
                account_type='checking',
                balance=5000.0
            )
            db.session.add(a1)
            a1_savings = Account(
                user_id=u1.id,
                account_number='1111222299',
                account_type='savings',
                balance=15000.0
            )
            db.session.add(a1_savings)
            db.session.flush()

            c1 = VirtualCard(
                user_id=u1.id,
                account_id=a1.id,
                card_number='6521 1111 2222 3333',
                cardholder_name='ALICE WONDERLAND',
                expiry_date='12/28',
                cvv='999',
                status='active',
                daily_limit=50000.0,
                card_type='RuPay Platinum'
            )
            db.session.add(c1)

            # Create test user 2 (Bob)
            u2 = User(
                username='bob',
                email='bob@bank.test',
                full_name='Bob Builder',
                transaction_pin='1234'
            )
            u2.set_password('pass123')
            db.session.add(u2)
            db.session.flush()

            a2 = Account(
                user_id=u2.id,
                account_number='4444555566',
                account_type='checking',
                balance=1000.0
            )
            db.session.add(a2)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self, username='alice', password='pass123'):
        return self.client.post('/login', data={
            'identifier': username,
            'password': password
        }, follow_redirects=True)

    def test_login_success_and_failure(self):
        # Failed login
        res = self.client.post('/login', data={'identifier': 'alice', 'password': 'wrong'}, follow_redirects=True)
        self.assertIn(b'Invalid login credentials', res.data)

        # Successful login
        res = self.login('alice', 'pass123')
        self.assertIn(b'Account Dashboard', res.data)
        self.assertIn(b'Alice Wonderland', res.data)

    def test_deposit(self):
        self.login('alice', 'pass123')
        with self.app.app_context():
            acc = Account.query.filter_by(account_number='1111222233').first()
            acc_id = acc.id

        res = self.client.post('/deposit', data={
            'account_id': acc_id,
            'amount': '1500.00',
            'category': 'Salary',
            'description': 'Monthly Consulting'
        }, follow_redirects=True)

        self.assertIn(b'Successfully deposited', res.data)
        with self.app.app_context():
            acc = Account.query.filter_by(account_number='1111222233').first()
            self.assertEqual(acc.balance, 6500.0)

    def test_withdrawal_valid_and_insufficient_funds(self):
        self.login('alice', 'pass123')
        with self.app.app_context():
            acc = Account.query.filter_by(account_number='1111222233').first()
            acc_id = acc.id

        # Insufficient funds attempt
        res = self.client.post('/withdraw', data={
            'account_id': acc_id,
            'amount': '10000.00',
            'transaction_pin': '1234'
        }, follow_redirects=True)
        self.assertIn(b'Insufficient funds', res.data)

        # Valid withdrawal
        res = self.client.post('/withdraw', data={
            'account_id': acc_id,
            'amount': '500.00',
            'transaction_pin': '1234',
            'category': 'ATM / Cash',
            'description': 'Pocket Cash'
        }, follow_redirects=True)
        self.assertIn(b'Successfully withdrawn', res.data)

        with self.app.app_context():
            acc = Account.query.filter_by(account_number='1111222233').first()
            self.assertEqual(acc.balance, 4500.0)

    def test_transfer_atomic(self):
        self.login('alice', 'pass123')
        with self.app.app_context():
            alice_acc = Account.query.filter_by(account_number='1111222233').first()
            source_id = alice_acc.id

        res = self.client.post('/transfer', data={
            'source_account_id': source_id,
            'recipient_account': '4444555566',
            'amount': '1200.00',
            'note': 'Sublet rent share',
            'transaction_pin': '1234'
        }, follow_redirects=True)

        self.assertIn(b'Successfully transferred', res.data)
        self.assertIn(b'Bob Builder', res.data)

        with self.app.app_context():
            alice_acc = Account.query.filter_by(account_number='1111222233').first()
            bob_acc = Account.query.filter_by(account_number='4444555566').first()
            self.assertEqual(alice_acc.balance, 3800.0)
            self.assertEqual(bob_acc.balance, 2200.0)

    def test_loan_application_and_repayment(self):
        self.login('alice', 'pass123')
        # Apply for loan
        res = self.client.post('/loans/apply', data={
            'amount': '50000',
            'term_months': '24',
            'purpose': 'Solar Panels',
            'monthly_income': '60000'
        }, follow_redirects=True)

        self.assertIn(b'credited to your account', res.data)

        with self.app.app_context():
            alice_acc = Account.query.filter_by(account_number='1111222233').first()
            self.assertEqual(alice_acc.balance, 55000.0)
            loan = Loan.query.filter_by(purpose='Solar Panels').first()
            self.assertIsNotNone(loan)
            self.assertEqual(loan.amount, 50000.0)
            loan_id = loan.id
            monthly_emi = loan.monthly_emi

        # Pay 1 installment
        res = self.client.post(f'/loans/pay/{loan_id}', data={
            'pay_amount': str(monthly_emi)
        }, follow_redirects=True)
        self.assertIn(b'paid', res.data)

        with self.app.app_context():
            alice_acc = Account.query.filter_by(account_number='1111222233').first()
            loan = Loan.query.get(loan_id)
            self.assertAlmostEqual(alice_acc.balance, 55000.0 - monthly_emi, places=2)
            self.assertAlmostEqual(loan.amount_paid, monthly_emi, places=2)

    def test_extra_loan_payment_with_fee(self):
        self.login('alice', 'pass123')
        # Apply for loan
        self.client.post('/loans/apply', data={
            'amount': '50000',
            'term_months': '24',
            'purpose': 'Business Setup',
            'monthly_income': '60000'
        }, follow_redirects=True)

        with self.app.app_context():
            loan = Loan.query.filter_by(purpose='Business Setup').first()
            loan_id = loan.id
            alice_acc = Account.query.filter_by(account_number='1111222233').first()
            balance_before = alice_acc.balance

        # Pay extra 10000 towards loan
        extra_amt = 10000.0
        expected_fee = 1230.0  # 12.3% of 10000
        total_deduction = extra_amt + expected_fee

        res = self.client.post(f'/loans/pay/{loan_id}', data={
            'payment_type': 'extra',
            'extra_amount': str(extra_amt)
        }, follow_redirects=True)

        self.assertIn(b'Extra payment of', res.data)
        self.assertIn(b'12.3% fee', res.data)

        with self.app.app_context():
            alice_acc = Account.query.filter_by(account_number='1111222233').first()
            loan = Loan.query.get(loan_id)
            self.assertAlmostEqual(alice_acc.balance, balance_before - total_deduction, places=2)
            self.assertEqual(loan.amount_paid, extra_amt)

    def test_virtual_card_freeze_and_limit(self):
        self.login('alice', 'pass123')
        with self.app.app_context():
            card = VirtualCard.query.first()
            card_id = card.id
            self.assertEqual(card.status, 'active')

        # Freeze card
        res = self.client.post(f'/cards/toggle-freeze/{card_id}', follow_redirects=True)
        self.assertIn(b'Debit Card blocked', res.data)

        with self.app.app_context():
            card = VirtualCard.query.get(card_id)
            self.assertEqual(card.status, 'frozen')

        # Update limit
        res = self.client.post(f'/cards/update-limit/{card_id}', data={'daily_limit': '3500'}, follow_redirects=True)
        self.assertIn(b'Daily transaction limit updated to', res.data)

    def test_vaults_create_and_stash(self):
        self.login('alice', 'pass123')
        # Create vault with $500 initial stash
        res = self.client.post('/vaults/create', data={
            'name': 'Iceland Trek',
            'target_amount': '3000',
            'initial_stash': '500',
            'color': '#3B82F6',
            'deadline': 'Sept 2026'
        }, follow_redirects=True)
        self.assertIn(b'Iceland Trek', res.data)

        with self.app.app_context():
            acc = Account.query.filter_by(account_number='1111222233').first()
            vault = SavingsGoal.query.filter_by(name='Iceland Trek').first()
            self.assertEqual(acc.balance, 4500.0)
            self.assertEqual(vault.current_amount, 500.0)

    def test_export_transactions_csv(self):
        self.login('alice', 'pass123')
        res = self.client.get('/transactions/export')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content_type, 'text/csv; charset=utf-8')
        self.assertIn(b'Reference ID,Date & Time,Type,Category', res.data)

    def test_accounts_hub_and_detail(self):
        self.login('alice', 'pass123')
        # View Accounts hub
        res = self.client.get('/accounts')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'My Accounts', res.data)
        self.assertIn(b'1111222233', res.data)
        self.assertIn(b'1111222299', res.data)
        self.assertIn(b'High-Yield Savings', res.data)

        # View Savings Account Detail
        with self.app.app_context():
            savings_acc = Account.query.filter_by(account_number='1111222299').first()
            savings_id = savings_acc.id

        res = self.client.get(f'/accounts/{savings_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Account Passbook', res.data)
        self.assertIn(b'1111-2222-99', res.data)

    def test_self_transfer_checking_to_savings(self):
        self.login('alice', 'pass123')
        with self.app.app_context():
            chk = Account.query.filter_by(account_number='1111222233').first()
            svg = Account.query.filter_by(account_number='1111222299').first()
            chk_id = chk.id
            svg_id = svg.id

        res = self.client.post('/accounts/self-transfer', data={
            'source_account_id': chk_id,
            'dest_account_id': svg_id,
            'amount': '2000.00',
            'remark': 'Monthly savings sweep'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Transferred', res.data)

        with self.app.app_context():
            chk = Account.query.filter_by(account_number='1111222233').first()
            svg = Account.query.filter_by(account_number='1111222299').first()
            self.assertEqual(chk.balance, 3000.0)
            self.assertEqual(svg.balance, 17000.0)

    def test_manual_account_creation_funded_from_existing(self):
        self.login('alice', 'pass123')
        with self.app.app_context():
            chk = Account.query.filter_by(account_number='1111222233').first()
            source_id = chk.id
            chk_balance_before = chk.balance

        # Open a new Fixed Deposit account funded by transferring 1500 from checking
        res = self.client.post('/accounts/open', data={
            'account_type': 'fixed_deposit',
            'initial_deposit': '1500.00',
            'funding_source': 'existing',
            'source_account_id': source_id,
            'transaction_pin': '1234'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'successfully opened', res.data)

        with self.app.app_context():
            alice = User.query.filter_by(username='alice').first()
            # Alice should now have 3 accounts (checking, savings, fixed_deposit)
            self.assertEqual(len(alice.accounts), 3)
            fd_acc = Account.query.filter_by(user_id=alice.id, account_type='fixed_deposit').first()
            self.assertIsNotNone(fd_acc)
            self.assertEqual(fd_acc.balance, 1500.0)
            chk = Account.query.filter_by(account_number='1111222233').first()
            self.assertEqual(chk.balance, chk_balance_before - 1500.0)

    def test_manual_account_creation_external_funding(self):
        self.login('alice', 'pass123')
        # Open a new Corporate/Business account funded externally
        res = self.client.post('/accounts/open', data={
            'account_type': 'business',
            'initial_deposit': '10000.00',
            'funding_source': 'external',
            'transaction_pin': '1234'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'successfully opened', res.data)

        with self.app.app_context():
            alice = User.query.filter_by(username='alice').first()
            biz_acc = Account.query.filter_by(user_id=alice.id, account_type='business').first()
            self.assertIsNotNone(biz_acc)
            self.assertEqual(biz_acc.balance, 10000.0)

    def test_manual_account_creation_invalid_pin(self):
        self.login('alice', 'pass123')
        res = self.client.post('/accounts/open', data={
            'account_type': 'savings',
            'initial_deposit': '1000.00',
            'funding_source': 'external',
            'transaction_pin': '9999'  # Wrong PIN
        }, follow_redirects=True)

        self.assertIn(b'Incorrect 4-digit transaction PIN', res.data)

    def test_register_with_dual_accounts(self):
        # Register a new user with dual accounts checked
        res = self.client.post('/register', data={
            'full_name': 'Kavita Verma',
            'username': 'kavita.v',
            'email': 'kavita@bank.test',
            'phone': '9876543210',
            'account_type': 'checking',
            'initial_deposit': '7000.00',
            'also_open_savings': 'yes',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        with self.app.app_context():
            u = User.query.filter_by(username='kavita.v').first()
            self.assertIsNotNone(u)
            # Should have both checking and savings accounts
            self.assertEqual(len(u.accounts), 2)
            acc_types = {acc.account_type for acc in u.accounts}
            self.assertEqual(acc_types, {'checking', 'savings'})

    def test_loan_underwriting_subprime_rejection(self):
        self.login('alice', 'pass123')
        # Subprime credit score < 600
        res = self.client.post('/loans/apply', data={
            'amount': '50000',
            'term_months': '24',
            'purpose': 'Medical Emergency',
            'monthly_income': '50000',
            'credit_score': '550'
        }, follow_redirects=True)

        self.assertIn(b'below the mandatory minimum CIBIL threshold', res.data)

    def test_loan_underwriting_low_income_rejection(self):
        self.login('alice', 'pass123')
        # Monthly income < 20000
        res = self.client.post('/loans/apply', data={
            'amount': '30000',
            'term_months': '12',
            'purpose': 'Gadget Purchase',
            'monthly_income': '15000',
            'credit_score': '750'
        }, follow_redirects=True)

        self.assertIn(b'below the required underwriting baseline', res.data)

    def test_loan_underwriting_amount_exceeding_max_limit(self):
        self.login('alice', 'pass123')
        # Score 660 (Fair Tier: 8x multiplier). Income: 30000 -> Max Limit = 240,000.
        # User tries to borrow 400,000.
        res = self.client.post('/loans/apply', data={
            'amount': '400000',
            'term_months': '24',
            'purpose': 'Luxury Vacation',
            'monthly_income': '30000',
            'credit_score': '660'
        }, follow_redirects=True)

        self.assertIn(b'exceeds your maximum eligible limit', res.data)

    def test_loan_underwriting_income_discount_and_approval(self):
        self.login('alice', 'pass123')
        # Super prime: Score 810, Income 120,000 (qualifies for -0.50% income concession)
        # Max limit is 25x = 3,000,000. User requests 200,000.
        res = self.client.post('/loans/apply', data={
            'amount': '200000',
            'term_months': '24',
            'purpose': 'Home Solar Expansion',
            'monthly_income': '120000',
            'credit_score': '810'
        }, follow_redirects=True)

        self.assertIn(b'Loan application approved', res.data)

        with self.app.app_context():
            loan = Loan.query.filter_by(purpose='Home Solar Expansion').first()
            self.assertIsNotNone(loan)
            self.assertEqual(loan.credit_score_at_application, 810)
            self.assertEqual(loan.monthly_income, 120000.0)
            self.assertEqual(loan.max_eligible_amount, 3000000.0)
            # Base 7.50% - 0.50% income rebate + 0.25% tenure adj = 7.25% p.a.
            self.assertEqual(loan.interest_rate, 7.25)

    def test_loan_eligibility_api(self):
        self.login('alice', 'pass123')
        res = self.client.get('/api/loan-eligibility?score=780&income=80000&term=24&amount=300000')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['eligible'])
        self.assertEqual(data['tier'], 'Prime')
        # 18x 80,000 = 1,440,000
        self.assertEqual(data['max_amount'], 1440000.0)
        self.assertGreater(data['calculated_emi'], 0)

    def test_home_loan_up_to_1_5_crore_and_25_years(self):
        self.login('alice', 'pass123')
        # Super prime: score 820, monthly income 220,000 -> 75x = 16,500,000, capped at ₹1.5 Crore (15,000,000)
        res = self.client.post('/loans/apply', data={
            'category': 'home',
            'amount': '15000000',
            'term_months': '300',  # 25 Years
            'purpose': 'Luxury Villa Construction',
            'monthly_income': '220000',
            'credit_score': '820'
        }, follow_redirects=True)

        self.assertIn(b'Loan application approved', res.data)
        self.assertIn(b'Home Loan', res.data)

        with self.app.app_context():
            loan = Loan.query.filter_by(purpose='Luxury Villa Construction').first()
            self.assertIsNotNone(loan)
            self.assertEqual(loan.category, 'home')
            self.assertEqual(loan.amount, 15000000.0)
            self.assertEqual(loan.term_months, 300)
            self.assertEqual(loan.max_eligible_amount, 15000000.0)
            self.assertGreater(loan.monthly_emi, 0)
            # 8.40 base - 0.30 income rebate + 0.20 tenure (>180m) = 8.30%
            self.assertEqual(loan.interest_rate, 8.30)

    def test_car_loan_tenure_limit_enforced(self):
        self.login('alice', 'pass123')
        # Car loans have a strict max tenure of 84 months (7 Years). Requesting 120 months must be rejected.
        res = self.client.post('/loans/apply', data={
            'category': 'auto',
            'amount': '1500000',
            'term_months': '120',  # 10 Years (exceeds 7 Years cap)
            'purpose': 'Electric SUV',
            'monthly_income': '150000',
            'credit_score': '780'
        }, follow_redirects=True)

        self.assertIn(b'exceeds maximum allowable tenure of 84 months (7 Years)', res.data)

    def test_car_loan_amount_limit_enforced(self):
        self.login('alice', 'pass123')
        # Even for high income (300,000), Car Loan is strictly capped at ₹40 Lakh (4,000,000). Requesting 5,000,000 must be denied.
        res = self.client.post('/loans/apply', data={
            'category': 'auto',
            'amount': '5000000',
            'term_months': '60',
            'purpose': 'Imported Sports Car',
            'monthly_income': '300000',
            'credit_score': '800'
        }, follow_redirects=True)

        self.assertIn(b'exceeds your maximum eligible limit of', res.data)
        self.assertIn(b'Vehicle Loan', res.data)

    def test_category_eligibility_api(self):
        self.login('alice', 'pass123')
        # Test Home Loan eligibility API (₹1.5 Crore cap, 300 months max tenure)
        res_home = self.client.get('/api/loan-eligibility?score=800&income=200000&category=home&term=300')
        self.assertEqual(res_home.status_code, 200)
        data_home = res_home.get_json()
        self.assertEqual(data_home['category'], 'home')
        self.assertEqual(data_home['max_amount'], 15000000.0)
        self.assertEqual(data_home['max_tenure_months'], 300)
        self.assertEqual(data_home['min_tenure_months'], 24)

        # Test Auto Loan eligibility API (₹40 Lakh cap, 84 months max tenure)
        res_auto = self.client.get('/api/loan-eligibility?score=800&income=200000&category=auto&term=84')
        self.assertEqual(res_auto.status_code, 200)
        data_auto = res_auto.get_json()
        self.assertEqual(data_auto['category'], 'auto')
        self.assertEqual(data_auto['max_amount'], 4000000.0)
        self.assertEqual(data_auto['max_tenure_months'], 84)
        self.assertEqual(data_auto['min_tenure_months'], 12)

    def test_autonomous_daily_interest_accrual(self):
        with self.app.app_context():
            from app import execute_daily_banking_cycle
            # Alice has savings balance = 15000.0. Default savings rate is 6.5% p.a.
            # Expected daily interest = round(15000 * (6.5 / 100) / 365, 2) = round(2.6712, 2) = 2.67
            res = execute_daily_banking_cycle(target_date_str='2026-09-05', force=True)
            self.assertTrue(res['success'])
            self.assertGreater(res['accounts_credited'], 0)
            self.assertGreater(res['total_interest_credited'], 0)

            savings_acc = Account.query.filter_by(account_number='1111222299').first()
            self.assertAlmostEqual(savings_acc.balance, 15000.0 + 2.67, places=2)
            self.assertAlmostEqual(savings_acc.total_interest_earned, 2.67, places=2)
            self.assertEqual(savings_acc.last_interest_accrual_date, '2026-09-05')

            # Verify interest transaction recorded
            txn = Transaction.query.filter_by(dest_account_id=savings_acc.id, transaction_type='interest_credit').first()
            self.assertIsNotNone(txn)
            self.assertEqual(txn.category, 'Interest Payout')
            self.assertEqual(txn.amount, 2.67)

    def test_autonomous_loan_emi_auto_debit(self):
        with self.app.app_context():
            from app import execute_daily_banking_cycle
            user = User.query.filter_by(username='alice').first()
            checking_acc = Account.query.filter_by(account_number='1111222233').first()
            initial_checking_bal = checking_acc.balance  # 5000.0

            # Create an active loan for Alice
            loan = Loan(
                user_id=user.id,
                loan_reference='LN-TEST01',
                amount=50000.0,
                interest_rate=8.5,
                term_months=12,
                monthly_emi=4360.0,
                total_payable=52320.0,
                amount_paid=0.0,
                category='personal',
                status='active',
                purpose='Home renovation',
                auto_debit_enabled=True
            )
            db.session.add(loan)
            db.session.commit()

            # Execute daily cycle
            res = execute_daily_banking_cycle(target_date_str='2026-09-06', force=True)
            self.assertTrue(res['success'])
            self.assertGreaterEqual(res['loans_debited'], 1)

            # Check daily loan interest was deducted from Alice's checking account (along with daily checking interest 0.48)
            checking_acc = Account.query.filter_by(account_number='1111222233').first()
            daily_loan_interest = round(52320.0 * (8.5 / 100.0) / 365.0, 2)  # 12.18
            expected_checking_bal = round(initial_checking_bal + round(initial_checking_bal * 0.035 / 365.0, 2) - daily_loan_interest, 2)
            self.assertAlmostEqual(checking_acc.balance, expected_checking_bal, places=2)

            loan = Loan.query.filter_by(loan_reference='LN-TEST01').first()
            self.assertAlmostEqual(loan.amount_paid, daily_loan_interest, places=2)
            self.assertEqual(loan.last_emi_deducted_date, '2026-09-06')
            self.assertLess(loan.monthly_emi, 4360.0)
            self.assertAlmostEqual(loan.monthly_emi, 4358.94, places=2)

            # Check transaction record
            emi_txn = Transaction.query.filter_by(source_account_id=checking_acc.id, transaction_type='loan_payment').first()
            self.assertIsNotNone(emi_txn)
            self.assertEqual(emi_txn.category, 'Loan Auto-Debit')
            self.assertEqual(emi_txn.amount, daily_loan_interest)

    def test_auto_cycle_api_endpoint(self):
        # Test GET status
        res_status = self.client.get('/api/auto-cycle/status')
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.get_json()
        self.assertTrue(status_data['scheduler_active'])
        self.assertEqual(status_data['check_interval_seconds'], 3600)

        # Test POST trigger
        res_run = self.client.post('/api/auto-cycle/run-daily?force=true')
        self.assertEqual(res_run.status_code, 200)
        run_data = res_run.get_json()
        self.assertTrue(run_data['success'])
        self.assertIn('status', run_data)

    def test_loan_extra_prepayment_recalculates_emi(self):
        with self.client:
            self.login('alice', 'pass123')
            with self.app.app_context():
                user = User.query.filter_by(username='alice').first()
                primary_acc = user.primary_account
                primary_acc.balance = 50000.0  # Ensure ample balance
                
                loan = Loan(
                    user_id=user.id,
                    loan_reference='LN-PREPAY01',
                    amount=50000.0,
                    interest_rate=8.5,
                    term_months=12,
                    monthly_emi=4360.0,
                    total_payable=52320.0,
                    amount_paid=0.0,
                    category='personal',
                    status='active',
                    purpose='Prepayment Test',
                    auto_debit_enabled=True
                )
                db.session.add(loan)
                db.session.commit()
                loan_id = loan.id

            # Post extra prepayment of 10,000 with tenure of 12 months
            res = self.client.post(f'/loans/pay/{loan_id}', data={
                'payment_type': 'extra',
                'extra_amount': '10000.0',
                'tenure_months': '12'
            }, follow_redirects=True)
            self.assertEqual(res.status_code, 200)

            with self.app.app_context():
                updated_loan = Loan.query.get(loan_id)
                self.assertEqual(updated_loan.amount_paid, 10000.0)
                # New EMI must be strictly less than original 4360.0
                self.assertLess(updated_loan.monthly_emi, 4360.0)
                self.assertGreater(updated_loan.monthly_emi, 0.0)
                self.assertEqual(updated_loan.term_months, 12)

if __name__ == '__main__':
    unittest.main()




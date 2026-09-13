import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from app import create_app
from models import db, User, Account, Transaction, Loan, SavingsGoal, VirtualCard, Beneficiary, ActivityLog, get_ist_time

load_dotenv()

def seed_database():
    app = create_app()
    with app.app_context():
        target_db = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if '@' in target_db:
            proto_and_creds, host_part = target_db.split('@', 1)
            masked_target = f"{proto_and_creds.split(':')[0]}://****@{host_part}"
        else:
            masked_target = target_db
        print(f"[*] Target Database: {masked_target}")
        db.drop_all()
        db.create_all()

        print("Seeding NeoBank Database with INR records...")

        # 1. Create Primary Demo User: Alex Mercer
        alex = User(
            username="alex.mercer",
            email="alex@mercer.dev",
            full_name="Alexander Mercer",
            phone="+91 98201 44829",
            transaction_pin="1234",
            role="customer"
        )
        alex.set_password("password123")
        db.session.add(alex)
        db.session.flush()

        # Alex's Checking / Savings Account
        alex_checking = Account(
            user_id=alex.id,
            account_number="4820918234",
            account_type="checking",
            balance=142500.00,
            currency="INR",
            status="active"
        )
        alex_savings = Account(
            user_id=alex.id,
            account_number="8831209177",
            account_type="savings",
            balance=350000.00,
            currency="INR",
            status="active"
        )
        db.session.add_all([alex_checking, alex_savings])
        db.session.flush()

        # Alex's RuPay Debit Card
        alex_card = VirtualCard(
            user_id=alex.id,
            account_id=alex_checking.id,
            card_number="6521 8921 4019 8392",
            cardholder_name="ALEXANDER MERCER",
            expiry_date="09/29",
            cvv="842",
            card_type="RuPay Platinum",
            status="active",
            daily_limit=50000.0,
            current_spent=4250.0
        )
        db.session.add(alex_card)

        # 2. Create Secondary Users
        sarah = User(
            username="sarah.chen",
            email="sarah@chen.io",
            full_name="Sarah Chen",
            phone="+91 98450 11928",
            transaction_pin="1234",
            role="customer"
        )
        sarah.set_password("password123")
        db.session.add(sarah)
        db.session.flush()

        sarah_checking = Account(
            user_id=sarah.id,
            account_number="5928109244",
            account_type="checking",
            balance=98400.00,
            currency="INR",
            status="active"
        )
        db.session.add(sarah_checking)
        db.session.flush()

        sarah_card = VirtualCard(
            user_id=sarah.id,
            account_id=sarah_checking.id,
            card_number="6521 4410 9921 3410",
            cardholder_name="SARAH CHEN",
            expiry_date="11/28",
            cvv="391",
            card_type="RuPay Platinum",
            status="active",
            daily_limit=40000.0,
            current_spent=1200.0
        )
        db.session.add(sarah_card)

        marcus = User(
            username="marcus.vance",
            email="marcus@vance.co",
            full_name="Marcus Vance",
            phone="+91 97110 39201",
            transaction_pin="1234",
            role="customer"
        )
        marcus.set_password("password123")
        db.session.add(marcus)
        db.session.flush()

        marcus_checking = Account(
            user_id=marcus.id,
            account_number="3910827411",
            account_type="checking",
            balance=41200.00,
            currency="INR",
            status="active"
        )
        db.session.add(marcus_checking)
        db.session.flush()

        # 3. Beneficiaries for Alex
        ben1 = Beneficiary(
            user_id=alex.id,
            name="Sarah Chen",
            account_number="5928109244",
            nickname="Sarah Architect"
        )
        ben2 = Beneficiary(
            user_id=alex.id,
            name="Marcus Vance",
            account_number="3910827411",
            nickname="Marcus Tech"
        )
        db.session.add_all([ben1, ben2])

        # 4. Savings Vaults for Alex
        vault1 = SavingsGoal(
            user_id=alex.id,
            name="Emergency Fund (6 Months)",
            target_amount=150000.0,
            current_amount=95000.0,
            color="#2563eb",
            deadline="Dec 2026"
        )
        vault2 = SavingsGoal(
            user_id=alex.id,
            name="Goa Family Vacation",
            target_amount=60000.0,
            current_amount=42000.0,
            color="#059669",
            deadline="Oct 2026"
        )
        vault3 = SavingsGoal(
            user_id=alex.id,
            name="Home Office & Computing",
            target_amount=80000.0,
            current_amount=35000.0,
            color="#d97706",
            deadline="Aug 2026"
        )
        db.session.add_all([vault1, vault2, vault3])

        # 5. Active Loan for Alex
        alex_loan = Loan(
            user_id=alex.id,
            loan_reference="LN-892401",
            amount=200000.0,
            interest_rate=9.5,
            term_months=24,
            monthly_emi=9183.05,
            total_payable=220393.20,
            amount_paid=36732.20, # 4 installments paid
            status="active",
            purpose="Solar Rooftop Installation",
            applied_at=get_ist_time() - timedelta(days=120),
            approved_at=get_ist_time() - timedelta(days=119)
        )
        db.session.add(alex_loan)

        # 6. Realistic Transactions for Alex
        now = get_ist_time()
        sample_txns = [
            Transaction(
                reference_id="TXN-9812A4F1",
                dest_account_id=alex_checking.id,
                amount=95000.00,
                transaction_type="deposit",
                category="Salary",
                description="NEFT Credit: Monthly Tech Consulting Retainer",
                status="completed",
                timestamp=now - timedelta(days=2, hours=4)
            ),
            Transaction(
                reference_id="TXN-7741C2B0",
                source_account_id=alex_checking.id,
                dest_account_id=sarah_checking.id,
                amount=12500.00,
                transaction_type="transfer",
                category="Transfer",
                description="IMPS to Sarah Chen - Office Rent Shared Share",
                status="completed",
                timestamp=now - timedelta(days=3, hours=10)
            ),
            Transaction(
                reference_id="TXN-4412B890",
                source_account_id=alex_checking.id,
                amount=4500.00,
                transaction_type="withdraw",
                category="Shopping",
                description="UPI / Amazon India - Electronics & Accessories",
                status="completed",
                timestamp=now - timedelta(days=5, hours=1)
            ),
            Transaction(
                reference_id="TXN-3321E5F8",
                source_account_id=alex_checking.id,
                amount=2450.00,
                transaction_type="withdraw",
                category="Bills & Utilities",
                description="Electricity & Fiber Broadband Payment",
                status="completed",
                timestamp=now - timedelta(days=7, hours=15)
            ),
            Transaction(
                reference_id="TXN-1109D94A",
                source_account_id=alex_checking.id,
                amount=9183.05,
                transaction_type="loan_payment",
                category="Loan Repayment",
                description="Auto-Debit EMI: Solar Rooftop Installation (LN-892401)",
                status="completed",
                timestamp=now - timedelta(days=10, hours=8)
            ),
            Transaction(
                reference_id="TXN-6623F811",
                source_account_id=alex_checking.id,
                amount=10000.00,
                transaction_type="vault_deposit",
                category="Savings",
                description="Transferred to Goal: Goa Family Vacation",
                status="completed",
                timestamp=now - timedelta(days=12, hours=3)
            ),
            Transaction(
                reference_id="TXN-5501B203",
                dest_account_id=alex_checking.id,
                amount=35000.00,
                transaction_type="deposit",
                category="Investment Returns",
                description="Dividend Credit - Mutual Funds & Securities",
                status="completed",
                timestamp=now - timedelta(days=16, hours=11)
            ),
            Transaction(
                reference_id="TXN-8820A301",
                source_account_id=alex_checking.id,
                dest_account_id=marcus_checking.id,
                amount=8500.00,
                transaction_type="transfer",
                category="Transfer",
                description="IMPS to Marcus Vance - Architectural Blueprint consulting",
                status="completed",
                timestamp=now - timedelta(days=20, hours=6)
            ),
        ]
        db.session.add_all(sample_txns)

        # 7. Activity Logs
        logs = [
            ActivityLog(user_id=alex.id, action="Session Login", details="Chrome Web - Mumbai Gateway", timestamp=now - timedelta(hours=1)),
            ActivityLog(user_id=alex.id, action="Funds Deposited", details="NEFT ₹95,000.00 received", timestamp=now - timedelta(days=2)),
            ActivityLog(user_id=alex.id, action="Card Setting Updated", details="Daily limit set to ₹50,000.00", timestamp=now - timedelta(days=8)),
            ActivityLog(user_id=alex.id, action="Security: PIN Verified", details="Transaction security check passed", timestamp=now - timedelta(days=10)),
        ]
        db.session.add_all(logs)

        db.session.commit()
        print("NeoBank Database seeded with INR currency successfully!")
        print("Demo Account:")
        print("  Username: alex.mercer")
        print("  Password: password123")
        print("  PIN:      1234")

if __name__ == '__main__':
    seed_database()

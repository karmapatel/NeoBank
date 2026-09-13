"""
Supabase Connection Diagnostic Tool for NeoBank
Run this script to verify your Supabase PostgreSQL and API connection:
    python test_supabase_connection.py
"""

import os
import sys
from dotenv import load_dotenv
from sqlalchemy import text

# Load environment variables from .env
load_dotenv()

from supabase_client import get_database_uri, get_engine_options, get_supabase_client, is_supabase_configured

def mask_uri(uri: str) -> str:
    """Masks credentials in database URI for safe terminal logging."""
    if '@' in uri:
        try:
            proto_and_creds, host_part = uri.split('@', 1)
            proto = proto_and_creds.split('://')[0] if '://' in proto_and_creds else 'postgresql'
            return f"{proto}://****:****@{host_part}"
        except Exception:
            return "postgresql://****@****"
    return uri

def run_diagnostics():
    print("=" * 70)
    print("  NeoBank - Supabase & PostgreSQL Connection Diagnostic")
    print("=" * 70)

    # 1. Check .env file
    env_exists = os.path.exists('.env')
    print(f"\n[1] Environment File Check:")
    if env_exists:
        print("    [OK] .env file found in project root.")
    else:
        print("    [!] .env file not found. Copy .env.example to .env to configure credentials.")

    # 2. Database URI Resolution
    db_uri = get_database_uri()
    masked = mask_uri(db_uri)
    is_postgres = 'postgresql' in db_uri or 'postgres' in db_uri

    print(f"\n[2] Database Configuration:")
    print(f"    Resolved URI: {masked}")
    print(f"    Engine:       {'Supabase / PostgreSQL' if is_postgres else 'SQLite (Local Fallback)'}")

    # 3. Test Database Connection
    print(f"\n[3] Testing Database Connection...")
    from app import create_app
    from models import db

    app = create_app()
    with app.app_context():
        try:
            # Perform a test ping
            result = db.session.execute(text("SELECT 1;")).scalar()
            if result == 1:
                print("    [OK] Connection established successfully!")

            # Retrieve database version
            try:
                version_query = text("SELECT version();") if is_postgres else text("SELECT sqlite_version();")
                version_info = db.session.execute(version_query).scalar()
                print(f"    [OK] Database Version: {version_info.split(',')[0] if version_info else 'Unknown'}")
            except Exception as e:
                print(f"    [-] Could not fetch version: {e}")

            # Inspect existing tables
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            print(f"    [OK] Tables in Database ({len(tables)}): {', '.join(tables) if tables else 'None (run python seed.py or python app.py to initialize)'}")

            if 'users' in tables:
                from models import User, Account, Transaction
                user_count = User.query.count()
                acc_count = Account.query.count()
                txn_count = Transaction.query.count()
                print(f"    [*] Current Stats -> Users: {user_count} | Accounts: {acc_count} | Transactions: {txn_count}")

        except Exception as err:
            print(f"    [FAIL] Database connection failed!")
            print(f"    [!] Error: {err}\n")
            print("    Troubleshooting Tips:")
            print("    1. Check your password in DATABASE_URL. If it contains special characters (@, #, etc.), use URL encoding (e.g. %40 for @) or use individual variables (SUPABASE_DB_PASSWORD).")
            print("    2. In Supabase: Project Settings -> Database -> Connection string -> choose URI (direct on 5432 or pooler on 6543/5432).")
            print("    3. Ensure your network allows outbound connections to db.<project-ref>.supabase.co on port 5432 / 6543.")
            return False

    # 4. Supabase API Client Check (Optional)
    print(f"\n[4] Testing Supabase Python Client (Optional API SDK):")
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_KEY')

    if supabase_url and supabase_key:
        client = get_supabase_client()
        if client:
            print(f"    [OK] Supabase Client initialized for: {supabase_url}")
        else:
            print("    [!] Supabase client initialization returned None.")
    else:
        print("    [-] SUPABASE_URL / SUPABASE_KEY not set in .env (only needed if using Supabase Auth/Storage SDK).")

    print("\n" + "=" * 70)
    if is_postgres:
        print("  STATUS: Connected to Supabase / PostgreSQL!")
        print("  To initialize / seed tables in Supabase, run:")
        print("      python seed.py")
        print("  To start the application, run:")
        print("      python app.py")
    else:
        print("  STATUS: Currently using local SQLite database.")
        print("  To connect to Supabase:")
        print("  1. Open the .env file.")
        print("  2. Set DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres")
        print("  3. Run this script again: python test_supabase_connection.py")
    print("=" * 70 + "\n")
    return True

if __name__ == '__main__':
    success = run_diagnostics()
    sys.exit(0 if success else 1)

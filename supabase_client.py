import os
import urllib.parse
from dotenv import load_dotenv

# Load .env file automatically
load_dotenv()

def get_database_uri():
    """
    Resolves the SQLAlchemy database connection URI from environment variables.
    Priority:
    1. DATABASE_URL or SUPABASE_DB_URL
    2. Discrete parameters (SUPABASE_DB_USER, SUPABASE_DB_PASSWORD, SUPABASE_DB_HOST, etc.)
    3. Default fallback to local SQLite (sqlite:///neobank.db)
    """
    raw_uri = os.getenv('DATABASE_URL') or os.getenv('SUPABASE_DB_URL')
    
    if raw_uri and raw_uri.strip():
        uri = raw_uri.strip()
        # SQLAlchemy 1.4+ deprecated 'postgres://' in favor of 'postgresql://' or 'postgresql+psycopg2://'
        if uri.startswith('postgres://'):
            uri = uri.replace('postgres://', 'postgresql+psycopg2://', 1)
        elif uri.startswith('postgresql://') and not uri.startswith('postgresql+'):
            uri = uri.replace('postgresql://', 'postgresql+psycopg2://', 1)
        return uri

    # Check discrete parameters
    db_user = os.getenv('SUPABASE_DB_USER')
    db_password = os.getenv('SUPABASE_DB_PASSWORD')
    db_host = os.getenv('SUPABASE_DB_HOST')
    db_port = os.getenv('SUPABASE_DB_PORT', '5432')
    db_name = os.getenv('SUPABASE_DB_NAME', 'postgres')

    if db_host and db_user and db_password:
        # Quote password to prevent issues with special characters (@, #, %, etc.)
        encoded_password = urllib.parse.quote_plus(db_password)
        encoded_user = urllib.parse.quote_plus(db_user)
        return f"postgresql+psycopg2://{encoded_user}:{encoded_password}@{db_host}:{db_port}/{db_name}"

    # Default fallback for local development
    return 'sqlite:///neobank.db'


def get_engine_options(db_uri):
    """
    Returns engine options tailored for PostgreSQL (Supabase) vs SQLite.
    For PostgreSQL / Supabase, enables pool_pre_ping and pool_recycle
    to prevent PgBouncer / idle connection drops.
    """
    if db_uri and ('postgresql' in db_uri or 'postgres' in db_uri):
        return {
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'pool_size': 10,
            'max_overflow': 20
        }
    return {}


_supabase_client = None

def get_supabase_client():
    """
    Returns an initialized Supabase Python SDK Client if SUPABASE_URL and SUPABASE_KEY are provided.
    Returns None if credentials are missing or supabase library is not available.
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_KEY')

    if not supabase_url or not supabase_key:
        return None

    try:
        from supabase import create_client, Client
        _supabase_client = create_client(supabase_url.strip(), supabase_key.strip())
        return _supabase_client
    except Exception as e:
        print(f"[Supabase Client Warning] Could not initialize Supabase Client: {e}")
        return None


def is_supabase_configured():
    """Returns True if a remote Supabase / Postgres connection or API is configured."""
    db_uri = get_database_uri()
    has_postgres = 'postgresql' in db_uri or 'postgres' in db_uri
    has_api = bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_KEY'))
    return has_postgres or has_api

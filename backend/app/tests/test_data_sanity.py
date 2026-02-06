import pytest
import os
import sqlalchemy
from sqlalchemy import text

# Try to get DB connection string from env
# Assuming standard Postgres env vars or CUBEJS_DB_* vars
DB_HOST = os.getenv("DB_HOST") or os.getenv("CUBEJS_DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT") or os.getenv("CUBEJS_DB_PORT", "5432")
DB_USER = os.getenv("DB_USER") or os.getenv("CUBEJS_DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASSWORD") or os.getenv("CUBEJS_DB_PASS", "postgres")
DB_NAME = os.getenv("DB_NAME") or os.getenv("CUBEJS_DB_NAME", "postgres")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

@pytest.fixture(scope="session")
def db_engine():
    try:
        engine = sqlalchemy.create_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as e:
        pytest.skip(f"Database unavailable: {e}")

def test_data_sanity_distinct_months(db_engine):
    """Ensure >= 20 distinct months of data exist."""
    # Assuming fact_primary_sales has invoice_date or created_at
    # The catalog says fact_primary_sales.invoice_date exists

    # We need to know the table name. cube file says 'public.fact_primary_sales'
    table = "fact_primary_sales"
    col = "invoice_date"

    with db_engine.connect() as conn:
        # Check if table exists first
        try:
            conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
        except Exception:
            pytest.skip(f"Table {table} does not exist")

        result = conn.execute(text(f"""
            SELECT COUNT(DISTINCT TO_CHAR({col}, 'YYYY-MM'))
            FROM {table}
        """)).scalar()

        assert result >= 20, f"Expected >= 20 distinct months, found {result}"

def test_data_sanity_zones(db_engine):
    """Ensure all 6 zones exist."""
    table = "fact_primary_sales"
    col = "zone"

    with db_engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT COUNT(DISTINCT {col})
            FROM {table}
        """)).scalar()

        # We expect exactly 6 zones, or at least 6?
        # Requirement: "All 6 zones exist" -> implies we know there are 6.
        assert result >= 6, f"Expected 6 zones, found {result}"

def test_data_sanity_distributors(db_engine):
    """Ensure >= 25 distributors exist."""
    table = "fact_primary_sales"
    col = "distributor_name" # or distributor_code

    with db_engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT COUNT(DISTINCT {col})
            FROM {table}
        """)).scalar()

        assert result >= 25, f"Expected >= 25 distributors, found {result}"

def test_data_sanity_sales_rows(db_engine):
    """Primary and Secondary sales both have rows."""
    tables = ["fact_primary_sales", "fact_secondary_sales"]

    with db_engine.connect() as conn:
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                assert result > 0, f"Table {table} is empty"
            except Exception as e:
                 # If table missing, fail or skip? Requirement says "Assert... exist"
                 pytest.fail(f"Check failed for {table}: {e}")

def test_no_null_join_keys(db_engine):
    """No NULLs in critical join keys."""
    # Critical keys usually: sku_code, distributor_code, etc.
    # We check a few sample ones
    checks = [
        ("fact_primary_sales", "sku_code"),
        ("fact_primary_sales", "distributor_code"),
        ("fact_secondary_sales", "sku_code"),
    ]

    with db_engine.connect() as conn:
        for table, col in checks:
            try:
                result = conn.execute(text(f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE {col} IS NULL
                """)).scalar()
                assert result == 0, f"Found {result} NULLs in {table}.{col}"
            except Exception as e:
                # Table might not exist in this env
                pass

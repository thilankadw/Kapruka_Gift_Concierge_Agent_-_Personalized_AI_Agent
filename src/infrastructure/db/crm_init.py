"""
CRM database initialization.

Creates CRM tables via Supabase PostgreSQL schema.
Tables are created by sql/supabase_schema.sql (applied via ``make init-supabase``).
This module provides helpers to verify the schema is present.
"""

from loguru import logger
from sqlalchemy import text

from .sql_client import get_sql_engine


def ensure_crm_schema_compatibility():
    """Apply lightweight compatibility fixes for existing CRM tables."""
    engine = get_sql_engine()

    with engine.begin() as conn:
        active_type = conn.execute(
            text("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'users'
                  AND column_name = 'active'
            """)
        ).scalar()

        if active_type and active_type != "boolean":
            conn.execute(text("""
                ALTER TABLE users
                ALTER COLUMN active DROP DEFAULT
            """))
            conn.execute(text("""
                ALTER TABLE users
                ALTER COLUMN active TYPE BOOLEAN
                USING (active <> 0)
            """))
            conn.execute(text("""
                ALTER TABLE users
                ALTER COLUMN active SET DEFAULT TRUE
            """))
            logger.info("✓ Migrated users.active column to BOOLEAN")


def init_crm_schema():
    """
    Verify CRM schema exists in Supabase PostgreSQL.

    CRM tables are created as part of the full Supabase schema
    (``supabase_schema.sql``). This function is kept for backward
    compatibility and applies compatibility fixes for existing tables.
    """
    if check_crm_schema():
        ensure_crm_schema_compatibility()
        logger.info("✓ CRM schema already exists in Supabase")
    else:
        logger.warning(
            "⚠️  CRM tables missing — run 'make init-supabase' to create them"
        )


def check_crm_schema() -> bool:
    """
    Check if all required CRM tables exist in PostgreSQL.

    Returns:
        True if all required tables exist
    """
    engine = get_sql_engine()
    required_tables = ["users"]

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename IN ('users')
            """)
        )
        existing = {row[0] for row in result}

    missing = set(required_tables) - existing

    if missing:
        logger.warning(f"Missing CRM tables: {missing}")
        return False

    logger.info(f"✓ All CRM tables exist: {existing}")
    return True


if __name__ == "__main__":
    if check_crm_schema():
        ensure_crm_schema_compatibility()
        logger.success("✓ CRM schema already exists")
    else:
        logger.warning("⚠️  CRM tables missing — run 'make init-supabase'")

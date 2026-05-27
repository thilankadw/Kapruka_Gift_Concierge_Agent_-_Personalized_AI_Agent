"""
CRM and logistics database initialization helpers.

Tables are created by ``sql/supabase_schema.sql`` / ``supabase_schema.py``
through the Supabase schema init flow. This module verifies the required
tables are present and applies lightweight compatibility fixes for older
schemas.
"""

from loguru import logger
from sqlalchemy import text

from .sql_client import get_sql_engine


REQUIRED_CRM_TABLES = [
    "users",
    "delivery_zones",
    "delivery_slots",
    "courier_profiles",
    "product_delivery_rules",
    "delivery_history",
]


def ensure_crm_schema_compatibility():
    """Apply lightweight compatibility fixes for existing CRM tables."""
    engine = get_sql_engine()

    with engine.begin() as conn:
        active_type = conn.execute(
            text(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'users'
                  AND column_name = 'active'
                """
            )
        ).scalar()

        if active_type and active_type != "boolean":
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ALTER COLUMN active DROP DEFAULT
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ALTER COLUMN active TYPE BOOLEAN
                    USING (active <> 0)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ALTER COLUMN active SET DEFAULT TRUE
                    """
                )
            )
            logger.info("✓ Migrated users.active column to BOOLEAN")

        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS province TEXT"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT"))


def init_crm_schema():
    """
    Verify CRM + logistics schema exists in Supabase PostgreSQL.

    The actual table creation is handled by the full Supabase schema init flow.
    This function is kept for backward compatibility and applies compatibility
    fixes for existing tables.
    """
    if check_crm_schema():
        ensure_crm_schema_compatibility()
        logger.info("✓ CRM + logistics schema already exists in Supabase")
    else:
        logger.warning(
            "⚠️  CRM/logistics tables missing — run 'make init-supabase' to create them"
        )


def check_crm_schema() -> bool:
    """
    Check if all required CRM and logistics tables exist in PostgreSQL.

    Returns:
        True if all required tables exist
    """
    engine = get_sql_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename = ANY(:table_names)
                """
            ),
            {"table_names": REQUIRED_CRM_TABLES},
        )
        existing = {row[0] for row in result}

    missing = set(REQUIRED_CRM_TABLES) - existing

    if missing:
        logger.warning(f"Missing CRM/logistics tables: {missing}")
        return False

    logger.info(f"✓ All CRM/logistics tables exist: {sorted(existing)}")
    return True


if __name__ == "__main__":
    if check_crm_schema():
        ensure_crm_schema_compatibility()
        logger.success("✓ CRM + logistics schema already exists")
    else:
        logger.warning("⚠️  CRM/logistics tables missing — run 'make init-supabase'")

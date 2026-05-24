"""Public database exports for SQL, Supabase, and Qdrant helpers."""

from importlib import import_module


_EXPORTS = {
    # sql_client
    "create_tables": (".sql_client", "create_tables"),
    "get_session": (".sql_client", "get_session"),
    "get_sql_engine": (".sql_client", "get_sql_engine"),
    "test_connection": (".sql_client", "test_connection"),
    # supabase_client
    "check_pgvector_installed": (".supabase_client", "check_pgvector_installed"),
    "get_supabase_client": (".supabase_client", "get_supabase_client"),
    "get_supabase_engine": (".supabase_client", "get_supabase_engine"),
    "get_supabase_session": (".supabase_client", "get_supabase_session"),
    "init_supabase_schema": (".supabase_client", "init_supabase_schema"),
    "set_user_context": (".supabase_client", "set_user_context"),
    "validate_schema_dimensions": (".supabase_client", "validate_schema_dimensions"),
    # qdrant_client
    "collection_exists": (".qdrant_client", "collection_exists"),
    "collection_info": (".qdrant_client", "collection_info"),
    "count_points": (".qdrant_client", "count_points"),
    "delete_collection": (".qdrant_client", "delete_collection"),
    "ensure_collection": (".qdrant_client", "ensure_collection"),
    "ensure_kb_ingested": (".qdrant_client", "ensure_kb_ingested"),
    "get_qdrant_client": (".qdrant_client", "get_qdrant_client"),
    "search_chunks": (".qdrant_client", "search_chunks"),
    "upsert_chunks": (".qdrant_client", "upsert_chunks"),
}


__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Lazily resolve public database exports on first access."""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    """Expose lazy exports to introspection tools."""
    return sorted(set(globals()) | set(__all__))

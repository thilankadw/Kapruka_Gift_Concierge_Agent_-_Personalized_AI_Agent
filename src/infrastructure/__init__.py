"""Public infrastructure exports for the Kapruka agent.

This package uses lazy attribute loading so ``import infrastructure`` does not
eagerly import every dependency-heavy submodule at import time.
"""

from importlib import import_module


_EXPORTS = {
    # config
    "PROVIDER": (".config", "PROVIDER"),
    "MODEL_TIER": (".config", "MODEL_TIER"),
    "ROUTER_MODEL": (".config", "ROUTER_MODEL"),
    "ROUTER_PROVIDER": (".config", "ROUTER_PROVIDER"),
    "EXTRACTOR_MODEL": (".config", "EXTRACTOR_MODEL"),
    "EXTRACTOR_PROVIDER": (".config", "EXTRACTOR_PROVIDER"),
    "CHAT_MODEL": (".config", "CHAT_MODEL"),
    "CHAT_PROVIDER": (".config", "CHAT_PROVIDER"),
    "OPENAI_CHAT_MODEL": (".config", "OPENAI_CHAT_MODEL"),
    "EMBEDDING_MODEL": (".config", "EMBEDDING_MODEL"),
    "EMBEDDING_DIM": (".config", "EMBEDDING_DIM"),
    "get_chat_model": (".config", "get_chat_model"),
    "get_embedding_model": (".config", "get_embedding_model"),
    "load_faqs": (".config", "load_faqs"),
    "get_api_key": (".config", "get_api_key"),
    "validate": (".config", "validate"),
    "dump": (".config", "dump"),
    "get_all_models": (".config", "get_all_models"),
    "get_config": (".config", "get_config"),
    # db
    "check_pgvector_installed": (".db", "check_pgvector_installed"),
    "collection_exists": (".db", "collection_exists"),
    "collection_info": (".db", "collection_info"),
    "count_points": (".db", "count_points"),
    "create_tables": (".db", "create_tables"),
    "delete_collection": (".db", "delete_collection"),
    "ensure_collection": (".db", "ensure_collection"),
    "ensure_kb_ingested": (".db", "ensure_kb_ingested"),
    "get_qdrant_client": (".db", "get_qdrant_client"),
    "get_session": (".db", "get_session"),
    "get_sql_engine": (".db", "get_sql_engine"),
    "get_supabase_client": (".db", "get_supabase_client"),
    "get_supabase_engine": (".db", "get_supabase_engine"),
    "get_supabase_session": (".db", "get_supabase_session"),
    "init_supabase_schema": (".db", "init_supabase_schema"),
    "search_chunks": (".db", "search_chunks"),
    "set_user_context": (".db", "set_user_context"),
    "test_connection": (".db", "test_connection"),
    "upsert_chunks": (".db", "upsert_chunks"),
    "validate_schema_dimensions": (".db", "validate_schema_dimensions"),
    # llm
    "get_chat_llm": (".llm", "get_chat_llm"),
    "get_router_llm": (".llm", "get_router_llm"),
    "get_extractor_llm": (".llm", "get_extractor_llm"),
    "get_default_embeddings": (".llm", "get_default_embeddings"),
    # log
    "setup_logging": (".log", "setup_logging"),
    # observability
    "get_langfuse": (".observability", "get_langfuse"),
    "fetch_prompt": (".observability", "fetch_prompt"),
    "observe": (".observability", "observe"),
    "update_current_trace": (".observability", "update_current_trace"),
    "update_current_observation": (".observability", "update_current_observation"),
    "flush": (".observability", "flush"),
}


__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Lazily resolve public infrastructure exports on first access."""
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

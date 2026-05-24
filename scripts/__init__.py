"""Public exports for runnable project scripts."""

from importlib import import_module


_EXPORTS = {
    "ingest_to_qdrant_main": (".ingest_to_qdrant", "main"),
    "init_supabase_main": (".init_supabase", "main"),
    "rebuild_cag_cache": (".rebuild_cag_cache", "rebuild_cag_cache"),
    "seed_crm_unified_main": (".seed_crm_unified", "main"),
    "test_supabase_main": (".test_supabase", "main"),
}


__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Lazily resolve public script entry points on first access."""
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

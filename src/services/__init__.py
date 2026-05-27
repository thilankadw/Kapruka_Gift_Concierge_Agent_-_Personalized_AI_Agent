"""Public service exports with lazy loading."""

from importlib import import_module


_EXPORTS = {
    "ChunkingService": (".ingest_services", "ChunkingService"),
    "KaprukaWebCrawler": (".ingest_services", "KaprukaWebCrawler"),
    "LOADER_MAP": (".ingest_services", "LOADER_MAP"),
    "STRATEGY_MAP": (".ingest_services", "STRATEGY_MAP"),
    "count_tokens": (".ingest_services", "count_tokens"),
    "embed_texts": (".ingest_services", "embed_texts"),
    "fixed_chunk": (".ingest_services", "fixed_chunk"),
    "late_chunk_index": (".ingest_services", "late_chunk_index"),
    "late_chunk_split": (".ingest_services", "late_chunk_split"),
    "load_jsonl_docs": (".ingest_services", "load_jsonl_docs"),
    "load_kb_docs": (".ingest_services", "load_kb_docs"),
    "load_markdown_docs": (".ingest_services", "load_markdown_docs"),
    "parent_child_chunk": (".ingest_services", "parent_child_chunk"),
    "run_ingest": (".ingest_services", "run_ingest"),
    "semantic_chunk": (".ingest_services", "semantic_chunk"),
    "sliding_chunk": (".ingest_services", "sliding_chunk"),
}


__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))

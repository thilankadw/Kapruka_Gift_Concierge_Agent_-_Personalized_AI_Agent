"""Public memory exports with lazy loading.

Importing ``memory`` should not eagerly open Supabase-backed stores during test
collection or when only the schema types are needed.
"""

from importlib import import_module


_EXPORTS = {
    "ConversationTurn": (".schemas", "ConversationTurn"),
    "MemoryFact": (".schemas", "MemoryFact"),
    "ReminderIntent": (".schemas", "ReminderIntent"),
    "Episode": (".schemas", "Episode"),
    "Procedure": (".schemas", "Procedure"),
    "ShortTermStore": (".schemas", "ShortTermStore"),
    "LongTermStore": (".schemas", "LongTermStore"),
    "Embedder": (".schemas", "Embedder"),
    "Clock": (".schemas", "Clock"),
    "ShortTermMemoryStore": (".st_store", "ShortTermMemoryStore"),
    "LongTermMemoryStore": (".lt_store", "LongTermMemoryStore"),
    "EpisodicMemoryStore": (".episodic_store", "EpisodicMemoryStore"),
    "create_episode_from_turns": (".episodic_store", "create_episode_from_turns"),
    "ProceduralMemoryStore": (".procedural_store", "ProceduralMemoryStore"),
    "MemoryDistiller": (".memory_ops", "MemoryDistiller"),
    "MemoryRecaller": (".memory_ops", "MemoryRecaller"),
    "MemoryForgetService": (".memory_ops", "MemoryForgetService"),
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

"""CRM service exports with lazy loading."""

from importlib import import_module


_EXPORTS = {
    "CRMDatabaseClient": (".crm_db_client", "CRMDatabaseClient"),
    "get_crm_client": (".crm_db_client", "get_crm_client"),
    "KaprukaDataGenerator": (".llm_data_generator", "KaprukaDataGenerator"),
    "get_data_generator": (".llm_data_generator", "get_data_generator"),
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

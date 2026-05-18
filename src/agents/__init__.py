"""
Agent package exports for Kapruka tools.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools import CRMTool, RAGTool

__all__ = [
    "CRMTool",
    "RAGTool",
]


def __getattr__(name: str):
    if name == "CRMTool":
        from .tools import CRMTool

        return CRMTool
    if name == "RAGTool":
        from .tools import RAGTool

        return RAGTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

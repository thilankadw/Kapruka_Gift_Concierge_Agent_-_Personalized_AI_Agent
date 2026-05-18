"""
Tool exports for the Kapruka agent package.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .crm_tool import CRMTool
    from .rag_tool import RAGTool

__all__ = [
    "CRMTool",
    "RAGTool",
]


def __getattr__(name: str):
    if name == "CRMTool":
        from .crm_tool import CRMTool

        return CRMTool
    if name == "RAGTool":
        from .rag_tool import RAGTool

        return RAGTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

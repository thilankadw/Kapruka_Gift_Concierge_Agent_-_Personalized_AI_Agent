"""
Pydantic request / response models for the Kapruka Gift Concierge API.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Request Models ────────────────────────────────────────────

class ChatRequest(BaseModel):
    """POST /chat - send a message to the agent."""
    user_message: str = Field(..., min_length=1, description="The user's message")
    user_id: str = Field(..., min_length=1, description="Unique user identifier such as a phone number or CRM user ID")
    session_id: str = Field(default="default", description="Conversation session identifier")


class MemoryClearRequest(BaseModel):
    """POST /memory/clear - clear short-term session memory."""
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)


# ── Response Models ───────────────────────────────────────────

class ChatResponse(BaseModel):
    """Response from the agent after processing a message."""
    answer: str = Field(..., description="The agent's response to the user")
    route: str = Field(..., description="Primary route taken: crm, rag, web_search, or direct")
    routes: List[str] = Field(default_factory=list, description="All routes taken for compound multi-route queries")
    action: Optional[str] = Field(None, description="CRM sub-action when the primary route is crm")
    tool_output: str = Field("", description="Raw tool output for debugging or UI inspection")
    memory_context: str = Field("", description="Memory context injected into the agent response")
    latency_ms: int = Field(0, description="End-to-end processing time in milliseconds")


class ToolStatus(BaseModel):
    """Status of each optional tool."""
    crm: bool = False
    rag: bool = False
    web_search: bool = False


class HealthResponse(BaseModel):
    """GET /health - system liveness and tool readiness."""
    status: str = "ok"
    tools: ToolStatus = Field(default_factory=ToolStatus)


class FactItem(BaseModel):
    """A single long-term memory fact."""
    text: str
    tags: List[str] = Field(default_factory=list)
    score: float = 0.0


class MemoryResponse(BaseModel):
    """GET /memory/{user_id} - a user's stored long-term facts."""
    user_id: str
    fact_count: int = 0
    facts: List[FactItem] = Field(default_factory=list)


class MemoryClearResponse(BaseModel):
    """POST /memory/clear - confirmation response."""
    cleared: bool = True
    user_id: str
    session_id: str


class GraphEdge(BaseModel):
    """A single edge in the LangGraph topology."""
    source: str
    target: str
    conditional: bool = False
    label: Optional[str] = None


class GraphResponse(BaseModel):
    """GET /graph - LangGraph topology."""
    mermaid: str = Field(..., description="Mermaid diagram text")
    nodes: List[str] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


class StreamEvent(BaseModel):
    """A single SSE event from POST /chat/stream."""
    node: str
    status: str = "done"
    data: Dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Error response body."""
    detail: str

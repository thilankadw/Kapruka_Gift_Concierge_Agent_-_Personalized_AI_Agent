"""
Kapruka agent orchestrator built on a LangGraph StateGraph.

Topology:
    recall -> supervisor -> [profile_agent, catalog_agent, concierge_agent]
                           -> merge_responses -> save_memory -> END

Route mapping:
    crm        -> profile_agent
    rag        -> catalog_agent
    web_search -> concierge_agent
    direct     -> concierge_agent

The router can emit multiple route decisions for compound requests. In that
case the graph fans out to multiple specialist nodes and then merges their
results into one customer-facing reply.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from loguru import logger

from agents.prompts.agent_prompts import (
    build_admin_agent_prompt as build_profile_agent_prompt,
    build_clinical_agent_prompt as build_catalog_agent_prompt,
    build_direct_agent_prompt as build_concierge_agent_prompt,
    build_merge_prompt as build_merge_agent_prompt,
)
from agents.router import QueryRouter
from agents.state import AgentState
from infrastructure.observability import observe
from memory.schemas import ConversationTurn

PROFILE_NODE = "profile_agent"
CATALOG_NODE = "catalog_agent"
CONCIERGE_NODE = "concierge_agent"

ROUTE_TO_NODE = {
    "crm": PROFILE_NODE,
    "rag": CATALOG_NODE,
    "web_search": CONCIERGE_NODE,
    "direct": CONCIERGE_NODE,
}


@dataclass
class AgentResponse:
    """Complete agent response with metadata for the UI and notebooks."""

    answer: str
    route: str = "direct"
    routes: List[str] = field(default_factory=list)
    action: Optional[str] = None
    tool_output: str = ""
    memory_context: str = ""
    latency_ms: int = 0


class AgentOrchestrator:
    """
    Orchestrates the Kapruka multi-agent shopping assistant.

    The public surface stays stable while the internal graph routes customer
    profile/logistics work, product knowledge work, and direct concierge work
    to the matching specialist node.
    """

    def __init__(
        self,
        llm_chat: Any,
        llm_router: Any,
        st_store: Any,
        lt_store: Any,
        recaller: Any,
        distiller: Any,
        crm_tool: Optional[Any] = None,
        rag_tool: Optional[Any] = None,
        web_tool: Optional[Any] = None,
    ) -> None:
        self.llm_chat = llm_chat
        self.st_store = st_store
        self.lt_store = lt_store
        self.recaller = recaller
        self.distiller = distiller

        self.crm_tool = crm_tool
        self.rag_tool = rag_tool
        self.web_tool = web_tool

        self.router = QueryRouter(llm_router)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Construct the LangGraph state machine for the Kapruka assistant."""
        workflow = StateGraph(AgentState)

        workflow.add_node("recall", self.recall_node)
        workflow.add_node("supervisor", self.supervisor_node)
        workflow.add_node(PROFILE_NODE, self.profile_agent_node)
        workflow.add_node(CATALOG_NODE, self.catalog_agent_node)
        workflow.add_node(CONCIERGE_NODE, self.concierge_agent_node)
        workflow.add_node("merge_responses", self.merge_responses_node)
        workflow.add_node("save_memory", self.store_and_distill_node)

        workflow.set_entry_point("recall")
        workflow.add_edge("recall", "supervisor")
        workflow.add_conditional_edges(
            "supervisor",
            self.supervisor_routing,
            {
                PROFILE_NODE: PROFILE_NODE,
                CATALOG_NODE: CATALOG_NODE,
                CONCIERGE_NODE: CONCIERGE_NODE,
            },
        )

        workflow.add_edge(PROFILE_NODE, "merge_responses")
        workflow.add_edge(CATALOG_NODE, "merge_responses")
        workflow.add_edge(CONCIERGE_NODE, "merge_responses")
        workflow.add_edge("merge_responses", "save_memory")
        workflow.add_edge("save_memory", END)

        return workflow.compile()

    @observe(name="node_recall")
    def recall_node(self, state: AgentState) -> Dict[str, Any]:
        """Load short-term conversation context and long-term memory facts."""
        user_message = state["messages"][-1].content
        user_id = state["user_id"]
        session_id = state["session_id"]

        try:
            st_turns, lt_facts = self.recaller.recall(
                user_id=user_id,
                session_id=session_id,
                query=user_message,
            )
            memory_context = self.recaller.format_context(st_turns)
            semantic_facts = [
                fact.to_dict() if hasattr(fact, "to_dict") else vars(fact)
                for fact in lt_facts
            ]
            return {
                "memory_context": memory_context,
                "semantic_facts": semantic_facts,
            }
        except Exception as exc:
            logger.warning("Recall node failed: {}", exc)
            return {"memory_context": "(memory offline)"}

    @observe(name="node_supervisor")
    def supervisor_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Classify intent and choose one or more Kapruka specialist routes.

        The router already understands the Kapruka domain. This node simply
        enriches the router input with memory and serializes the decisions into
        graph state.
        """
        user_message = state["messages"][-1].content
        memory_context = state.get("memory_context", "") or ""

        facts = state.get("semantic_facts", []) or []
        if facts:
            memory_context += "\n=== LONG-TERM FACTS ===\n"
            for fact in facts:
                memory_context += f"- {fact.get('text', '')}\n"

        decision_set = self.router.route(user_message, memory_context)
        route_decisions = [
            {
                "route": decision.route,
                "action": decision.action,
                "params": decision.params or {},
                "reasoning": decision.reasoning,
            }
            for decision in decision_set.decisions
        ]

        primary = route_decisions[0] if route_decisions else {"route": "direct"}
        return {
            "route_decisions": route_decisions,
            "route_decision": primary,
        }

    def supervisor_routing(self, state: AgentState) -> Union[str, List[str]]:
        """
        Convert router route labels into LangGraph node names.

        Single-route queries return one node name. Compound queries return a
        list so LangGraph can fan out into parallel branches.
        """
        decisions = state.get("route_decisions", []) or []
        if not decisions:
            return CONCIERGE_NODE

        node_names: List[str] = []
        seen: set[str] = set()
        for decision in decisions:
            route = decision.get("route", "direct")
            node_name = ROUTE_TO_NODE.get(route, CONCIERGE_NODE)
            if node_name not in seen:
                node_names.append(node_name)
                seen.add(node_name)

        if len(node_names) == 1:
            return node_names[0]
        return node_names

    @observe(name="node_profile_agent")
    def profile_agent_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Handle CRM-backed profile and structured logistics requests.

        This covers stable customer records and table-backed delivery queries.
        """
        decisions = state.get("route_decisions", []) or []
        crm_decision = next(
            (decision for decision in decisions if decision.get("route") == "crm"),
            state.get("route_decision", {}) or {},
        )
        action = crm_decision.get("action", "lookup_user")
        params = crm_decision.get("params", {})

        system_prompt = build_profile_agent_prompt()

        if not self.crm_tool:
            tool_output = "CRM tool unavailable."
        else:
            tool_output = self.crm_tool.dispatch(action, params)

        answer = self._generate_agent_response(state, system_prompt, tool_output)
        return {
            "messages": [AIMessage(content=answer)],
            "tool_output": tool_output,
            "final_answer": answer,
            "agent_outputs": [
                {"route": "crm", "tool_output": tool_output, "answer": answer}
            ],
        }

    @observe(name="node_catalog_agent")
    def catalog_agent_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Handle product-catalog, FAQ, and recommendation retrieval requests.
        """
        decisions = state.get("route_decisions", []) or []
        rag_decision = next(
            (decision for decision in decisions if decision.get("route") == "rag"),
            state.get("route_decision", {}) or {},
        )
        params = rag_decision.get("params", {})
        query = params.get("query", state["messages"][0].content)

        system_prompt = build_catalog_agent_prompt()

        facts = state.get("semantic_facts", []) or []
        kb_context = ""
        if facts:
            kb_context += "\n=== CUSTOMER PREFERENCES AND HISTORY ===\n"
            for fact in facts:
                kb_context += f"- {fact.get('text', '')}\n"

        if not self.rag_tool:
            tool_output = "RAG tool unavailable."
        else:
            tool_output = self.rag_tool.dispatch("search", {"query": query})

        answer = self._generate_agent_response(
            state,
            system_prompt,
            tool_output,
            extra_context=kb_context,
        )
        return {
            "messages": [AIMessage(content=answer)],
            "tool_output": tool_output,
            "final_answer": answer,
            "agent_outputs": [
                {"route": "rag", "tool_output": tool_output, "answer": answer}
            ],
        }

    @observe(name="node_concierge_agent")
    def concierge_agent_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Handle direct concierge replies and live external web lookups.
        """
        system_prompt = build_concierge_agent_prompt()

        decisions = state.get("route_decisions", []) or []
        web_decision = next(
            (
                decision
                for decision in decisions
                if decision.get("route") == "web_search"
            ),
            None,
        )

        tool_output = ""
        route_label = "direct"
        if web_decision and self.web_tool:
            params = web_decision.get("params", {})
            query = params.get("query", state["messages"][0].content)
            tool_output = self.web_tool.dispatch("search", {"query": query})
            route_label = "web_search"

        answer = self._generate_agent_response(state, system_prompt, tool_output)
        return {
            "messages": [AIMessage(content=answer)],
            "tool_output": tool_output,
            "final_answer": answer,
            "agent_outputs": [
                {
                    "route": route_label,
                    "tool_output": tool_output,
                    "answer": answer,
                }
            ],
        }

    @observe(name="node_merge_responses")
    def merge_responses_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Merge parallel specialist outputs into one reply.

        Single-route requests pass through without another model call.
        """
        agent_outputs = state.get("agent_outputs", []) or []
        if len(agent_outputs) <= 1:
            return {}

        logger.info("Merging {} agent outputs into unified response", len(agent_outputs))

        user_message = state["messages"][0].content
        memory_context = state.get("memory_context", "") or ""

        combined_tool_output = ""
        for output in agent_outputs:
            route = output.get("route", "unknown").upper()
            answer = output.get("answer", "")
            combined_tool_output += f"=== {route} RESULT ===\n{answer}\n\n"

        system_prompt = build_merge_agent_prompt()
        system_content = (
            f"{system_prompt}\n\n"
            f"=== MEMORY CONTEXT ===\n{memory_context}\n\n"
            f"=== AGENT RESULTS TO MERGE ===\n{combined_tool_output}"
        )

        response = self.llm_chat.invoke(
            [
                SystemMessage(content=system_content),
                HumanMessage(content=user_message),
            ]
        )
        merged_answer = response.content if hasattr(response, "content") else str(response)

        all_tool_output = "\n---\n".join(
            output.get("tool_output", "")
            for output in agent_outputs
            if output.get("tool_output")
        )
        return {
            "final_answer": merged_answer,
            "tool_output": all_tool_output,
            "messages": [AIMessage(content=merged_answer)],
        }

    @observe(name="node_save_memory")
    def store_and_distill_node(self, state: AgentState) -> Dict[str, Any]:
        """Persist the interaction and distill new long-term memory facts."""
        user_message = state["messages"][0].content
        answer = state["final_answer"]
        user_id = state["user_id"]
        session_id = state["session_id"]

        now = time.time()
        self.st_store.add(
            user_id,
            session_id,
            ConversationTurn(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=user_message,
                ts=now,
            ),
        )
        self.st_store.add(
            user_id,
            session_id,
            ConversationTurn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=answer,
                ts=now,
            ),
        )

        try:
            recent = self.st_store.recent(user_id, session_id, k=5)
            if self.distiller.should_distill(recent):
                logger.info("Distilling new facts for {}...", user_id)
                self.distiller.distill(user_id, recent)
                return {"should_distill": True}
        except Exception as exc:
            logger.warning("Distillation failed: {}", exc)

        return {"should_distill": False}

    def _generate_agent_response(
        self,
        state: AgentState,
        system_prompt: str,
        tool_output: str,
        extra_context: str = "",
    ) -> str:
        """Generate a specialist response from memory context and tool output."""
        user_message = state["messages"][-1].content
        memory_context = (state.get("memory_context", "") or "") + extra_context

        system_content = (
            f"{system_prompt}\n\n"
            f"=== MEMORY CONTEXT ===\n{memory_context}\n\n"
            f"=== TOOL OUTPUT ===\n{tool_output}"
        )

        response = self.llm_chat.invoke(
            [
                SystemMessage(content=system_content),
                HumanMessage(content=user_message),
            ]
        )
        return response.content if hasattr(response, "content") else str(response)

    @observe(name="agent_chat")
    def chat(self, user_message: str, user_id: str, session_id: str) -> AgentResponse:
        """Run the graph for one interaction."""
        t0 = time.time()

        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": user_id,
            "session_id": session_id,
            "agent_outputs": [],
        }

        final_state = self.graph.invoke(initial_state)
        latency = int((time.time() - t0) * 1000)

        route_decisions = final_state.get("route_decisions", []) or []
        all_routes = [decision.get("route", "direct") for decision in route_decisions]
        primary = route_decisions[0] if route_decisions else {"route": "direct"}

        return AgentResponse(
            answer=final_state["final_answer"],
            route=primary.get("route", "direct"),
            routes=all_routes,
            action=primary.get("action"),
            tool_output=final_state.get("tool_output", ""),
            memory_context=final_state.get("memory_context", ""),
            latency_ms=latency,
        )

    async def achat(
        self,
        user_message: str,
        user_id: str,
        session_id: str,
    ) -> AgentResponse:
        """Async version of chat() for non-blocking API usage."""
        t0 = time.time()

        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": user_id,
            "session_id": session_id,
            "agent_outputs": [],
        }

        final_state = await self.graph.ainvoke(initial_state)
        latency = int((time.time() - t0) * 1000)

        route_decisions = final_state.get("route_decisions", []) or []
        all_routes = [decision.get("route", "direct") for decision in route_decisions]
        primary = route_decisions[0] if route_decisions else {"route": "direct"}

        return AgentResponse(
            answer=final_state["final_answer"],
            route=primary.get("route", "direct"),
            routes=all_routes,
            action=primary.get("action"),
            tool_output=final_state.get("tool_output", ""),
            memory_context=final_state.get("memory_context", ""),
            latency_ms=latency,
        )


def build_agent(
    enable_crm: bool = True,
    enable_rag: bool = True,
    enable_web: bool = True,
) -> AgentOrchestrator:
    """Build the fully wired Kapruka agent orchestrator."""
    from infrastructure.llm import (
        get_chat_llm,
        get_default_embeddings,
        get_extractor_llm,
        get_router_llm,
    )
    from memory.lt_store import LongTermMemoryStore
    from memory.memory_ops import MemoryDistiller, MemoryRecaller
    from memory.st_store import ShortTermMemoryStore

    llm_chat = get_chat_llm(temperature=0)
    llm_router = get_router_llm(temperature=0)
    llm_extractor = get_extractor_llm(temperature=0)
    embedder = get_default_embeddings()

    st_store = ShortTermMemoryStore()
    lt_store = LongTermMemoryStore(embedder)
    recaller = MemoryRecaller(st_store, lt_store)
    distiller = MemoryDistiller(llm_extractor, lt_store)

    crm_tool = None
    if enable_crm:
        try:
            from agents.tools import CRMTool

            crm_tool = CRMTool()
            logger.info("CRM tool initialised")
        except Exception as exc:
            logger.warning("CRM tool unavailable: {}", exc)

    rag_tool = None
    if enable_rag:
        try:
            from agents.tools import RAGTool

            rag_tool = RAGTool(embedder=embedder, llm=llm_chat)
            logger.info("RAG tool initialised")
        except Exception as exc:
            logger.warning("RAG tool unavailable: {}", exc)

    web_tool = None
    if enable_web:
        try:
            from agents.tools import WebSearchTool

            web_tool = WebSearchTool()
            logger.info("Web search tool initialised")
        except Exception as exc:
            logger.warning("Web search tool unavailable: {}", exc)

    return AgentOrchestrator(
        llm_chat=llm_chat,
        llm_router=llm_router,
        st_store=st_store,
        lt_store=lt_store,
        recaller=recaller,
        distiller=distiller,
        crm_tool=crm_tool,
        rag_tool=rag_tool,
        web_tool=web_tool,
    )

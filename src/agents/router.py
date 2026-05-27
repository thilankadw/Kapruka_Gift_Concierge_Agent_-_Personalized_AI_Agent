"""
Query Router — LLM-based intent classification.

Takes a user message + memory context and returns a ``MultiRouteDecision``
containing one or more ``RouteDecision`` objects.  When the user query
contains multiple independent intents (e.g. "Check my appointments AND
what is the infection control policy?") the router returns multiple
routes so the orchestrator can fan out to parallel agent nodes.
"""

import json
from loguru import logger
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.prompts.agent_prompts import build_router_prompt
from infrastructure.observability import observe, update_current_observation

# Valid routes
VALID_ROUTES = {"crm", "rag", "web_search", "direct"}

# Valid CRM sub-actions
VALID_CRM_ACTIONS = {
    "lookup_user",
    "create_user",
    "update_user",
    "deactivate_user",
    "list_users",
    "get_delivery_zone",
    "list_delivery_slots",
    "search_couriers",
    "get_product_delivery_rule",
    "lookup_delivery_history",
    "check_delivery_coverage",
}

# Maximum routes per query (safety cap)
MAX_ROUTES = 3

SRI_LANKAN_DISTRICTS = (
    "ampara",
    "anuradhapura",
    "badulla",
    "batticaloa",
    "colombo",
    "galle",
    "gampaha",
    "hambantota",
    "jaffna",
    "kalutara",
    "kandy",
    "kegalle",
    "kilinochchi",
    "kurunegala",
    "mannar",
    "matale",
    "matara",
    "monaragala",
    "mullaitivu",
    "nuwara eliya",
    "polonnaruwa",
    "puttalam",
    "ratnapura",
    "trincomalee",
    "vavuniya",
)

LOGISTICS_PRODUCT_TYPES = (
    "cake",
    "flowers",
    "flower",
    "chocolates",
    "chocolate",
    "perfume",
    "gift hamper",
    "gift_hamper",
    "electronics",
    "gift voucher",
    "gift_voucher",
    "jewellery",
    "plants",
    "plant",
    "books",
    "book",
)


@dataclass
class RouteDecision:
    """
    A single routing decision for one intent.

    Attributes:
        route: Primary route (crm | rag | web_search | direct).
        confidence: Router's self-assessed confidence [0-1].
        reasoning: One-line explanation of the routing decision.
        action: CRM sub-action (only when route == crm).
        params: Extracted parameters for the tool.
    """

    route: str = "direct"
    confidence: float = 0.0
    reasoning: str = ""
    action: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiRouteDecision:
    """
    Container for one or more RouteDecision objects.

    Single-intent queries produce ``decisions`` with one element.
    Multi-intent queries (e.g. "book me an appointment AND tell me
    about infection control") produce multiple elements, enabling
    LangGraph fan-out to parallel agent nodes.
    """

    decisions: List[RouteDecision] = field(default_factory=list)

    @property
    def is_multi_route(self) -> bool:
        return len(self.decisions) > 1

    @property
    def primary(self) -> RouteDecision:
        """First (or only) decision — backward compatibility."""
        return self.decisions[0] if self.decisions else RouteDecision()


class QueryRouter:
    """
    Routes user queries to the appropriate tool path.

    Uses an LLM call with structured JSON output to classify intent.
    Falls back to ``direct`` on parse errors.
    """

    def __init__(self, llm: Any) -> None:
        """
        Args:
            llm: A LangChain ``ChatOpenAI`` (or compatible) instance.
        """
        self.llm = llm

    @observe(name="router", as_type="generation")
    def route(
        self,
        user_message: str,
        memory_context: str = "",
    ) -> MultiRouteDecision:
        """
        Classify user intent and extract parameters.

        Returns a ``MultiRouteDecision`` containing one or more
        ``RouteDecision`` objects.  For most queries only one route
        is returned; multi-route is triggered only when the user
        asks clearly separate questions in one message.

        Traced as a LangFuse **generation** so cost/tokens are captured.
        """
        system_prompt, user_prompt = build_router_prompt(
            user_message=user_message,
            memory_context=memory_context,
        )

        update_current_observation(
            input=user_prompt[:1000],
            model=self._model_name(),
        )

        try:
            response = self.llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            content = (
                response.content
                if hasattr(response, "content")
                else str(response)
            )

            # Extract token usage if available
            usage = {}
            if hasattr(response, "response_metadata"):
                meta = response.response_metadata or {}
                token_usage = meta.get("token_usage") or meta.get("usage", {})
                if token_usage:
                    usage = {
                        "input": token_usage.get("prompt_tokens", 0),
                        "output": token_usage.get("completion_tokens", 0),
                        "total": token_usage.get("total_tokens", 0),
                    }

            update_current_observation(
                output=content[:500],
                usage=usage if usage else None,
            )

        except Exception as exc:
            logger.error("Router LLM call failed: {}", exc)
            return MultiRouteDecision(decisions=[
                RouteDecision(
                    route="direct",
                    confidence=0.0,
                    reasoning=f"Router LLM error: {exc}",
                )
            ])

        parsed = self._parse_response(content)
        return self._postprocess_decisions(user_message, parsed)

    def _model_name(self) -> str:
        """Extract model name from the LLM for LangFuse metadata."""
        if hasattr(self.llm, "model_name"):
            return self.llm.model_name
        if hasattr(self.llm, "model"):
            return self.llm.model
        return "unknown"

    # ── parsing ───────────────────────────────────────────────

    def _parse_response(self, raw: str) -> MultiRouteDecision:
        """
        Parse the JSON response from the router LLM.

        Supports two formats:
          - Multi-route (new):  ``{"routes": [{...}, {...}]}``
          - Single-route (old): ``{"route": "crm", ...}``

        The old format is auto-wrapped into a single-element list
        for full backward compatibility.
        """
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        # Locate JSON object boundaries
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            logger.warning("Router output is not JSON; falling back to direct.")
            return MultiRouteDecision(decisions=[
                RouteDecision(route="direct", confidence=0.0,
                              reasoning="Failed to parse router output as JSON.")
            ])

        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            logger.warning("Router JSON parse error: {}", exc)
            return MultiRouteDecision(decisions=[
                RouteDecision(route="direct", confidence=0.0,
                              reasoning=f"JSON parse error: {exc}")
            ])

        # ── Normalise to a list of route dicts ──────────────────
        if "routes" in data and isinstance(data["routes"], list):
            # New multi-route format
            route_dicts = data["routes"][:MAX_ROUTES]
        else:
            # Old single-route format — wrap in list
            route_dicts = [data]

        # ── Build RouteDecision objects ──────────────────────────
        decisions: List[RouteDecision] = []
        seen_routes: set = set()

        for rd in route_dicts:
            route = rd.get("route", "direct")
            if route not in VALID_ROUTES:
                logger.warning("Invalid route '{}'; skipping.", route)
                continue
            # Deduplicate (same route appearing twice)
            if route in seen_routes:
                continue
            seen_routes.add(route)

            action = rd.get("action")
            if route == "crm" and action not in VALID_CRM_ACTIONS:
                logger.warning(
                    "Invalid CRM action '{}'; defaulting to lookup_user.", action
                )
                action = "lookup_user"

            decisions.append(RouteDecision(
                route=route,
                confidence=float(rd.get("confidence", 0.5)),
                reasoning=rd.get("reasoning", ""),
                action=action if route == "crm" else None,
                params=rd.get("params", {}),
            ))

        # Fallback if nothing valid was parsed
        if not decisions:
            decisions = [RouteDecision(route="direct", confidence=0.0,
                                       reasoning="No valid routes parsed.")]

        return MultiRouteDecision(decisions=decisions)

    def _postprocess_decisions(
        self,
        user_message: str,
        decision_set: MultiRouteDecision,
    ) -> MultiRouteDecision:
        """
        Recover common logistics-feasibility misroutes after LLM parsing.

        The logistics flow is backed by CRM/logistics tables, so delivery
        feasibility requests should not fall through to web_search or to the
        default lookup_user CRM action.
        """
        if not decision_set.decisions:
            return decision_set

        logistics_query = self._looks_like_logistics_query(user_message)
        live_external_query = self._looks_like_live_external_logistics_query(user_message)
        inferred_params = self._infer_logistics_params(user_message)
        inferred_action = self._infer_logistics_action(user_message)

        updated: List[RouteDecision] = []
        for decision in decision_set.decisions:
            route = decision.route
            action = decision.action
            params = dict(decision.params or {})

            if logistics_query and (route in {"direct", "web_search"}):
                # Keep live disruption queries on web_search; otherwise route to
                # the structured logistics flow when we have enough parameters.
                if not live_external_query and inferred_params.get("district"):
                    route = "crm"
                    action = inferred_action
                    params = {**inferred_params, **params}

            if route == "crm" and logistics_query:
                if action not in VALID_CRM_ACTIONS or action == "lookup_user":
                    action = inferred_action
                params = {**inferred_params, **params}
                params.pop("query", None)

            updated.append(
                RouteDecision(
                    route=route,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    action=action if route == "crm" else None,
                    params=params,
                )
            )

        return MultiRouteDecision(decisions=updated)

    @staticmethod
    def _looks_like_logistics_query(user_message: str) -> bool:
        message = user_message.lower()
        logistics_keywords = (
            "delivery",
            "deliver",
            "same-day",
            "same day",
            "express",
            "coverage",
            "feasible",
            "feasibility",
            "courier",
            "slot",
            "district",
            "arrival",
        )
        return any(keyword in message for keyword in logistics_keywords)

    @staticmethod
    def _looks_like_live_external_logistics_query(user_message: str) -> bool:
        message = user_message.lower()
        external_keywords = (
            "weather",
            "rain",
            "storm",
            "flood",
            "traffic",
            "road",
            "closure",
            "closed",
            "accident",
            "strike",
            "public announcement",
            "news",
        )
        return any(keyword in message for keyword in external_keywords)

    def _infer_logistics_action(self, user_message: str) -> str:
        message = user_message.lower()
        if any(keyword in message for keyword in ("history", "past deliveries", "delivery history")):
            return "lookup_delivery_history"
        if "courier" in message:
            return "search_couriers"
        if any(keyword in message for keyword in ("rule", "fragile", "temperature", "distance")):
            return "get_product_delivery_rule"
        if any(keyword in message for keyword in ("slot", "timeslot", "time slot")):
            return "list_delivery_slots"
        if any(keyword in message for keyword in ("coverage", "same-day", "same day", "feasible", "feasibility", "available")):
            return "check_delivery_coverage"
        return "get_delivery_zone"

    def _infer_logistics_params(self, user_message: str) -> Dict[str, Any]:
        message = user_message.lower()
        params: Dict[str, Any] = {}

        district = next(
            (
                name.title()
                for name in SRI_LANKAN_DISTRICTS
                if name in message
            ),
            None,
        )
        if district:
            params["district"] = district

        product_type = next(
            (
                name.replace(" ", "_")
                for name in LOGISTICS_PRODUCT_TYPES
                if name in message
            ),
            None,
        )
        if product_type:
            normalised = product_type
            if normalised in {"flower"}:
                normalised = "flowers"
            elif normalised in {"chocolate"}:
                normalised = "chocolates"
            elif normalised in {"plant"}:
                normalised = "plants"
            elif normalised in {"book"}:
                normalised = "books"
            params["product_type"] = normalised

        if "available" in message or "availability" in message:
            params["available_only"] = True

        slot_hint = None
        if "morning" in message:
            slot_hint = "morning"
        elif "afternoon" in message:
            slot_hint = "afternoon"
        elif "evening" in message:
            slot_hint = "evening"
        if slot_hint:
            params["slot"] = slot_hint

        return params

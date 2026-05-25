"""
CRM Tool - Kapruka user-profile and logistics lookup/management.

This CRM layer stores:
1. Stable customer profile data
2. Structured logistics reference data

Product catalog data is not managed here. Product metadata is vectorized and
stored in Qdrant for RAG retrieval.
"""

import time
import uuid
import inspect
from typing import Any, Dict, List, Optional

from loguru import logger

from infrastructure.observability import observe, update_current_observation
from services.crm_service import get_crm_client


class CRMTool:
    """
    CRM tool for the Kapruka routing-engine agent.

    Each public method corresponds to one routable CRM action.
    All methods return human-readable strings for the synthesiser LLM.
    """

    def __init__(self) -> None:
        self.client = get_crm_client()

    @staticmethod
    def _safe(value: Optional[Any]) -> str:
        return "N/A" if value is None or value == "" else str(value)

    @staticmethod
    def _format_bool(value: Optional[bool]) -> str:
        if value is None:
            return "Unknown"
        return "Yes" if value else "No"

    @staticmethod
    def _format_active(active: Optional[bool]) -> str:
        return "Active" if active is True else "Inactive"

    @staticmethod
    def _now_epoch() -> int:
        return int(time.time())

    def _format_user(self, user: Dict[str, Any]) -> str:
        lines = [
            f"Name: {self._safe(user.get('full_name'))}",
            f"User ID: {self._safe(user.get('user_id'))}",
            f"External ID: {self._safe(user.get('external_user_id'))}",
            f"Phone: {self._safe(user.get('phone'))}",
            f"Email: {self._safe(user.get('email'))}",
            f"District: {self._safe(user.get('district'))}",
            f"Province: {self._safe(user.get('province'))}",
            f"Address: {self._safe(user.get('address'))}",
            f"Status: {self._format_active(user.get('active'))}",
        ]
        notes = user.get("notes")
        if notes:
            lines.append(f"Notes: {notes}")
        return "\n".join(lines)

    def _format_zone(self, zone: Dict[str, Any]) -> str:
        return (
            f"District: {self._safe(zone.get('district'))}\n"
            f"Delivery Available: {self._format_bool(zone.get('delivery_available'))}\n"
            f"Same-Day Available: {self._format_bool(zone.get('same_day'))}\n"
            f"Express Available: {self._format_bool(zone.get('express_available'))}\n"
            f"Minimum Notice Hours: {self._safe(zone.get('minimum_notice_hours'))}\n"
            f"Max Daily Orders: {self._safe(zone.get('max_daily_orders'))}\n"
            f"Active Couriers: {self._safe(zone.get('active_couriers'))}"
        )

    def _format_slots(self, slots: List[Dict[str, Any]]) -> str:
        if not slots:
            return "No delivery slots found."
        lines = ["Delivery slots:"]
        for slot in slots:
            lines.append(
                "• "
                f"{self._safe(slot.get('slot'))}"
                f" | Capacity: {self._safe(slot.get('capacity'))}"
                f" | Available: {self._format_bool(slot.get('available'))}"
            )
        return "\n".join(lines)

    def _format_couriers(self, couriers: List[Dict[str, Any]]) -> str:
        if not couriers:
            return "No courier profiles found."
        lines = ["Courier profiles:"]
        for courier in couriers:
            lines.append(
                "• "
                f"{self._safe(courier.get('name'))}"
                f" | Courier ID: {self._safe(courier.get('courier_id'))}"
                f" | District: {self._safe(courier.get('district'))}"
                f" | Vehicle: {self._safe(courier.get('vehicle_type'))}"
                f" | Available: {self._format_bool(courier.get('availability'))}"
                f" | Max/Day: {self._safe(courier.get('max_deliveries_per_day'))}"
                f" | Rating: {self._safe(courier.get('rating'))}"
            )
        return "\n".join(lines)

    def _format_rule(self, rule: Dict[str, Any]) -> str:
        return (
            f"Product Type: {self._safe(rule.get('product_type'))}\n"
            f"Fragile: {self._format_bool(rule.get('fragile'))}\n"
            f"Temperature Control Required: {self._format_bool(rule.get('temperature_control_required'))}\n"
            f"Same-Day Allowed: {self._format_bool(rule.get('same_day_allowed'))}\n"
            f"Minimum Notice Hours: {self._safe(rule.get('minimum_notice_hours'))}\n"
            f"Max Delivery Distance (km): {self._safe(rule.get('max_delivery_distance_km'))}"
        )

    def _format_history(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "No matching delivery history found."
        lines = ["Delivery history:"]
        for row in rows:
            lines.append(
                "• "
                f"Order: {self._safe(row.get('order_id'))}"
                f" | District: {self._safe(row.get('district'))}"
                f" | Product: {self._safe(row.get('product_type'))}"
                f" | Minutes: {self._safe(row.get('delivery_time_minutes'))}"
                f" | Status: {self._safe(row.get('status'))}"
                f" | Rating: {self._safe(row.get('customer_rating'))}"
            )
        return "\n".join(lines)

    def _summarize_delivery_feasibility(
        self,
        summary: Dict[str, Any],
        slot: Optional[str] = None,
    ) -> Dict[str, str]:
        zone = summary.get("zone") or {}
        rule = summary.get("product_delivery_rule") or {}
        available_slots = summary.get("available_slots", [])
        requested_slots = summary.get("delivery_slots", [])

        delivery_available = zone.get("delivery_available")
        same_day_zone = zone.get("same_day")
        same_day_rule = rule.get("same_day_allowed")

        requested_slot_available = None
        if slot:
            requested_slot_available = any(item.get("available") for item in requested_slots)

        delivery_feasible = bool(delivery_available)
        reasons: List[str] = []

        if delivery_available is False:
            reasons.append("district delivery is currently unavailable")
        elif delivery_available is True:
            reasons.append("district delivery coverage is available")

        if slot:
            if requested_slot_available:
                reasons.append(f"requested slot '{slot}' is available")
            else:
                delivery_feasible = False
                reasons.append(f"requested slot '{slot}' is not available")
        elif delivery_available and not available_slots:
            reasons.append("no open slots are listed right now")

        same_day_feasible: Optional[bool]
        if same_day_zone is None and same_day_rule is None:
            same_day_feasible = None
        elif same_day_zone is None:
            same_day_feasible = bool(same_day_rule)
        elif same_day_rule is None:
            same_day_feasible = bool(same_day_zone)
        else:
            same_day_feasible = bool(same_day_zone and same_day_rule)

        if not reasons:
            reasons.append("insufficient data to confirm delivery feasibility")

        return {
            "delivery_feasibility": "Feasible" if delivery_feasible else "Not feasible",
            "same_day_feasibility": (
                "Available"
                if same_day_feasible is True
                else "Not available"
                if same_day_feasible is False
                else "Unknown"
            ),
            "reason": "; ".join(reasons),
        }

    @staticmethod
    def _missing_required_params(handler: Any, params: Dict[str, Any]) -> List[str]:
        signature = inspect.signature(handler)
        missing: List[str] = []
        for name, parameter in signature.parameters.items():
            if parameter.default is not inspect._empty:
                continue
            if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            value = params.get(name)
            if value is None or value == "":
                missing.append(name)
        return missing

    @staticmethod
    def _filter_supported_params(handler: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        signature = inspect.signature(handler)
        supported = {
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        }
        return {name: value for name, value in params.items() if name in supported}

    # ------------------------------------------------------------------
    # User profile actions
    # ------------------------------------------------------------------

    def lookup_user(
        self,
        user_id: Optional[str] = None,
        external_user_id: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        if user_id:
            user = self.client.get_user_by_id(user_id)
            return self._format_user(user) if user else "No user profile found matching the given criteria."

        if external_user_id:
            user = self.client.get_user_by_external_id(external_user_id)
            return self._format_user(user) if user else "No user profile found matching the given criteria."

        users = self.client.list_users(limit=200, active_only=False)
        matches = []
        for user in users:
            if phone and user.get("phone") == phone:
                matches.append(user)
            elif email and str(user.get("email", "")).lower() == email.lower():
                matches.append(user)
            elif name and name.lower() in str(user.get("full_name", "")).lower():
                matches.append(user)

        if not any([user_id, external_user_id, phone, email, name]):
            return "No search criteria provided. Please supply user_id, external_user_id, phone, email, or name."

        if not matches:
            return "No user profile found matching the given criteria."

        return "\n\n".join(self._format_user(user) for user in matches[:5])

    def create_user(
        self,
        full_name: str,
        external_user_id: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        district: Optional[str] = None,
        province: Optional[str] = None,
        address: Optional[str] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        if not full_name or not full_name.strip():
            return "Cannot create user profile: full_name is required."

        generated_user_id = user_id or str(uuid.uuid4())
        generated_external_id = external_user_id or (
            phone.replace("+", "") if phone else generated_user_id
        )

        user = self.client.create_user(
            user_id=generated_user_id,
            external_user_id=generated_external_id,
            full_name=full_name.strip(),
            phone=phone,
            email=email,
            district=district,
            province=province,
            address=address,
            notes=notes,
            active=True,
        )
        if not user:
            return "Error creating user profile."
        return "✅ User profile created.\n" + self._format_user(user)

    def update_user(
        self,
        user_id: Optional[str] = None,
        external_user_id: Optional[str] = None,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        district: Optional[str] = None,
        province: Optional[str] = None,
        address: Optional[str] = None,
        notes: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> str:
        if not user_id and not external_user_id:
            return "Cannot update user profile: provide user_id or external_user_id."

        resolved_external_id = external_user_id
        if user_id and not external_user_id:
            existing = self.client.get_user_by_id(user_id)
            if not existing:
                return "User profile not found."
            resolved_external_id = existing.get("external_user_id")
            if not resolved_external_id:
                return "Cannot update this user via external_user_id because the profile has no external_user_id."

        user = self.client.update_user_profile(
            external_user_id=resolved_external_id,
            full_name=full_name.strip() if full_name else None,
            phone=phone,
            email=email,
            district=district,
            province=province,
            address=address,
            notes=notes,
            active=active,
        )
        if not user:
            return "User profile not found."
        return "✅ User profile updated.\n" + self._format_user(user)

    def deactivate_user(
        self,
        user_id: Optional[str] = None,
        external_user_id: Optional[str] = None,
    ) -> str:
        return self.update_user(
            user_id=user_id,
            external_user_id=external_user_id,
            active=False,
        )

    def list_users(
        self,
        limit: int = 10,
        active_only: bool = True,
        district: Optional[str] = None,
    ) -> str:
        users = self.client.list_users(limit=limit, active_only=active_only)
        if district:
            users = [
                user for user in users
                if district.lower() in str(user.get("district", "")).lower()
            ]
        if not users:
            return "No user profiles found."
        lines = ["Kapruka CRM user profiles:"]
        for user in users:
            lines.append(
                "• "
                f"{self._safe(user.get('full_name'))}"
                f" | User ID: {self._safe(user.get('user_id'))}"
                f" | External ID: {self._safe(user.get('external_user_id'))}"
                f" | District: {self._safe(user.get('district'))}"
                f" | Province: {self._safe(user.get('province'))}"
                f" | Phone: {self._safe(user.get('phone'))}"
                f" | Status: {self._format_active(user.get('active'))}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Logistics actions
    # ------------------------------------------------------------------

    def get_delivery_zone(self, district: str) -> str:
        zone = self.client.get_delivery_zone(district)
        if not zone:
            return f"No delivery zone found for district '{district}'."
        return self._format_zone(zone)

    def list_delivery_slots(
        self,
        district: str,
        available_only: bool = False,
    ) -> str:
        slots = self.client.list_delivery_slots(
            district=district,
            available_only=available_only,
        )
        return self._format_slots(slots)

    def search_couriers(
        self,
        district: Optional[str] = None,
        vehicle_type: Optional[str] = None,
        available_only: bool = True,
        limit: int = 10,
    ) -> str:
        couriers = self.client.list_couriers(
            district=district,
            vehicle_type=vehicle_type,
            available_only=available_only,
            limit=limit,
        )
        return self._format_couriers(couriers)

    def get_product_delivery_rule(self, product_type: str) -> str:
        rule = self.client.get_product_delivery_rule(product_type)
        if not rule:
            return f"No delivery rule found for product type '{product_type}'."
        return self._format_rule(rule)

    def lookup_delivery_history(
        self,
        district: Optional[str] = None,
        product_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        history = self.client.list_delivery_history(
            district=district,
            product_type=product_type,
            status=status,
            limit=limit,
        )
        return self._format_history(history)

    def check_delivery_coverage(
        self,
        district: str,
        product_type: Optional[str] = None,
        slot: Optional[str] = None,
    ) -> str:
        summary = self.client.check_delivery_options(
            district=district,
            product_type=product_type,
            slot=slot,
        )
        zone = summary.get("zone")
        if not zone:
            return f"No delivery zone found for district '{district}'."

        feasibility = self._summarize_delivery_feasibility(summary, slot=slot)
        lines = [
            "Delivery coverage summary:",
            f"Delivery feasibility: {feasibility['delivery_feasibility']}",
            f"Same-day feasibility: {feasibility['same_day_feasibility']}",
            f"Reason: {feasibility['reason']}",
            "",
            self._format_zone(zone),
        ]

        rule = summary.get("product_delivery_rule")
        if rule:
            lines.extend(["", "Product rule:", self._format_rule(rule)])

        available_slots = summary.get("available_slots", [])
        if slot:
            lines.extend(["", "Requested slot match:", self._format_slots(summary.get("delivery_slots", []))])
        else:
            lines.extend(["", "Available slots:", self._format_slots(available_slots[:5])])

        couriers = summary.get("top_available_couriers", [])
        if couriers:
            lines.extend(["", "Top available couriers:", self._format_couriers(couriers)])

        stats = summary.get("delivery_history_summary", {})
        if stats.get("sample_size"):
            lines.extend([
                "",
                "Recent delivery history summary:",
                f"Sample size: {self._safe(stats.get('sample_size'))}",
                f"Average delivery time (minutes): {self._safe(stats.get('avg_delivery_time_minutes'))}",
                f"Average customer rating: {self._safe(stats.get('avg_customer_rating'))}",
                f"Status counts: {self._safe(stats.get('status_counts'))}",
            ])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    @observe(name="crm_dispatch")
    def dispatch(self, action: str, params: Dict[str, Any]) -> str:
        handler_map = {
            "lookup_user": self.lookup_user,
            "create_user": self.create_user,
            "update_user": self.update_user,
            "deactivate_user": self.deactivate_user,
            "list_users": self.list_users,
            "get_delivery_zone": self.get_delivery_zone,
            "list_delivery_slots": self.list_delivery_slots,
            "search_couriers": self.search_couriers,
            "get_product_delivery_rule": self.get_product_delivery_rule,
            "lookup_delivery_history": self.lookup_delivery_history,
            "check_delivery_coverage": self.check_delivery_coverage,
        }
        handler = handler_map.get(action)
        if not handler:
            return f"Unknown CRM action: {action}. Available: {list(handler_map.keys())}"

        missing = self._missing_required_params(handler, params)
        if missing:
            formatted = ", ".join(missing)
            return f"Missing required parameter(s) for {action}: {formatted}."
        filtered_params = self._filter_supported_params(handler, params)

        update_current_observation(input=f"action={action} params={params}")

        start = time.time()
        try:
            result = handler(**filtered_params)
        except Exception as exc:
            logger.error("CRM action '{}' failed: {}", action, exc)
            result = f"CRM action failed: {exc}"
        latency_ms = int((time.time() - start) * 1000)

        update_current_observation(
            output=result[:500],
            metadata={"action": action, "latency_ms": latency_ms},
        )
        return result

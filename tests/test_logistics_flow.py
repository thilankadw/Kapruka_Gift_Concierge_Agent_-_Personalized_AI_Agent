from agents.orchestrator import AgentOrchestrator
from agents.router import QueryRouter
from agents.tools.crm_tool import CRMTool


class DummyResponse:
    def __init__(self, content: str):
        self.content = content
        self.response_metadata = {}


class StaticLLM:
    def __init__(self, content: str):
        self.content = content
        self.model_name = "stub-model"

    def invoke(self, _messages):
        return DummyResponse(self.content)


class EchoToolOutputLLM:
    def invoke(self, messages):
        system_content = messages[0].content
        marker = "=== TOOL OUTPUT ===\n"
        if marker in system_content:
            content = system_content.split(marker, 1)[1].strip()
        else:
            content = system_content.strip()
        return DummyResponse(content)


class DummySTStore:
    def add(self, *_args, **_kwargs):
        return None

    def recent(self, *_args, **_kwargs):
        return []


class DummyRecaller:
    def recall(self, **_kwargs):
        return [], []

    def format_context(self, _turns):
        return ""


class DummyDistiller:
    def should_distill(self, _recent):
        return False


class FakeCRMTool:
    def __init__(self):
        self.calls = []

    def dispatch(self, action, params):
        self.calls.append((action, params))
        return (
            "Delivery coverage summary:\n"
            "Delivery feasibility: Feasible\n"
            "Same-day feasibility: Not available\n"
            "Reason: district delivery coverage is available"
        )


class FakeCRMClient:
    def check_delivery_options(self, district, product_type=None, slot=None):
        return {
            "district": district,
            "product_type": product_type,
            "zone": {
                "district": district,
                "delivery_available": True,
                "same_day": False,
                "express_available": True,
                "minimum_notice_hours": 6,
                "max_daily_orders": 100,
                "active_couriers": 5,
            },
            "delivery_slots": [
                {"slot": "morning", "capacity": 25, "available": True},
            ],
            "available_slots": [
                {"slot": "morning", "capacity": 25, "available": True},
            ],
            "top_available_couriers": [],
            "product_delivery_rule": {
                "product_type": "cake",
                "fragile": True,
                "temperature_control_required": False,
                "same_day_allowed": False,
                "minimum_notice_hours": 12,
                "max_delivery_distance_km": 315,
            },
            "delivery_history_summary": {
                "sample_size": 0,
                "status_counts": {},
                "avg_delivery_time_minutes": None,
                "avg_customer_rating": None,
            },
        }


def test_router_redirects_logistics_feasibility_to_crm():
    router = QueryRouter(
        StaticLLM(
            """{
                "routes": [
                    {
                        "route": "web_search",
                        "confidence": 0.94,
                        "reasoning": "delivery check",
                        "action": null,
                        "params": {"query": "same-day delivery in Kandy for cake"}
                    }
                ]
            }"""
        )
    )

    decision = router.route(
        "Can you check same-day delivery availability in Kandy for a cake?"
    ).primary

    assert decision.route == "crm"
    assert decision.action == "check_delivery_coverage"
    assert decision.params["district"] == "Kandy"
    assert decision.params["product_type"] == "cake"


def test_crm_tool_check_delivery_coverage_includes_feasibility_summary():
    tool = CRMTool.__new__(CRMTool)
    tool.client = FakeCRMClient()

    result = tool.check_delivery_coverage(district="Kandy", product_type="cake")

    assert "Delivery feasibility: Feasible" in result
    assert "Same-day feasibility: Not available" in result
    assert "District: Kandy" in result


def test_orchestrator_runs_logistics_flow_end_to_end():
    crm_tool = FakeCRMTool()
    orchestrator = AgentOrchestrator(
        llm_chat=EchoToolOutputLLM(),
        llm_router=StaticLLM(
            """{
                "routes": [
                    {
                        "route": "web_search",
                        "confidence": 0.91,
                        "reasoning": "delivery check",
                        "action": null,
                        "params": {"query": "same-day delivery in Kandy for cake"}
                    }
                ]
            }"""
        ),
        st_store=DummySTStore(),
        lt_store=None,
        recaller=DummyRecaller(),
        distiller=DummyDistiller(),
        crm_tool=crm_tool,
        rag_tool=None,
        web_tool=None,
    )

    response = orchestrator.chat(
        "Can you check same-day delivery availability in Kandy for a cake?",
        user_id="user-1",
        session_id="session-1",
    )

    assert response.route == "crm"
    assert response.action == "check_delivery_coverage"
    assert "Delivery feasibility: Feasible" in response.answer
    assert crm_tool.calls == [
        (
            "check_delivery_coverage",
            {
                "district": "Kandy",
                "product_type": "cake",
                "available_only": True,
            },
        )
    ]

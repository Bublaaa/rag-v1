from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langsmith import traceable
from typing_extensions import Annotated, TypedDict  # noqa: UP035

from app.config import get_settings


class AgentState(TypedDict):
    """
    State for the production agent.
    Uses Annotated with add_messages reducer for message accumulation.
    """

    message: Annotated[list[BaseMessage], add_messages]
    error: Optional[str]  # noqa: UP045
    retry_count: int
    model_used: str


class ProductionAgent:
    """
    Production LangGraph agent with:
    - Retry on failure (model fallback)
    - Graceful error handling
    - Langsmith tracing
    """

    def __init__(self):
        settings = get_settings()

        self.primary_llm = ChatOllama(
            model=settings.primary_model, temperature=0, timeout=30, max_retries=0
        )

        self.fallback_llm = ChatOllama(
            model=settings.fallback_model, temperature=0, timeout=30, max_retries=0
        )
        self.max_retries = settings.max_retries
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the LangGraph state machine."""

        def process_message(state: AgentState) -> dict:
            """Try to proces the message with the primary model."""
            try:
                response = self.primary_llm.invoke(state["message"])
                return {
                    "message": [response],
                    "error": None,
                    "model_used": "primary",
                }
            except Exception as e:  # noqa: BLE001
                return {
                    "error": str(e),
                    "retry_count": state["retry_count"] + 1,
                    "model_used": "",
                }

        def try_fallback(state: AgentState) -> dict:
            """Fallback to secondary model"""
            try:
                response = self.fallback_llm.invoke(state["message"])
                return {
                    "message": [response],
                    "error": None,
                    "model_used": "fallback",
                }
            except Exception as e:  # noqa: BLE001
                return {"error": str(e), "model_used:": ""}

        def handle_error(state: AgentState) -> dict:
            """Return error message"""
            return {
                "message": [
                    AIMessage(
                        content=(
                            "I'm sorry, I'm having trouble processing your request right now. Please try again in a moment"
                        )
                    )
                ],
                "model_used": "error_handle",
            }

        def route_after_process(state: AgentState) -> str:
            """Decide what to do after primary model attempt."""
            if state.get("error") is None:
                return "done"
            elif state["retry_count"] <= self.max_retries and self.max_retries > 0:
                return "fallback"
            else:
                return "error"

        def route_after_fallback(state: AgentState) -> str:
            """Decide what to do after fallback attempt."""
            if state.get("error") is None:
                return "done"
            else:
                return "error"

        # Build graph
        graph = StateGraph(AgentState)

        graph.add_node("process", process_message)
        graph.add_node("fallback", try_fallback)
        graph.add_node("error", handle_error)

        graph.add_edge(START, "process")
        graph.add_conditional_edges(
            "process",
            route_after_process,
            {"done": END, "fallback": "fallback", "error": "error"},
        )
        graph.add_conditional_edges(
            "fallback",
            route_after_fallback,
            {"done": END, "error": "error"},
        )
        graph.add_edge("error", END)

        return graph.compile()

    @traceable(name="production_agent_invoke")
    def invoke(self, message: str) -> dict:
        """
        Invoke the agent with user message.
        Returns : {"response":str, "model_used":str, "error":str|None}
        """

        result = self.graph.invoke(
            {
                "message": [HumanMessage(content=message)],
                "error": None,
                "retry_count": 0,
                "model_used": "",
            }
        )

        return {
            "response": result["message"][-1].content,
            "model_used": result.get("model_used", "unknown"),
            "error": result.get("error"),
        }


"""


uv run python - <<'PY'
from unittest.mock import Mock

from langchain_core.messages import AIMessage
from app.agent import ProductionAgent


def make_test_agent(max_retries=1):
    # Skip settings and real LLM initialization.
    # Test the actual LangGraph workflow with mocked models.
    agent = ProductionAgent.__new__(ProductionAgent)
    agent.max_retries = max_retries
    agent.primary_llm = Mock()
    agent.fallback_llm = Mock()
    agent.graph = agent._build_graph()
    return agent


def run_test(name, agent, expected_model, expected_error):
    print(f"\n{'=' * 60}")
    print(name)
    print("=" * 60)

    result = agent.invoke("What is Python?")

    print("Result:", result)

    assert result["model_used"] == expected_model, (
        f"Expected model_used={expected_model!r}, "
        f"got {result['model_used']!r}"
    )

    if expected_error:
        assert result["error"] is not None, "Expected an error"
    else:
        assert result["error"] is None, (
            f"Unexpected error: {result['error']}"
        )

    assert isinstance(result["response"], str)
    assert result["response"], "Response should not be empty"

    print("PASS")


# TEST 1: Primary model succeeds
agent = make_test_agent()
agent.primary_llm.invoke.return_value = AIMessage(
    content="Python is a programming language."
)

run_test(
    "TEST 1: Primary model success",
    agent,
    "primary",
    False,
)

assert agent.fallback_llm.invoke.call_count == 0


# TEST 2: Primary fails, fallback succeeds
agent = make_test_agent(max_retries=1)
agent.primary_llm.invoke.side_effect = RuntimeError(
    "Primary model unavailable"
)
agent.fallback_llm.invoke.return_value = AIMessage(
    content="Python is a popular programming language."
)

run_test(
    "TEST 2: Fallback model success",
    agent,
    "fallback",
    False,
)

assert agent.primary_llm.invoke.call_count == 1
assert agent.fallback_llm.invoke.call_count == 1


# TEST 3: Both models fail
agent = make_test_agent(max_retries=1)
agent.primary_llm.invoke.side_effect = RuntimeError(
    "Primary model unavailable"
)
agent.fallback_llm.invoke.side_effect = RuntimeError(
    "Fallback model unavailable"
)

run_test(
    "TEST 3: Both models fail gracefully",
    agent,
    "error_handle",
    True,
)

assert agent.primary_llm.invoke.call_count == 1
assert agent.fallback_llm.invoke.call_count == 1


# TEST 4: Fallback disabled
agent = make_test_agent(max_retries=0)
agent.primary_llm.invoke.side_effect = RuntimeError(
    "Primary model unavailable"
)

run_test(
    "TEST 4: Fallback disabled",
    agent,
    "error_handle",
    True,
)

assert agent.fallback_llm.invoke.call_count == 0


print(f"\n{'=' * 60}")
print("ALL TESTS PASSED")
print("=" * 60)
PY


"""
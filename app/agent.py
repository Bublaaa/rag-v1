from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI  # noqa: F401
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
            model=settings.primary_model, temperature=0, timeout=30, max_retries=0, api_key=settings.ollama_api_key
        )

        # self.fallback_llm = ChatOllama(
        #     model=settings.fallback_model, temperature=0, timeout=30, max_retries=0, api_key=settings.ollama_api_key
        # )

        # self.fallback_llm = ChatOpenAI(
        #     model=settings.fallback_model,
        #     base_url="https://ollama.com/v1",
        #     api_key=settings.ollama_api_key,
        #     temperature=0,
        #     timeout=30,
        #     max_retries=0,
        # )
        
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
import os
import sys
import traceback
from pathlib import Path
from unittest.mock import Mock

from dotenv import load_dotenv
load_dotenv(Path.cwd() / ".env")

from langchain_core.messages import AIMessage
from langsmith import Client
from app.agent import ProductionAgent


# ---------------------------------------------------------
# Test setup
# ---------------------------------------------------------

if not os.getenv("LANGSMITH_API_KEY"):
    raise RuntimeError("LANGSMITH_API_KEY is missing from .env")

if os.getenv("LANGSMITH_TRACING", "").lower() not in {"true", "1", "yes"}:
    raise RuntimeError("Set LANGSMITH_TRACING=true in .env")

client = Client()
passed = 0
failed = 0


def check(name, test_fn):
    global passed, failed

    print(f"\n{'=' * 70}")
    print(f"TEST: {name}")
    print("=" * 70)

    try:
        test_fn()
        passed += 1
        print("PASS")
    except Exception as exc:
        failed += 1
        print(f"FAIL: {type(exc).__name__}: {exc}")
        traceback.print_exc()


def make_agent(max_retries=1):
    ""Build the real graph with mocked LLM clients.""
    agent = ProductionAgent.__new__(ProductionAgent)
    agent.max_retries = max_retries
    agent.primary_llm = Mock()
    agent.fallback_llm = Mock()
    agent.graph = agent._build_graph()
    return agent


def assert_result(result, expected_model, expected_error):
    assert isinstance(result, dict)
    assert isinstance(result.get("response"), str)
    assert result["response"].strip(), "Response must not be empty"
    assert result["model_used"] == expected_model, (
        f"Expected {expected_model!r}; got {result['model_used']!r}"
    )

    if expected_error:
        assert result["error"] is not None, "Expected an error"
    else:
        assert result["error"] is None, (
            f"Unexpected error: {result['error']}"
        )


# ---------------------------------------------------------
# Test 1: Graph construction
# ---------------------------------------------------------

def test_graph_construction():
    agent = make_agent()
    assert agent.graph is not None
    assert callable(agent.graph.invoke)


check("Graph construction", test_graph_construction)


# ---------------------------------------------------------
# Test 2: Primary model succeeds
# ---------------------------------------------------------

def test_primary_success():
    agent = make_agent()
    agent.primary_llm.invoke.return_value = AIMessage(
        content="Python is a programming language."
    )

    result = agent.invoke("What is Python?")

    assert_result(result, "primary", False)
    agent.primary_llm.invoke.assert_called_once()
    agent.fallback_llm.invoke.assert_not_called()


check("Primary model success", test_primary_success)


# ---------------------------------------------------------
# Test 3: Primary fails, fallback succeeds
# ---------------------------------------------------------

def test_fallback_success():
    agent = make_agent(max_retries=1)
    agent.primary_llm.invoke.side_effect = RuntimeError(
        "Simulated primary model failure"
    )
    agent.fallback_llm.invoke.return_value = AIMessage(
        content="Python is a popular programming language."
    )

    result = agent.invoke("What is Python?")

    assert_result(result, "fallback", False)
    agent.primary_llm.invoke.assert_called_once()
    agent.fallback_llm.invoke.assert_called_once()


check("Primary failure followed by fallback success", test_fallback_success)


# ---------------------------------------------------------
# Test 4: Both models fail
# ---------------------------------------------------------

def test_both_models_fail():
    agent = make_agent(max_retries=1)
    agent.primary_llm.invoke.side_effect = RuntimeError(
        "Simulated primary failure"
    )
    agent.fallback_llm.invoke.side_effect = RuntimeError(
        "Simulated fallback failure"
    )

    result = agent.invoke("What is Python?")

    assert_result(result, "error_handle", True)
    assert "sorry" in result["response"].lower()
    agent.primary_llm.invoke.assert_called_once()
    agent.fallback_llm.invoke.assert_called_once()


check("Both models fail and error handler responds", test_both_models_fail)


# ---------------------------------------------------------
# Test 5: Fallback disabled
# ---------------------------------------------------------

def test_fallback_disabled():
    agent = make_agent(max_retries=0)
    agent.primary_llm.invoke.side_effect = RuntimeError(
        "Simulated primary failure"
    )

    result = agent.invoke("What is Python?")

    assert_result(result, "error_handle", True)
    agent.fallback_llm.invoke.assert_not_called()


check("Fallback disabled", test_fallback_disabled)


# ---------------------------------------------------------
# Test 6: Invalid / empty input still follows graph behavior
# ---------------------------------------------------------

def test_empty_input():
    agent = make_agent()
    agent.primary_llm.invoke.return_value = AIMessage(
        content="I received an empty question."
    )

    result = agent.invoke("")

    assert_result(result, "primary", False)
    agent.primary_llm.invoke.assert_called_once()


check("Empty input behavior", test_empty_input)


# ---------------------------------------------------------
# Test 7: Real local Ollama integration
# ---------------------------------------------------------

def test_real_local_ollama():
    # This uses the actual configured ProductionAgent and real models.
    # It is intentionally separate from the mocked unit tests.
    agent = ProductionAgent()
    result = agent.invoke(
        "Explain retrieval-augmented generation in one concise sentence."
    )

    assert isinstance(result["response"], str)
    assert result["response"].strip(), "Ollama returned an empty response"

    print("Model used:", result["model_used"])
    print("Response:", result["response"])
    print("Error:", result["error"])

    assert result["error"] is None, (
        f"Real model invocation returned an error: {result['error']}"
    )


check("Real local Ollama integration", test_real_local_ollama)


# ---------------------------------------------------------
# Flush traces and report
# ---------------------------------------------------------

print("\nFlushing LangSmith traces...")
try:
    client.flush()
    print("Trace flush requested.")
except Exception as exc:
    print(f"WARNING: Trace flush failed: {type(exc).__name__}: {exc}")

print(f"\n{'=' * 70}")
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
print("Check the RAG project in LangSmith for the test runs.")

if failed:
    sys.exit(1)
PY




"""
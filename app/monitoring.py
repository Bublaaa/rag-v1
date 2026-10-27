"""
Monitoring & Structured Logging
Production-grade metrics collection and JSON logging
"""

import json
import logging
import time
from datetime import UTC, datetime
from functools import wraps  # noqa: F401
from typing import Any, Callable  # noqa: F401, UP035


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for log aggregation (ELK, Datadog, etc)."""

    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }

        # Merge any extra data attached to the record
        if hasattr(record, "extra_data"):
            log_obj.update(record.extra_data)
        return json.dumps(log_obj)


def get_logger(name: str = "RAG") -> logging.Logger:
    """Create a structured JSON logger"""
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class MetricsCollector:
    """
    Collects and aggregates application metrics

    in production, replace with prometheus client:
      from prometheus_client import Counter, Histogram
    """

    def __init__(self):
        self._request_total = 0
        self._errors_total = 0
        self._latency_sum = 0
        self._latency_count = 0
        self._tokens_input = 0
        self._tokens_output = 0
        self._cache_hits = 0
        self._cache_misses = 0

    def record_request(
        self,
        latency_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: bool = False,
        cache_hit: bool = False,
    ):
        self._request_total += 1
        self._latency_sum += latency_ms
        self._latency_count += 1
        self._tokens_input += input_tokens
        self._tokens_output += output_tokens

        if error:
            self._errors_total += 1
        if cache_hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    @property
    def summary(self) -> dict:
        """Compute sumarry matrics."""
        avg_latency = (
            self._latency_sum / self._latency_count if self._latency_count > 0 else 0.0
        )
        error_rate = (
            self._errors_total / self._request_total if self._request_total > 0 else 0.0
        )
        cache_total = self._cache_hits + self._cache_misses
        cache_hit_rate = self._cache_hits / cache_total if cache_total > 0 else 0.0
        return {
            "total_request": self._request_total,
            "total_errors": self._errors_total,
            "error_rate": f"{error_rate:.2%}",
            "avg_latency_ms": round(avg_latency, 2),
            "cache_hit_rate": f"{cache_hit_rate:.2%}",
            "total_input_token": self._tokens_input,
            "total_output_token": self._tokens_output,
        }


class RequestTimer:
    """Context manager for timing requests."""

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.time() - self.start) * 1000


"""

uv run python - <<'PY'
import time
from app.monitoring import MetricsCollector, RequestTimer, get_logger


def demo_monitoring():
    logger = get_logger("monitoring_demo")
    metrics = MetricsCollector()

    print("Monitoring Demo:\n")

    queries = [
        "What is Python?",
        "Explain machine learning.",
        "What is 2 + 2?",
    ]

    responses = [
        "Python is a programming language.",
        "Machine learning enables systems to learn from data.",
        "2 + 2 = 4.",
    ]

    for query, response in zip(queries, responses):
        try:
            with RequestTimer() as timer:
                time.sleep(0.05)  # Simulate LLM processing

            metrics.record_request(
                latency_ms=timer.elapsed_ms,
                input_tokens=len(query.split()),
                output_tokens=len(response.split()),
                error=False,
                cache_hit=False,
            )

            logger.info(
                "Request completed",
                extra={
                    "extra_data": {
                        "query": query,
                        "latency_ms": round(timer.elapsed_ms, 2),
                    }
                },
            )

            print(f"Query: {query[:30]}... -> {response[:30]}...")

        except Exception:
            metrics.record_request(
                latency_ms=0,
                error=True,
            )
            logger.exception("Request failed")

    print("\nMetrics Summary:")
    summary = metrics.summary

    for key, value in summary.items():
        print(f"  {key}: {value}")


demo_monitoring()
PY


"""

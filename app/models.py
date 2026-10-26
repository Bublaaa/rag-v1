"""
API Requests and Response Models
Pydantic models fro input validation and response structure
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming Chat Request"""

    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The user's message to the agent",
    )
    thread_id: str = Field(default="default", description="Conversation thread id")


class ChatResponse(BaseModel):
    """Chat response returned to the client"""

    response: str
    thread_id: str
    model_used: str
    cached: bool = False
    processing_time_ms: float
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Timestamp of the response in ISO 8601 format",
    )


class HealthResponse(BaseModel):
    """Health check response"""

    status: str = "healthy"
    environment: str
    version: str = "1.0.0"
    checks: dict = {}


class MetricsResponse(BaseModel):
    """Metric endpoint response ."""

    total_requests: int
    total_errors: int
    error_rate: str
    avg_latency_ms: float
    cache_hit_rate: str
    total_input_tokens: int
    total_output_tokens: int


class ErrorResponse(BaseModel):
    """Standard error response"""

    error: str
    detail: str | None = None
    request_id: str | None = None


"""
uv run python -c "
from app.config import get_settings
settings=get_settings()
print(f'Environment:{settings.app_env}')
print(f'Primary model: {settings.primary_model}')
print(f'rate limit : {settings.rate_limit}')
print(f'Cache TTL: {settings.cache_ttl_seconds} seconds')
print(f'Max retries: {settings.max_retries}')
print(f'Is Production: {settings.is_production}')
print('Config loaded successfully')
"
"""

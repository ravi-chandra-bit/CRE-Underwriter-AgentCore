"""Token usage and estimated cost per underwriting run."""

from __future__ import annotations

from typing import Any

from opentelemetry import trace

from underwriter.config import load_pricing


def usage_from_result(result: Any) -> dict[str, int]:
    usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None) or {}
    return {k: int(usage.get(k, 0)) for k in ("inputTokens", "outputTokens", "totalTokens")}


def estimate_cost(usage: dict[str, int], model_key: str = "default") -> float:
    pricing = load_pricing()["models"].get(model_key) or load_pricing()["models"]["default"]
    return round(
        usage.get("inputTokens", 0) / 1000 * pricing["input_per_1k"]
        + usage.get("outputTokens", 0) / 1000 * pricing["output_per_1k"],
        6,
    )


def record_run_metrics(
    deal_id: str, usage: dict[str, int], latency_s: float, tool_calls: int
) -> dict[str, Any]:
    cost = estimate_cost(usage)
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attributes(
            {
                "underwriting.deal_id": deal_id,
                "underwriting.input_tokens": usage.get("inputTokens", 0),
                "underwriting.output_tokens": usage.get("outputTokens", 0),
                "underwriting.estimated_cost_usd": cost,
                "underwriting.latency_s": latency_s,
                "underwriting.tool_calls": tool_calls,
            }
        )
    return {"usage": usage, "estimated_cost_usd": cost, "latency_s": latency_s, "tool_call_count": tool_calls}

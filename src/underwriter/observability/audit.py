"""Structured audit logging.

In AgentCore Runtime, stdout goes to CloudWatch Logs and the active OpenTelemetry span is
exported by the ADOT distro to AgentCore Observability (CloudWatch GenAI Observability).
Each audit line is also attached to the current span as an event so a trace and its audit
records can be joined on trace id.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from opentelemetry import trace

_log = logging.getLogger("underwriter.audit")
if not _log.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(h)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def audit_log(event: str, **fields: Any) -> None:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    record = {
        "ts": round(time.time(), 3),
        "event": event,
        "trace_id": f"{ctx.trace_id:032x}" if ctx.is_valid else None,
        **{k: v for k, v in fields.items() if v is not None},
    }
    if span.is_recording():
        span.add_event(f"audit.{event}", {k: str(v) for k, v in record.items() if v is not None})
    _log.info(json.dumps(record, default=str))

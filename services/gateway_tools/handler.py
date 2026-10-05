"""Lambda handler for AgentCore Gateway Lambda targets.

The same deployment package backs two Gateway targets with separate IAM roles:
  * `uwcalc` - deterministic calculators (TOOLSET=calc)
  * `los`    - loan-origination data service (TOOLSET=los)

Gateway invokes the function with the tool arguments as the event and the tool name in
`context.client_context.custom["bedrockAgentCoreToolName"]` as "<target>___<tool>".
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from underwriter.service import EntitlementError, UnderwritingService, dispatch

log = logging.getLogger()
log.setLevel(logging.INFO)

TOOLSETS = {
    "calc": {
        "compute_cre_metrics",
        "compute_farm_cash_flow_stress",
        "check_credit_policy",
        "get_evidence",
        "verify_memo_citations",
    },
    "los": {
        "get_deal_package",
        "extract_document",
        "map_t12_label",
        "submit_memo_for_analyst_review",
        "record_credit_decision",
        "send_adverse_action_notice",
    },
}

_service: UnderwritingService | None = None


def _svc() -> UnderwritingService:
    global _service
    if _service is None:
        _service = UnderwritingService()
    return _service


def tool_name(context: Any) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    return custom.get("bedrockAgentCoreToolName", "")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    full = tool_name(context)
    name = full.split("___")[-1]
    allowed = TOOLSETS[os.environ.get("TOOLSET", "calc")]
    log.info(json.dumps({"event": "gateway_tool_call", "tool": full, "deal_id": event.get("deal_id")}))
    if name not in allowed:
        return {"error": f"tool {name} is not served by this target"}
    try:
        return dispatch(_svc(), name, dict(event))
    except EntitlementError as exc:
        log.warning(json.dumps({"event": "entitlement_denied", "tool": full, "reason": str(exc)}))
        return {"error": "not entitled to this deal"}
    except PermissionError as exc:
        log.warning(json.dumps({"event": "human_only_action_refused", "tool": full}))
        return {"error": str(exc)}
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}

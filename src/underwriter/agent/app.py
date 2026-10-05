"""AgentCore Runtime entrypoint.

Request payloads:
    {"deal_id": "CRE-001"}                               start an underwriting run
    {"deal_id": "CRE-001", "prompt": "..."}              optional extra analyst instructions
    {"approval": {"interrupt_id": "...", "response": "approve" | "reject"}}
                                                         resume a run paused for human approval

Inbound auth: the Runtime is configured with a Cognito JWT authorizer (AgentCore Identity).
The validated token is forwarded (Authorization is allow-listed in requestHeaderConfiguration)
and passed on to AgentCore Gateway, so every tool call carries the end user's identity and
the Gateway's Cedar policy evaluates the user's own entitlements.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext

from underwriter.agent.factory import AgentBundle, build_agent
from underwriter.observability import audit_log, record_run_metrics, usage_from_result
from underwriter.policy.action_guard import find_decision_language

app = BedrockAgentCoreApp()

# A Runtime session is pinned to one microVM, so per-session state can live in memory.
_SESSIONS: dict[str, dict[str, Any]] = {}


def _claims(headers: dict[str, str]) -> tuple[str | None, dict[str, Any]]:
    """Read claims from the bearer token. Signature/expiry were already verified by the
    Runtime's JWT authorizer before the request reached this container."""
    auth = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
    token = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else None
    if not token:
        return None, {}
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return token, json.loads(base64.urlsafe_b64decode(payload))


def _result_payload(bundle: AgentBundle, result: Any, deal_id: str, started: float) -> dict[str, Any]:
    text = str(result)
    if result.stop_reason == "interrupt":
        status = "awaiting_approval"
    else:
        status = "completed"
    phrases = find_decision_language(text) + find_decision_language(bundle.record.pending_memo or "")
    if phrases:
        audit_log("decision_language_blocked", deal_id=deal_id, phrases=phrases)
        text = "Output withheld: it contained credit-decision language, which this assistant may not produce."
        status = "blocked"
    metrics = record_run_metrics(
        deal_id, usage_from_result(result), round(time.time() - started, 2), len(bundle.record.tool_calls)
    )
    return {
        "deal_id": deal_id,
        "status": status,
        "response": text,
        "memo": bundle.record.pending_memo,
        "interrupts": [
            {"interrupt_id": i.id, "name": i.name, "reason": i.reason} for i in (result.interrupts or [])
        ],
        "tool_calls": bundle.record.tool_calls,
        "blocked_tool_attempts": bundle.record.forbidden_attempts,
        **metrics,
    }


@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    started = time.time()
    session_id = context.session_id or "local"
    token, claims = _claims(context.request_headers or {})
    user = claims.get("sub")
    portfolio = claims.get("portfolio") or os.environ.get("DEFAULT_PORTFOLIO")

    if "approval" in payload:
        state = _SESSIONS.get(session_id)
        if not state:
            return {"status": "error", "error": "no paused run in this session"}
        bundle, deal_id = state["bundle"], state["deal_id"]
        approval = payload["approval"]
        audit_log("approval_received", user=user, deal_id=deal_id, response=approval.get("response"))
        result = bundle.agent(
            [
                {
                    "interruptResponse": {
                        "interruptId": approval["interrupt_id"],
                        "response": approval.get("response", "reject"),
                    }
                }
            ]
        )
        return _result_payload(bundle, result, deal_id, started)

    deal_id = payload["deal_id"]
    bundle = build_agent(
        portfolio=portfolio,
        gateway_url=os.environ.get("GATEWAY_URL"),
        bearer_token=token,
        user=user,
        session_id=session_id,
    )
    _SESSIONS[session_id] = {"bundle": bundle, "deal_id": deal_id}
    audit_log("run_started", user=user, deal_id=deal_id, session_id=session_id, portfolio=portfolio)
    prompt = f"Prepare the underwriting package and draft credit memo for deal {deal_id}."
    if payload.get("prompt"):
        prompt += f"\nAnalyst notes: {payload['prompt']}"
    result = bundle.agent(prompt)
    return _result_payload(bundle, result, deal_id, started)


if __name__ == "__main__":
    app.run()

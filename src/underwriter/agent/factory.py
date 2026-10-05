"""Builds the Strands underwriting agent for local or Gateway-backed tool access."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from strands import Agent
from strands.models import BedrockModel

from underwriter.agent.hooks import ActionGuardHook, AuditHook, RunRecord
from underwriter.agent.prompts import build_system_prompt
from underwriter.agent.tools import build_local_tools
from underwriter.policy.action_guard import MEMO_DISCLAIMER
from underwriter.service import UnderwritingService

# Bedrock model id. Copy the exact cross-region inference profile id for your account and
# region from the Bedrock console (Model catalog) and set BEDROCK_MODEL_ID.
DEFAULT_MODEL_ID = "anthropic.claude-opus-5-5"


@dataclass
class AgentBundle:
    agent: Agent
    record: RunRecord
    mcp_client: Any | None = None


def build_model() -> BedrockModel:
    cfg: dict[str, Any] = {
        "model_id": os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        "max_tokens": int(os.environ.get("MAX_TOKENS", "16000")),
    }
    # Bedrock Guardrails: PII filters and denied topics (credit decisions) on input and output.
    if os.environ.get("GUARDRAIL_ID"):
        cfg.update(
            guardrail_id=os.environ["GUARDRAIL_ID"],
            guardrail_version=os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
            guardrail_trace="enabled",
            guardrail_redact_output=True,
            guardrail_redact_output_message="[Output withheld by guardrail]",
        )
    return BedrockModel(region_name=os.environ.get("AWS_REGION", "us-east-1"), **cfg)


def build_agent(
    service: UnderwritingService | None = None,
    *,
    portfolio: str | None = None,
    gateway_url: str | None = None,
    bearer_token: str | None = None,
    user: str | None = None,
    session_id: str | None = None,
    auto_approve: bool = False,
) -> AgentBundle:
    """Local mode calls the service in-process; Gateway mode reaches the same tools over MCP
    through AgentCore Gateway, authenticated with the end user's own token."""
    record = RunRecord()
    mcp_client = None
    if gateway_url:
        from mcp.client.streamable_http import streamablehttp_client
        from strands.tools.mcp import MCPClient

        headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
        mcp_client = MCPClient(lambda: streamablehttp_client(gateway_url, headers=headers))
        tools: list[Any] = [mcp_client]
    else:
        tools = build_local_tools(service or UnderwritingService(), portfolio)

    agent = Agent(
        name="credit-underwriting-assistant",
        model=build_model(),
        tools=tools,
        system_prompt=build_system_prompt(MEMO_DISCLAIMER, portfolio if gateway_url else None),
        hooks=[AuditHook(record, user=user, session_id=session_id), ActionGuardHook(record, auto_approve)],
        callback_handler=None,
        trace_attributes={
            k: v
            for k, v in {
                "session.id": session_id,
                "user.id": user,
                "underwriting.portfolio": portfolio,
            }.items()
            if v
        },
    )
    return AgentBundle(agent=agent, record=record, mcp_client=mcp_client)

"""Cognito pre-token-generation trigger (event version V2).

Copies the user's lending entitlements from custom attributes into the *access token*, so
AgentCore Runtime and Gateway receive them as JWT claims and AgentCore Policy (Cedar) can
evaluate them as principal tags: `lending_role` (viewer | underwriter | credit_analyst) and
`portfolio` (e.g. cre-west, ag-midwest).
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    attrs = event["request"].get("userAttributes", {})
    claims = {
        "lending_role": attrs.get("custom:lending_role", "viewer"),
        "portfolio": attrs.get("custom:portfolio", "none"),
    }
    event["response"]["claimsAndScopeOverrideDetails"] = {
        "accessTokenGeneration": {"claimsToAddOrOverride": claims},
        "idTokenGeneration": {"claimsToAddOrOverride": claims},
    }
    return event

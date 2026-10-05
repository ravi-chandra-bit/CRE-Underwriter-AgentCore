"""Invoke the deployed underwriting agent as a signed-in analyst.

    export UW_USERNAME=analyst.west@example.com UW_PASSWORD=...
    python -m scripts.invoke_agent --deal CRE-001            # run, then approve filing interactively
    python -m scripts.invoke_agent --deal CRE-001 --approve  # auto-approve the filing step

Reads stack outputs (RuntimeArn, UserPoolClientId) from environment variables or
`infra/outputs.json` written by `cdk deploy --outputs-file outputs.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import boto3
import urllib3

OUTPUTS = Path(__file__).resolve().parents[1] / "infra" / "outputs.json"


def outputs() -> dict[str, str]:
    if OUTPUTS.exists():
        data = json.loads(OUTPUTS.read_text())
        return next(iter(data.values()))
    return {}


def _cfg(key: str, env: str) -> str:
    value = os.environ.get(env) or outputs().get(key)
    if not value:
        raise SystemExit(f"set {env} or deploy with --outputs-file infra/outputs.json")
    return value


def get_token() -> str:
    """Cognito access token for the analyst (carries lending_role and portfolio claims)."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    resp = boto3.client("cognito-idp", region_name=region).initiate_auth(
        ClientId=_cfg("UserPoolClientId", "UW_CLIENT_ID"),
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": os.environ["UW_USERNAME"], "PASSWORD": os.environ["UW_PASSWORD"]},
    )
    return resp["AuthenticationResult"]["AccessToken"]


def invoke_runtime(payload: dict[str, Any], token: str, session_id: str) -> dict[str, Any]:
    """OAuth (JWT) callers invoke the Runtime over HTTPS with a bearer token, not SigV4."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    arn = urllib.parse.quote(_cfg("RuntimeArn", "UW_RUNTIME_ARN"), safe="")
    qualifier = os.environ.get("UW_ENDPOINT", outputs().get("RuntimeEndpointName", "prod"))
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{arn}/invocations?qualifier={qualifier}"
    resp = urllib3.PoolManager().request(
        "POST",
        url,
        body=json.dumps(payload).encode(),
        timeout=urllib3.Timeout(total=900),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        },
    )
    if resp.status >= 400:
        raise RuntimeError(f"runtime returned {resp.status}: {resp.data[:500]!r}")
    return json.loads(resp.data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deal", required=True)
    ap.add_argument("--prompt", default="")
    ap.add_argument("--approve", action="store_true", help="approve the filing step without asking")
    args = ap.parse_args()

    token = get_token()
    session = f"cli-{args.deal}-{uuid.uuid4().hex}"
    resp = invoke_runtime({"deal_id": args.deal, "prompt": args.prompt}, token, session)
    while resp.get("status") == "awaiting_approval":
        if resp.get("memo"):
            print(resp["memo"])
        intr = resp["interrupts"][0]
        print(f"\n[approval requested] {intr['reason']}")
        answer = "approve" if args.approve else input("approve / reject > ").strip()
        resp = invoke_runtime(
            {"approval": {"interrupt_id": intr["interrupt_id"], "response": answer}}, token, session
        )
    print(json.dumps({k: v for k, v in resp.items() if k != "memo"}, indent=2))


if __name__ == "__main__":
    main()

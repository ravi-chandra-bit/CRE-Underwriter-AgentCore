"""Point the Runtime `prod` endpoint at an earlier agent version (or list versions).

    python -m scripts.rollback --list
    python -m scripts.rollback --to-version 3
    python -m scripts.rollback --previous

Every `cdk deploy` that changes the agent creates a new immutable Runtime version. The
endpoint is just a pointer, so rollback is a single control-plane call and needs no rebuild.
"""

from __future__ import annotations

import argparse
import os

import boto3

from scripts.invoke_agent import _cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--to-version")
    g.add_argument("--previous", action="store_true")
    ap.add_argument("--endpoint", default="prod")
    args = ap.parse_args()

    ctl = boto3.client("bedrock-agentcore-control", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    runtime_id = _cfg("RuntimeId", "UW_RUNTIME_ID")
    versions, token = [], None
    while True:
        page = ctl.list_agent_runtime_versions(
            agentRuntimeId=runtime_id, **({"nextToken": token} if token else {})
        )
        versions += page.get("agentRuntimes", [])
        token = page.get("nextToken")
        if not token:
            break
    versions.sort(key=lambda v: int(v["agentRuntimeVersion"]))
    current = ctl.get_agent_runtime_endpoint(agentRuntimeId=runtime_id, endpointName=args.endpoint)
    live = current.get("liveVersion")
    if args.list:
        for v in versions:
            mark = " <- live" if v["agentRuntimeVersion"] == live else ""
            print(
                f"version {v['agentRuntimeVersion']:>4}  {v.get('lastUpdatedAt', '')}  {v.get('status', '')}{mark}"
            )
        return
    target = args.to_version
    if args.previous:
        earlier = [v["agentRuntimeVersion"] for v in versions if int(v["agentRuntimeVersion"]) < int(live)]
        if not earlier:
            raise SystemExit("no earlier version to roll back to")
        target = earlier[-1]
    ctl.update_agent_runtime_endpoint(
        agentRuntimeId=runtime_id, endpointName=args.endpoint, agentRuntimeVersion=str(target)
    )
    print(f"endpoint '{args.endpoint}' moved from version {live} to {target}")


if __name__ == "__main__":
    main()

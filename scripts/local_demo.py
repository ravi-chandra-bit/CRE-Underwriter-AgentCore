"""Run one deal locally.

python -m scripts.local_demo --deal CRE-001                 # deterministic pipeline, no AWS needed
python -m scripts.local_demo --deal CRE-001 --agent         # Strands agent on Bedrock, local tools
python -m scripts.local_demo --deal CRE-001 --agent --ask   # pause for your approval before filing
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from underwriter.pipeline import run_deterministic
from underwriter.service import UnderwritingService
from underwriter.store import LocalDealStore

DATA = Path(__file__).resolve().parents[1] / "evals" / "data" / "deals"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deal", default="CRE-001")
    ap.add_argument("--agent", action="store_true")
    ap.add_argument("--ask", action="store_true", help="ask before the filing step (human approval)")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp()) / "deals"
    shutil.copytree(DATA, tmp, ignore=shutil.ignore_patterns("truth.json", "work"))
    service = UnderwritingService(LocalDealStore(tmp))

    if not args.agent:
        run = run_deterministic(service, args.deal)
        print(run["memo"])
        print(json.dumps({k: v for k, v in run["verification"].items() if k != "unsupported"}, indent=2))
        return

    from underwriter.agent.factory import build_agent

    bundle = build_agent(service, auto_approve=not args.ask, session_id=f"demo-{args.deal}")
    result = bundle.agent(f"Prepare the underwriting package and draft credit memo for deal {args.deal}.")
    while result.stop_reason == "interrupt":
        responses = []
        for intr in result.interrupts:
            print(bundle.record.pending_memo or "")
            print(f"\n[approval requested] {intr.reason}")
            responses.append(
                {
                    "interruptResponse": {
                        "interruptId": intr.id,
                        "response": input("approve / reject > ").strip(),
                    }
                }
            )
        result = bundle.agent(responses)
    print(bundle.record.pending_memo or str(result))
    print(
        json.dumps(
            {"tool_calls": bundle.record.tool_calls, "usage": result.metrics.accumulated_usage},
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()

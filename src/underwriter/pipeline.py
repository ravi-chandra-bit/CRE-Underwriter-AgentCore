"""Deterministic end-to-end run (no LLM).

Calls the same service tools the agent calls, in the order the system prompt asks for, and
drafts the memo from the template. Used by offline evaluation in CI, by unit tests, and as
a reference run an analyst can compare against the agent's output.
"""

from __future__ import annotations

from typing import Any

from underwriter.memo import EvidenceLedger, draft_agri_memo, draft_cre_memo
from underwriter.models import CREMetrics, FarmMetrics, LoanRequest, PolicyCheck, RentRoll, T12Statement
from underwriter.service import UnderwritingService
from underwriter.store import read_json


def run_deterministic(service: UnderwritingService, deal_id: str) -> dict[str, Any]:
    store = service.store
    pkg = service.get_deal_package(deal_id)
    extractions = {d["doc_id"]: service.extract_document(deal_id, d["doc_id"]) for d in pkg["documents"]}
    if pkg["loan_type"] == "CRE":
        service.compute_cre_metrics(deal_id)
    else:
        service.compute_farm_cash_flow_stress(deal_id)
    service.check_credit_policy(deal_id)

    deal = read_json(store, deal_id, "deal.json")
    loan = LoanRequest(**deal["loan"])
    ledger = EvidenceLedger(**read_json(store, deal_id, "work/evidence.json"))
    pc = PolicyCheck(**read_json(store, deal_id, "work/policy.json"))
    metrics = read_json(store, deal_id, "work/metrics.json")
    docs = {d["doc_type"]: d["doc_id"] for d in deal["documents"]}

    if pkg["loan_type"] == "CRE":
        rr = RentRoll(**read_json(store, deal_id, f"work/parsed_{docs['rent_roll']}.json")["document"])
        t12 = T12Statement(**read_json(store, deal_id, f"work/parsed_{docs['t12']}.json")["document"])
        memo = draft_cre_memo(loan, rr, t12, CREMetrics(**metrics), pc, ledger)
    else:
        memo = draft_agri_memo(loan, docs["farm_financials"], FarmMetrics(**metrics), pc, ledger)

    verification = service.verify_memo_citations(deal_id, memo)
    return {
        "deal_id": deal_id,
        "extractions": extractions,
        "metrics": metrics,
        "policy": pc.model_dump(mode="json"),
        "memo": memo,
        "verification": verification,
        "tool_calls": [],
        "forbidden_tool_attempts": [],
    }

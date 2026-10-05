"""Underwriting tool implementations.

This is the single implementation behind every tool the agent can call. It is exposed two
ways:
  * locally, as Strands `@tool` functions (agent/tools.py) for development and offline evals;
  * in AWS, through Lambda functions registered as AgentCore Gateway targets
    (services/*/handler.py), so the deployed agent reaches it over MCP with the user's token.

Design rule: the model passes identifiers (deal_id, doc_id), never figures. All numbers are
read from source documents and computed here, then returned with citation anchors.
"""

from __future__ import annotations

from typing import Any

from underwriter.calculators import compute_cre_metrics, compute_farm_metrics
from underwriter.ingestion import VALID_CATEGORIES, parse_farm_financials, parse_rent_roll, parse_t12
from underwriter.memo import EvidenceLedger, verify_citations
from underwriter.models import (
    CREMetrics,
    FarmFinancials,
    FarmMetrics,
    LoanRequest,
    LoanType,
    RentRoll,
    T12Statement,
)
from underwriter.policy import check_agri_policy, check_cre_policy, find_decision_language
from underwriter.store import DealStore, read_json, store_from_env, write_json

MIN_FAITHFULNESS_TO_SUBMIT = 0.98


class EntitlementError(PermissionError):
    pass


class UnderwritingService:
    def __init__(self, store: DealStore | None = None):
        self.store = store or store_from_env()

    # -- helpers ---------------------------------------------------------------------

    def _deal(self, deal_id: str, portfolio: str | None) -> dict[str, Any]:
        deal = read_json(self.store, deal_id, "deal.json")
        # The Gateway's Cedar policy proves the caller is entitled to `portfolio`; this check
        # proves the deal belongs to that portfolio. Together they scope data to the user.
        if portfolio is not None and deal.get("portfolio") != portfolio:
            raise EntitlementError(f"deal {deal_id} is not in portfolio {portfolio}")
        return deal

    def _loan(self, deal: dict[str, Any]) -> LoanRequest:
        return LoanRequest(**deal["loan"])

    def _doc(self, deal: dict[str, Any], doc_type: str) -> dict[str, Any]:
        docs = [d for d in deal["documents"] if d["doc_type"] == doc_type]
        if not docs:
            raise ValueError(f"deal {deal['loan']['deal_id']} has no {doc_type} document")
        return docs[0]

    def _overrides(self, deal_id: str) -> dict[str, dict[str, str]]:
        if self.store.exists(deal_id, "work/label_overrides.json"):
            return read_json(self.store, deal_id, "work/label_overrides.json")
        return {}

    def _parsed(self, deal: dict[str, Any], doc_type: str):
        deal_id = deal["loan"]["deal_id"]
        doc = self._doc(deal, doc_type)
        key = f"work/parsed_{doc['doc_id']}.json"
        if not self.store.exists(deal_id, key):
            self.extract_document(deal_id, doc["doc_id"], None)
        data = read_json(self.store, deal_id, key)
        model = {"rent_roll": RentRoll, "t12": T12Statement, "farm_financials": FarmFinancials}[doc_type]
        return model(**data["document"])

    def _ledger(self, deal_id: str) -> EvidenceLedger:
        if self.store.exists(deal_id, "work/evidence.json"):
            return EvidenceLedger(**read_json(self.store, deal_id, "work/evidence.json"))
        return EvidenceLedger(deal_id=deal_id)

    def _save_ledger(self, ledger: EvidenceLedger) -> None:
        write_json(self.store, ledger.deal_id, "work/evidence.json", ledger.model_dump())

    # -- tools -----------------------------------------------------------------------

    def get_deal_package(self, deal_id: str, portfolio: str | None = None) -> dict[str, Any]:
        deal = self._deal(deal_id, portfolio)
        loan = self._loan(deal)
        ledger = self._ledger(deal_id)
        ledger.add_loan(loan)
        self._save_ledger(ledger)
        return {
            "deal_id": deal_id,
            "borrower_name": loan.borrower_name,
            "loan_type": loan.loan_type.value,
            "property_type": loan.property_type.value,
            "purpose": loan.purpose,
            "documents": [{"doc_id": d["doc_id"], "doc_type": d["doc_type"]} for d in deal["documents"]],
            "citation_anchors": [a for a in ledger.items if a.startswith("loan:")],
        }

    def extract_document(self, deal_id: str, doc_id: str, portfolio: str | None = None) -> dict[str, Any]:
        deal = self._deal(deal_id, portfolio)
        doc = next((d for d in deal["documents"] if d["doc_id"] == doc_id), None)
        if doc is None:
            raise ValueError(f"document {doc_id} not found in deal {deal_id}")
        text = self.store.read_text(deal_id, doc["filename"])
        ledger = self._ledger(deal_id)

        if doc["doc_type"] == "rent_roll":
            parsed, warnings = parse_rent_roll(text, doc_id)
            ledger.add_rent_roll(parsed)
            summary = {
                "unit_count": parsed.unit_count,
                "occupied_units": parsed.occupied_units,
                "physical_occupancy": parsed.physical_occupancy,
                "in_place_annual_rent": parsed.in_place_annual_rent,
            }
        elif doc["doc_type"] == "t12":
            parsed, warnings = parse_t12(text, doc_id, self._overrides(deal_id).get(doc_id))
            ledger.add_t12(parsed)
            summary = {
                "totals_by_category": parsed.totals_by_category(),
                "unmapped_labels": parsed.unmapped_labels,
                "period_end": parsed.period_end,
            }
        elif doc["doc_type"] == "farm_financials":
            parsed, warnings = parse_farm_financials(text, doc_id)
            ledger.add_farm_doc(parsed)
            summary = {
                "annual_revenue": round(sum(m.revenue for m in parsed.months), 2),
                "annual_operating_expenses": parsed.annual("operating_expenses"),
                "opening_cash": parsed.opening_cash,
                "operating_line_limit": parsed.operating_line_limit,
            }
        else:
            raise ValueError(f"unsupported document type {doc['doc_type']}")

        write_json(
            self.store,
            deal_id,
            f"work/parsed_{doc_id}.json",
            {"document": parsed.model_dump(mode="json"), "warnings": warnings},
        )
        self._save_ledger(ledger)
        # Tenant names and other row-level PII stay server-side; the model sees aggregates only.
        return {
            "doc_id": doc_id,
            "doc_type": doc["doc_type"],
            "summary": summary,
            "warnings": warnings,
            "citation_anchors": [a for a in ledger.items if a.startswith(f"doc:{doc_id}#")],
        }

    def map_t12_label(
        self,
        deal_id: str,
        doc_id: str,
        label: str,
        category: str,
        rationale: str,
        portfolio: str | None = None,
    ) -> dict[str, Any]:
        """Record a category for a T-12 line the deterministic mapper could not classify."""
        self._deal(deal_id, portfolio)
        if category not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        if not rationale.strip():
            raise ValueError("a rationale is required; it is shown to the analyst")
        overrides = self._overrides(deal_id)
        overrides.setdefault(doc_id, {})[label] = category
        write_json(self.store, deal_id, "work/label_overrides.json", overrides)
        log = (
            read_json(self.store, deal_id, "work/mapping_log.json")
            if self.store.exists(deal_id, "work/mapping_log.json")
            else []
        )
        log.append(
            {
                "doc_id": doc_id,
                "label": label,
                "category": category,
                "rationale": rationale,
                "source": "agent",
                "requires_analyst_confirmation": True,
            }
        )
        write_json(self.store, deal_id, "work/mapping_log.json", log)
        return self.extract_document(deal_id, doc_id, portfolio)

    def compute_cre_metrics(self, deal_id: str, portfolio: str | None = None) -> dict[str, Any]:
        deal = self._deal(deal_id, portfolio)
        loan = self._loan(deal)
        if loan.loan_type != LoanType.CRE:
            raise ValueError("compute_cre_metrics applies to CRE deals only")
        m = compute_cre_metrics(loan, self._parsed(deal, "rent_roll"), self._parsed(deal, "t12"))
        write_json(self.store, deal_id, "work/metrics.json", m.model_dump())
        ledger = self._ledger(deal_id)
        ledger.add_loan(loan)
        ledger.add_cre_metrics(m)
        self._save_ledger(ledger)
        return {**m.model_dump(), "citation_prefix": f"{m.calc_id}#"}

    def compute_farm_cash_flow_stress(self, deal_id: str, portfolio: str | None = None) -> dict[str, Any]:
        deal = self._deal(deal_id, portfolio)
        loan = self._loan(deal)
        if loan.loan_type != LoanType.AGRI:
            raise ValueError("compute_farm_cash_flow_stress applies to agricultural deals only")
        m = compute_farm_metrics(loan, self._parsed(deal, "farm_financials"))
        write_json(self.store, deal_id, "work/metrics.json", m.model_dump())
        ledger = self._ledger(deal_id)
        ledger.add_loan(loan)
        ledger.add_farm_metrics(m)
        self._save_ledger(ledger)
        return {**m.model_dump(), "citation_prefix": f"{m.calc_id}#"}

    def check_credit_policy(self, deal_id: str, portfolio: str | None = None) -> dict[str, Any]:
        deal = self._deal(deal_id, portfolio)
        loan = self._loan(deal)
        if not self.store.exists(deal_id, "work/metrics.json"):
            raise ValueError("run the metric calculation tool before checking policy")
        data = read_json(self.store, deal_id, "work/metrics.json")
        if loan.loan_type == LoanType.CRE:
            pc = check_cre_policy(CREMetrics(**data), loan.property_type)
        else:
            pc = check_agri_policy(FarmMetrics(**data))
        write_json(self.store, deal_id, "work/policy.json", pc.model_dump())
        ledger = self._ledger(deal_id)
        ledger.add_policy(pc)
        self._save_ledger(ledger)
        return {
            **pc.model_dump(mode="json"),
            "note": "Exceptions are flags for analyst review, not a decision.",
        }

    def get_evidence(self, deal_id: str, portfolio: str | None = None) -> dict[str, Any]:
        self._deal(deal_id, portfolio)
        return {"deal_id": deal_id, "evidence": self._ledger(deal_id).summary()}

    def verify_memo_citations(
        self, deal_id: str, memo_markdown: str, portfolio: str | None = None
    ) -> dict[str, Any]:
        self._deal(deal_id, portfolio)
        report = verify_citations(memo_markdown, self._ledger(deal_id))
        decision_phrases = find_decision_language(memo_markdown)
        return {
            **report.model_dump(),
            "decision_language": decision_phrases,
            "ok": report.faithfulness >= MIN_FAITHFULNESS_TO_SUBMIT
            and not report.fabricated_anchors
            and not decision_phrases,
        }

    def submit_memo_for_analyst_review(
        self, deal_id: str, memo_markdown: str, approved_by: str = "", portfolio: str | None = None
    ) -> dict[str, Any]:
        """Write action: files the draft memo in the analyst's review queue. Never a decision."""
        check = self.verify_memo_citations(deal_id, memo_markdown, portfolio)
        if check["decision_language"]:
            raise ValueError(
                f"memo contains credit-decision language and was not filed: {check['decision_language']}"
            )
        if not check["ok"]:
            raise ValueError(
                f"memo failed citation verification (faithfulness {check['faithfulness']}, "
                f"fabricated anchors {check['fabricated_anchors']}); fix before filing"
            )
        write_json(
            self.store,
            deal_id,
            "work/memo_submitted.json",
            {"memo": memo_markdown, "status": "PENDING ANALYST REVIEW", "approved_by": approved_by},
        )
        return {"deal_id": deal_id, "status": "PENDING ANALYST REVIEW", "faithfulness": check["faithfulness"]}

    # Present in the LOS for human users only. Registered on the Gateway so AgentCore Policy
    # can demonstrably forbid them; any call that reaches here is refused again.
    def record_credit_decision(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise PermissionError(
            "credit decisions are recorded by an authorised human in the LOS, never by the agent"
        )

    def send_adverse_action_notice(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise PermissionError(
            "adverse action notices are issued by a human under ECOA/Reg B, never by the agent"
        )


TOOL_NAMES = (
    "get_deal_package",
    "extract_document",
    "map_t12_label",
    "compute_cre_metrics",
    "compute_farm_cash_flow_stress",
    "check_credit_policy",
    "get_evidence",
    "verify_memo_citations",
    "submit_memo_for_analyst_review",
)


def dispatch(service: UnderwritingService, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Route a Gateway tool call (name possibly prefixed '<target>___') to the service."""
    name = tool.split("___")[-1]
    if name in ("record_credit_decision", "send_adverse_action_notice"):
        return getattr(service, name)(**args)
    if name not in TOOL_NAMES:
        raise ValueError(f"unknown tool {tool}")
    return getattr(service, name)(**args)

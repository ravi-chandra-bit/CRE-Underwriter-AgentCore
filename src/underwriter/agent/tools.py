"""Strands tools that call UnderwritingService in-process.

Used for local development and offline/live evaluation. In AWS the same operations are
reached through AgentCore Gateway (agent/factory.py builds an MCP client instead), so the
tool names and arguments here deliberately match services/tool_schemas/*.json.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from underwriter.service import UnderwritingService


def build_local_tools(service: UnderwritingService, portfolio: str | None = None) -> list[Any]:
    """Tools bound to the caller's portfolio, so entitlement is enforced in-process too."""

    @tool
    def get_deal_package(deal_id: str) -> dict:
        """Return the loan request summary and the list of documents on file for a deal.

        Args:
            deal_id: Deal identifier, e.g. "CRE-001" or "AG-004".
        """
        return service.get_deal_package(deal_id, portfolio)

    @tool
    def extract_document(deal_id: str, doc_id: str) -> dict:
        """Parse a source document (rent roll, T-12 or farm financials) and return aggregate figures,
        warnings, unmapped T-12 labels and the citation anchors created.

        Args:
            deal_id: Deal identifier.
            doc_id: Document identifier from get_deal_package.
        """
        return service.extract_document(deal_id, doc_id, portfolio)

    @tool
    def map_t12_label(deal_id: str, doc_id: str, label: str, category: str, rationale: str) -> dict:
        """Assign a canonical category to a T-12 line item the parser could not map, then re-extract.

        Args:
            deal_id: Deal identifier.
            doc_id: T-12 document identifier.
            label: The unmapped label exactly as reported by extract_document.
            category: One of gross_potential_rent, vacancy_loss, concessions, bad_debt, other_income,
                real_estate_taxes, insurance, utilities, repairs_maintenance, management_fee, payroll,
                general_admin, marketing, contract_services, capital_expenditures, debt_service,
                depreciation_amortization.
            rationale: One sentence explaining the mapping, shown to the analyst.
        """
        return service.map_t12_label(deal_id, doc_id, label, category, rationale, portfolio)

    @tool
    def compute_cre_metrics(deal_id: str) -> dict:
        """Compute underwritten NOI, DSCR, debt yield, LTV, breakeven occupancy and maximum loan sizing
        for a CRE deal from its extracted rent roll and T-12.

        Args:
            deal_id: Deal identifier.
        """
        return service.compute_cre_metrics(deal_id, portfolio)

    @tool
    def compute_farm_cash_flow_stress(deal_id: str) -> dict:
        """Compute farm cash available for debt service, term debt coverage, LTV, liquidity and a
        month-by-month seasonal cash-flow stress test for an agricultural deal.

        Args:
            deal_id: Deal identifier.
        """
        return service.compute_farm_cash_flow_stress(deal_id, portfolio)

    @tool
    def check_credit_policy(deal_id: str) -> dict:
        """Compare the computed metrics with credit policy and return flagged exceptions with rule ids.

        Args:
            deal_id: Deal identifier.
        """
        return service.check_credit_policy(deal_id, portfolio)

    @tool
    def get_evidence(deal_id: str) -> dict:
        """List every citable figure for the deal with its citation anchor and value.

        Args:
            deal_id: Deal identifier.
        """
        return service.get_evidence(deal_id, portfolio)

    @tool
    def verify_memo_citations(deal_id: str, memo_markdown: str) -> dict:
        """Check that every number in a memo draft is cited and matches the cited figure, and that the
        memo contains no credit-decision language.

        Args:
            deal_id: Deal identifier.
            memo_markdown: The full memo draft in Markdown.
        """
        return service.verify_memo_citations(deal_id, memo_markdown, portfolio)

    @tool
    def submit_memo_for_analyst_review(deal_id: str, memo_markdown: str) -> dict:
        """File the verified draft memo in the credit analyst's review queue. Requires human approval.

        Args:
            deal_id: Deal identifier.
            memo_markdown: The verified memo in Markdown.
        """
        return service.submit_memo_for_analyst_review(deal_id, memo_markdown, "analyst", portfolio)

    return [
        get_deal_package,
        extract_document,
        map_t12_label,
        compute_cre_metrics,
        compute_farm_cash_flow_stress,
        check_credit_policy,
        get_evidence,
        verify_memo_citations,
        submit_memo_for_analyst_review,
    ]

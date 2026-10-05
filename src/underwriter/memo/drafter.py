"""Template credit-memo drafter.

Used in offline mode (CI evaluation, unit tests, demos without Bedrock access) and as the
structural reference the LLM is asked to follow in live mode. Every figure is formatted
from a ledger value and carries its citation anchor.
"""

from __future__ import annotations

from underwriter.memo.evidence import EvidenceLedger
from underwriter.models import CREMetrics, FarmMetrics, LoanRequest, PolicyCheck, RentRoll, T12Statement
from underwriter.policy.action_guard import MEMO_DISCLAIMER


def money(v: float) -> str:
    return f"${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def pct(v: float, d: int = 1) -> str:
    return f"{v * 100:.{d}f}%"


def mult(v: float) -> str:
    return f"{v:.2f}x"


def _exceptions_section(pc: PolicyCheck) -> list[str]:
    deal = pc.calc_id
    lines = ["## Policy exceptions", ""]
    if not pc.exceptions:
        lines.append(
            f"No exceptions were flagged across the {pc.rules_evaluated} policy rules evaluated "
            f"[{deal}#rules_evaluated]."
        )
        return lines
    lines.append(
        f"{len(pc.exceptions)} exception(s) flagged [{deal}#exception_count]. Each requires analyst "
        "review and, if accepted, documented mitigants and approval at the appropriate authority level."
    )
    lines += ["", "| Rule | Description | Actual | Limit | Severity |", "|---|---|---|---|---|"]
    for e in pc.exceptions:
        if e.metric in ("dscr", "tdcr", "stressed_tdcr", "current_ratio"):
            a, lim = mult(e.actual), mult(e.limit)
        elif e.metric == "months_line_exceeded":
            a, lim = f"{e.actual:.0f}", f"{e.limit:.0f}"
        else:
            a, lim = pct(e.actual), pct(e.limit)
        lines.append(
            f"| {e.rule_id} | {e.description} | {a} [{deal}#{e.rule_id}.actual] | "
            f"{lim} [{deal}#{e.rule_id}.limit] | {e.severity.value} |"
        )
    return lines


def _header(loan: LoanRequest) -> list[str]:
    L = f"loan:{loan.deal_id}"
    return [
        f"# Credit Memo (Draft) - {loan.borrower_name}",
        "",
        f"**Deal:** {loan.deal_id}  |  **Type:** {loan.loan_type.value} / {loan.property_type.value}  |  "
        "**Status:** DRAFT - PENDING ANALYST REVIEW",
        "",
        "## Request",
        "",
        f"The borrower requests a loan of {money(loan.loan_amount)} [{L}#loan_amount] at a note rate of "
        f"{pct(loan.interest_rate, 2)} [{L}#interest_rate], amortizing over {loan.amortization_years} years "
        f"[{L}#amortization_years] with a {loan.term_years}-year term [{L}#term_years]. "
        f"The appraised value is {money(loan.appraised_value)} [{L}#appraised_value].",
        "",
    ]


def _footer() -> list[str]:
    return [
        "",
        "## Analyst decision",
        "",
        "_To be completed by the credit analyst. The assistant does not recommend approval or decline._",
        "",
        "---",
        MEMO_DISCLAIMER,
    ]


def draft_cre_memo(
    loan: LoanRequest, rr: RentRoll, t12: T12Statement, m: CREMetrics, pc: PolicyCheck, ledger: EvidenceLedger
) -> str:
    C, R, T = m.calc_id, f"doc:{rr.doc_id}", f"doc:{t12.doc_id}"
    lines = _header(loan)
    lines += [
        "## Property and rent roll",
        "",
        f"The rent roll lists {rr.unit_count} units [{R}#unit_count], of which {rr.occupied_units} are occupied "
        f"[{R}#occupied_units], for physical occupancy of {pct(rr.physical_occupancy)} [{R}#physical_occupancy]. "
        f"In-place annual contract rent is {money(rr.in_place_annual_rent)} [{R}#in_place_annual_rent].",
        "",
        "## Underwritten cash flow",
        "",
        "| Item | Amount |",
        "|---|---|",
        f"| Gross potential rent | {money(m.gross_potential_rent)} [{C}#gross_potential_rent] |",
        f"| Underwritten vacancy | {pct(m.underwritten_vacancy_rate)} [{C}#underwritten_vacancy_rate] |",
        f"| Effective gross income | {money(m.effective_gross_income)} [{C}#effective_gross_income] |",
        f"| Operating expenses | {money(m.operating_expenses)} [{C}#operating_expenses] |",
        f"| Replacement reserves | {money(m.replacement_reserves)} [{C}#replacement_reserves] |",
        f"| Net operating income | {money(m.noi)} [{C}#noi] |",
        f"| Annual debt service | {money(m.annual_debt_service)} [{C}#annual_debt_service] |",
        "",
    ]
    if "real_estate_taxes" in t12.totals_by_category():
        lines.append(
            f"T-12 real estate taxes were {money(abs(t12.total('real_estate_taxes')))} "
            f"[{T}#real_estate_taxes]."
        )
    if t12.unmapped_labels:
        lines.append(
            f"Note: {len(t12.unmapped_labels)} [{T}#unmapped_count] T-12 line item(s) could not be "
            "categorised and are "
            "excluded from NOI pending analyst review: " + "; ".join(t12.unmapped_labels) + "."
        )
    lines += [
        "",
        "## Key metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| DSCR | {mult(m.dscr)} [{C}#dscr] |",
        f"| Debt yield | {pct(m.debt_yield)} [{C}#debt_yield] |",
        f"| LTV | {pct(m.ltv)} [{C}#ltv] |",
        f"| Breakeven occupancy | {pct(m.breakeven_occupancy)} [{C}#breakeven_occupancy] |",
        "",
        "Maximum supportable loan by constraint: DSCR "
        f"{money(m.max_loan_by_dscr)} [{C}#max_loan_by_dscr], LTV {money(m.max_loan_by_ltv)} "
        f"[{C}#max_loan_by_ltv], debt yield {money(m.max_loan_by_debt_yield)} [{C}#max_loan_by_debt_yield].",
        "",
    ]
    lines += _exceptions_section(pc)
    lines += _footer()
    return "\n".join(lines)


def draft_agri_memo(
    loan: LoanRequest, farm_doc_id: str, m: FarmMetrics, pc: PolicyCheck, ledger: EvidenceLedger
) -> str:
    C, F = m.calc_id, f"doc:{farm_doc_id}"
    lines = _header(loan)
    lines += [
        "## Operation cash flow",
        "",
        "| Item | Amount |",
        "|---|---|",
        f"| Gross farm revenue | {money(m.annual_revenue)} [{C}#annual_revenue] |",
        f"| Operating expenses | {money(m.annual_operating_expenses)} [{C}#annual_operating_expenses] |",
        f"| Cash available for debt service | {money(m.cash_available_for_debt_service)} "
        f"[{C}#cash_available_for_debt_service] |",
        f"| Existing debt service | {money(m.existing_debt_service)} [{C}#existing_debt_service] |",
        f"| Proposed debt service | {money(m.proposed_debt_service)} [{C}#proposed_debt_service] |",
        "",
        f"Base-case term debt coverage is {mult(m.tdcr)} [{C}#tdcr] and LTV is {pct(m.ltv)} [{C}#ltv]. "
        f"Working capital is {money(m.working_capital)} [{C}#working_capital] with a current ratio of "
        f"{mult(m.current_ratio)} [{C}#current_ratio]. The operating line limit is "
        f"{money(ledger.get(f'{F}#operating_line_limit').value)} [{F}#operating_line_limit].",  # type: ignore[union-attr]
        "",
        "## Seasonal cash-flow stress",
        "",
        "| Scenario | TDCR | Lowest month-end cash | Peak line draw | Months over line |",
        "|---|---|---|---|---|",
    ]
    for s in m.stress:
        a = f"{C}#stress.{s.scenario}"
        lines.append(
            f"| {s.scenario} | {mult(s.tdcr)} [{a}.tdcr] | {money(s.min_month_end_cash)} [{a}.min_month_end_cash] | "
            f"{money(s.peak_line_draw)} [{a}.peak_line_draw] | {s.months_line_exceeded} [{a}.months_line_exceeded] |"
        )
    lines.append("")
    lines += _exceptions_section(pc)
    lines += _footer()
    return "\n".join(lines)

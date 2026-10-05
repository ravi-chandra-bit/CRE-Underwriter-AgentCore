import pytest

from underwriter.memo import EvidenceLedger, verify_citations
from underwriter.models import CREMetrics, PropertyType
from underwriter.policy import check_cre_policy, find_decision_language, is_forbidden, requires_approval


def _metrics(**kw) -> CREMetrics:
    base = dict(
        calc_id="calc:cre:X",
        gross_potential_rent=1,
        effective_gross_income=1,
        underwritten_vacancy_rate=0.05,
        operating_expenses=1,
        replacement_reserves=0,
        noi=1,
        annual_debt_service=1,
        dscr=1.30,
        debt_yield=0.10,
        ltv=0.70,
        breakeven_occupancy=0.80,
        max_loan_by_dscr=0,
        max_loan_by_ltv=0,
        max_loan_by_debt_yield=0,
    )
    base.update(kw)
    return CREMetrics(**base)


def test_property_specific_rule_replaces_generic():
    # 1.30x passes the generic 1.25x rule but fails the 1.35x office rule.
    office = check_cre_policy(_metrics(), PropertyType.OFFICE)
    # Office: 1.35x DSCR and 65% LTV limits apply instead of the generic 1.25x / 75%.
    assert sorted(e.rule_id for e in office.exceptions) == ["CP-3.1.3", "CP-3.2.2"]
    mf = check_cre_policy(_metrics(), PropertyType.MULTIFAMILY)
    assert mf.exceptions == []


def test_exception_carries_citation_to_calc():
    pc = check_cre_policy(_metrics(dscr=1.10), PropertyType.RETAIL)
    e = next(e for e in pc.exceptions if e.metric == "dscr")
    assert e.calc_ref == "calc:cre:X#dscr" and e.limit == 1.25


@pytest.mark.parametrize(
    "text,hit",
    [
        ("We recommend approval of the loan.", True),
        ("The loan should be declined given the DSCR shortfall.", True),
        ("Final decision: APPROVE", True),
        ("The assistant does not recommend approval or decline.", False),
        ("DSCR of 1.10x is below the 1.25x policy minimum; the analyst may consider mitigants.", False),
    ],
)
def test_decision_language(text, hit):
    assert bool(find_decision_language(text)) is hit


def test_forbidden_and_approval_tools_match_gateway_prefix():
    assert is_forbidden("los___record_credit_decision")
    assert is_forbidden("send_adverse_action_notice")
    assert not is_forbidden("uwcalc___compute_cre_metrics")
    assert requires_approval("los___submit_memo_for_analyst_review")


def _ledger() -> EvidenceLedger:
    led = EvidenceLedger(deal_id="X")
    led.add("calc:cre:X#dscr", 1.3152)
    led.add("calc:cre:X#ltv", 0.6954)
    led.add("calc:cre:X#noi", 238664.4)
    return led


def test_citation_verifier_accepts_rounded_display():
    memo = (
        "DSCR is 1.32x [calc:cre:X#dscr] and LTV is 69.5% [calc:cre:X#ltv]. NOI is $238,664 [calc:cre:X#noi]."
    )
    rep = verify_citations(memo, _ledger())
    assert rep.numeric_claims == 3 and rep.faithfulness == 1.0


def test_citation_verifier_catches_wrong_number_missing_cite_and_fabricated_anchor():
    memo = "DSCR is 1.45x [calc:cre:X#dscr].\nNOI is $238,664.\nDebt yield is 9.9% [calc:cre:X#debt_yield]."
    rep = verify_citations(memo, _ledger())
    assert rep.supported_claims == 0
    reasons = sorted(c.reason for c in rep.unsupported)
    assert reasons == ["cited value does not match", "cited value does not match", "no citation"]
    assert rep.fabricated_anchors == ["calc:cre:X#debt_yield"]


def test_citation_verifier_ignores_ids_and_dates():
    memo = "Deal CRE-001 under rule CP-3.1.1 per the T-12 ending 2026-08-31 for price_down_15."
    assert verify_citations(memo, _ledger()).numeric_claims == 0

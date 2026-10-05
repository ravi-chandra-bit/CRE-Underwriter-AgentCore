import pytest

from underwriter.calculators import annual_debt_service, max_loan_for_payment, periodic_payment, run_scenario
from underwriter.calculators.cre import compute_cre_metrics
from underwriter.models import (
    FarmFinancials,
    FarmMonth,
    LoanRequest,
    RentRoll,
    RentRollUnit,
    StressScenario,
    T12LineItem,
    T12Statement,
)


def test_periodic_payment_matches_textbook_value():
    # $1,000,000 at 6% over 30 years, monthly: $5,995.51
    assert periodic_payment(1_000_000, 0.06, 30) == pytest.approx(5995.51, abs=0.01)


def test_max_loan_is_inverse_of_payment():
    ads = annual_debt_service(2_500_000, 0.0675, 25)
    assert max_loan_for_payment(ads, 0.0675, 25) == pytest.approx(2_500_000, rel=1e-6)


def _loan(**kw) -> LoanRequest:
    base = dict(
        deal_id="T-1",
        borrower_name="Test",
        loan_type="CRE",
        property_type="multifamily",
        loan_amount=1_000_000,
        interest_rate=0.06,
        amortization_years=30,
        term_years=10,
        appraised_value=1_600_000,
    )
    base.update(kw)
    return LoanRequest(**base)


def test_cre_metrics_follow_documented_convention():
    rr = RentRoll(
        doc_id="RR",
        units=[
            RentRollUnit(unit_id=str(i), monthly_rent=1000, occupied=i < 9, source_row=i) for i in range(10)
        ],
    )
    t12 = T12Statement(
        doc_id="T12",
        line_items=[
            T12LineItem(label="GPR", category="gross_potential_rent", annual_total=120_000, source_row=1),
            T12LineItem(label="Vac", category="vacancy_loss", annual_total=-6_000, source_row=2),
            T12LineItem(label="Taxes", category="real_estate_taxes", annual_total=15_000, source_row=3),
            T12LineItem(label="Mgmt", category="management_fee", annual_total=1_000, source_row=4),
            T12LineItem(label="Capex", category="capital_expenditures", annual_total=50_000, source_row=5),
        ],
    )
    m = compute_cre_metrics(_loan(loan_amount=500_000), rr, t12)
    # vacancy = max(rent roll 10%, T-12 5%, floor 5%) = 10%
    assert m.underwritten_vacancy_rate == pytest.approx(0.10)
    assert m.effective_gross_income == pytest.approx(108_000)
    # mgmt floored at 3% of EGI = 3,240; capex excluded; reserves 10 units x 300
    assert m.operating_expenses == pytest.approx(15_000 + 3_240)
    assert m.noi == pytest.approx(108_000 - 18_240 - 3_000)
    assert m.dscr == pytest.approx(m.noi / m.annual_debt_service, abs=1e-4)
    assert m.ltv == pytest.approx(500_000 / 1_600_000, abs=1e-4)


def test_farm_stress_lowers_coverage_and_tracks_line_usage():
    months = [
        FarmMonth(
            month=i, crop_revenue=300_000 if i == 10 else 0, operating_expenses=12_000, family_living=5_000
        )
        for i in range(1, 13)
    ]
    farm = FarmFinancials(
        doc_id="F",
        months=months,
        opening_cash=10_000,
        operating_line_limit=100_000,
        current_assets=200_000,
        current_liabilities=100_000,
    )
    loan = _loan(loan_type="AGRI", property_type="farmland", payments_per_year=1, amortization_years=20)
    base = run_scenario(loan, farm, StressScenario(name="base"))
    down = run_scenario(loan, farm, StressScenario(name="down", crop_price_shock=-0.2))
    assert down.tdcr < base.tdcr
    # Cash runs negative before the October harvest and is financed on the operating line.
    assert base.peak_line_draw > 0
    assert base.min_cash_month < 10

"""Deterministic agricultural cash-flow and seasonal stress calculations.

Farm repayment capacity is seasonal: cash arrives at harvest while inputs, family living
and existing payments go out all year. The stress test walks the operation month by
month under each scenario and reports how deep the operating line is drawn and whether
term debt is still covered.
"""

from __future__ import annotations

from typing import Any

from underwriter.calculators.cre import annual_debt_service
from underwriter.config import load_policy
from underwriter.models import FarmFinancials, FarmMetrics, LoanRequest, StressResult, StressScenario

TAX_PAYMENT_MONTH = 4


def payment_month(farm: FarmFinancials) -> int:
    """Annual ag payments are scheduled for the month with the largest crop receipts."""
    best = max(farm.months, key=lambda m: (m.crop_revenue, -m.month))
    return best.month


def run_scenario(loan: LoanRequest, farm: FarmFinancials, scenario: StressScenario) -> StressResult:
    crop_factor = (1 + scenario.crop_price_shock) * (1 + scenario.yield_shock)
    cost_factor = 1 + scenario.input_cost_shock
    proposed_ds = annual_debt_service(
        loan.loan_amount,
        loan.interest_rate + scenario.rate_shock_bps / 10_000,
        loan.amortization_years,
        loan.payments_per_year,
    )
    pay_month = payment_month(farm)

    cash = farm.opening_cash
    min_cash, min_month = float("inf"), 1
    peak_draw = 0.0
    exceeded = 0
    revenue = opex = family = existing = 0.0

    for m in sorted(farm.months, key=lambda x: x.month):
        m_rev = m.crop_revenue * crop_factor + m.livestock_revenue + m.government_payments + m.other_revenue
        m_opex = m.operating_expenses * cost_factor
        revenue += m_rev
        opex += m_opex
        family += m.family_living
        existing += m.existing_debt_service

        cash += m_rev - m_opex - m.family_living - m.existing_debt_service
        if m.month == TAX_PAYMENT_MONTH:
            cash -= farm.income_taxes
        if m.month == pay_month:
            cash -= proposed_ds

        if cash < min_cash:
            min_cash, min_month = cash, m.month
        draw = max(-cash, 0.0)
        peak_draw = max(peak_draw, draw)
        if draw > farm.operating_line_limit:
            exceeded += 1

    cads = revenue - opex - family - farm.income_taxes
    total_ds = existing + proposed_ds
    return StressResult(
        scenario=scenario.name,
        net_cash_available=round(cads, 2),
        tdcr=round(cads / total_ds, 4) if total_ds else 0.0,
        min_month_end_cash=round(min_cash, 2),
        min_cash_month=min_month,
        peak_line_draw=round(peak_draw, 2),
        months_line_exceeded=exceeded,
    )


def compute_farm_metrics(
    loan: LoanRequest, farm: FarmFinancials, policy: dict[str, Any] | None = None
) -> FarmMetrics:
    policy = policy or load_policy()
    scenarios = [StressScenario(**s) for s in policy["agri_conventions"]["stress_scenarios"]]
    stress = [run_scenario(loan, farm, s) for s in scenarios]
    base = stress[0]

    revenue = round(sum(m.revenue for m in farm.months), 2)
    opex = farm.annual("operating_expenses")
    existing = farm.annual("existing_debt_service")
    proposed = annual_debt_service(
        loan.loan_amount, loan.interest_rate, loan.amortization_years, loan.payments_per_year
    )
    wc = farm.current_assets - farm.current_liabilities

    return FarmMetrics(
        calc_id=f"calc:agri:{loan.deal_id}",
        inputs={
            "loan_amount": loan.loan_amount,
            "interest_rate": loan.interest_rate,
            "amortization_years": loan.amortization_years,
            "appraised_value": loan.appraised_value,
            "farm_doc": farm.doc_id,
            "payment_month": payment_month(farm),
        },
        formula=(
            "CADS = revenue - operating expenses - family living - income taxes; "
            "TDCR = CADS / (existing + proposed annual debt service); "
            "stress shocks crop receipts (price x yield), inputs and rate, walked month by month"
        ),
        annual_revenue=revenue,
        annual_operating_expenses=opex,
        net_farm_income=round(revenue - opex - farm.depreciation, 2),
        cash_available_for_debt_service=base.net_cash_available,
        existing_debt_service=existing,
        proposed_debt_service=proposed,
        tdcr=base.tdcr,
        ltv=round(loan.loan_amount / loan.appraised_value, 4),
        working_capital=round(wc, 2),
        current_ratio=round(farm.current_assets / farm.current_liabilities, 4)
        if farm.current_liabilities
        else 0.0,
        stress=stress,
    )

"""Deterministic CRE underwriting math.

The LLM never computes these numbers. It calls these functions (locally, or through the
AgentCore Gateway Lambda that wraps them) and cites the returned `calc_id` in the memo.
Each function is pure: same inputs, same outputs, which is what makes the evaluation
suite and model-risk validation possible.
"""

from __future__ import annotations

from typing import Any

from underwriter.config import load_policy
from underwriter.models import CREMetrics, LoanRequest, PropertyType, RentRoll, T12Statement


def periodic_payment(
    principal: float, annual_rate: float, amort_years: int, payments_per_year: int = 12
) -> float:
    """Level payment that fully amortises `principal` over `amort_years`."""
    r = annual_rate / payments_per_year
    n = amort_years * payments_per_year
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def annual_debt_service(
    principal: float, annual_rate: float, amort_years: int, payments_per_year: int = 12
) -> float:
    """Annual debt service on an amortising basis.

    Interest-only periods are deliberately ignored: policy sizes on the amortising
    payment so DSCR does not look stronger during an IO period.
    """
    return round(
        periodic_payment(principal, annual_rate, amort_years, payments_per_year) * payments_per_year, 2
    )


def max_loan_for_payment(
    annual_payment: float, annual_rate: float, amort_years: int, payments_per_year: int = 12
) -> float:
    """Inverse of `periodic_payment`: the principal a given annual payment can carry."""
    p = annual_payment / payments_per_year
    r = annual_rate / payments_per_year
    n = amort_years * payments_per_year
    if r == 0:
        return p * n
    return p * (1 - (1 + r) ** -n) / r


def _abs_total(t12: T12Statement, category: str) -> float:
    return abs(t12.total(category))


def compute_cre_metrics(
    loan: LoanRequest,
    rent_roll: RentRoll,
    t12: T12Statement,
    policy: dict[str, Any] | None = None,
) -> CREMetrics:
    policy = policy or load_policy()
    conv = policy["underwriting_conventions"]
    ptype = loan.property_type.value

    # Income ------------------------------------------------------------------------
    gpr = round(sum(u.monthly_rent for u in rent_roll.units) * 12, 2)
    in_place = rent_roll.in_place_annual_rent
    rr_vacancy = 1 - in_place / gpr if gpr else 1.0

    t12_gpr = _abs_total(t12, "gross_potential_rent")
    t12_losses = sum(_abs_total(t12, c) for c in ("vacancy_loss", "concessions", "bad_debt"))
    t12_vacancy = t12_losses / t12_gpr if t12_gpr else 0.0

    floor = conv["vacancy_floor"].get(ptype, 0.05)
    vacancy = max(rr_vacancy, t12_vacancy, floor)

    other_income = t12.total("other_income")
    egi = gpr * (1 - vacancy) + other_income

    # Expenses ----------------------------------------------------------------------
    expense_cats = (
        "real_estate_taxes",
        "insurance",
        "utilities",
        "repairs_maintenance",
        "payroll",
        "general_admin",
        "marketing",
        "contract_services",
    )
    opex_ex_mgmt = sum(_abs_total(t12, c) for c in expense_cats)
    mgmt = max(_abs_total(t12, "management_fee"), conv["management_fee_floor"] * egi)
    opex = opex_ex_mgmt + mgmt

    if loan.property_type == PropertyType.MULTIFAMILY:
        reserves = conv["reserves_per_unit"] * rent_roll.unit_count
    else:
        reserves = conv["reserves_per_sf"] * sum(u.square_feet or 0 for u in rent_roll.units)

    noi = egi - opex - reserves

    # Debt metrics ------------------------------------------------------------------
    ads = annual_debt_service(
        loan.loan_amount, loan.interest_rate, loan.amortization_years, loan.payments_per_year
    )
    sizing = conv["sizing"]
    breakeven = (opex + reserves + ads - other_income) / gpr if gpr else 1.0

    return CREMetrics(
        calc_id=f"calc:cre:{loan.deal_id}",
        inputs={
            "loan_amount": loan.loan_amount,
            "interest_rate": loan.interest_rate,
            "amortization_years": loan.amortization_years,
            "appraised_value": loan.appraised_value,
            "rent_roll_doc": rent_roll.doc_id,
            "t12_doc": t12.doc_id,
            "vacancy_floor": floor,
        },
        formula=(
            "EGI = GPR*(1-max(rent-roll vacancy, T-12 vacancy, floor)) + other income; "
            "NOI = EGI - opex (mgmt fee floored) - reserves; DSCR = NOI/ADS (amortising); "
            "DY = NOI/loan; LTV = loan/value"
        ),
        gross_potential_rent=round(gpr, 2),
        effective_gross_income=round(egi, 2),
        underwritten_vacancy_rate=round(vacancy, 4),
        operating_expenses=round(opex, 2),
        replacement_reserves=round(reserves, 2),
        noi=round(noi, 2),
        annual_debt_service=ads,
        dscr=round(noi / ads, 4) if ads else 0.0,
        debt_yield=round(noi / loan.loan_amount, 4),
        ltv=round(loan.loan_amount / loan.appraised_value, 4),
        breakeven_occupancy=round(breakeven, 4),
        max_loan_by_dscr=round(
            max_loan_for_payment(
                max(noi, 0) / sizing["min_dscr"],
                loan.interest_rate,
                loan.amortization_years,
                loan.payments_per_year,
            ),
            -3,
        ),
        max_loan_by_ltv=round(sizing["max_ltv"] * loan.appraised_value, -3),
        max_loan_by_debt_yield=round(max(noi, 0) / sizing["min_debt_yield"], -3),
    )

"""Domain models shared by ingestion, calculators, policy, memo drafting and the agent tools.

Every model is a plain pydantic object so it can be serialised into a tool result,
a Lambda response or an evaluation report without custom encoders.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class LoanType(StrEnum):
    CRE = "CRE"
    AGRI = "AGRI"


class PropertyType(StrEnum):
    MULTIFAMILY = "multifamily"
    RETAIL = "retail"
    OFFICE = "office"
    INDUSTRIAL = "industrial"
    FARMLAND = "farmland"


class Severity(StrEnum):
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"


# --------------------------------------------------------------------------------------
# Loan request
# --------------------------------------------------------------------------------------


class LoanRequest(BaseModel):
    deal_id: str
    borrower_name: str
    loan_type: LoanType
    property_type: PropertyType
    loan_amount: float = Field(gt=0)
    interest_rate: float = Field(gt=0, lt=0.5, description="Annual note rate as a decimal, e.g. 0.0675")
    amortization_years: int = Field(gt=0, le=40)
    term_years: int = Field(gt=0, le=40)
    interest_only_years: int = Field(default=0, ge=0)
    appraised_value: float = Field(gt=0)
    # Agricultural requests repay annually after harvest; CRE monthly.
    payments_per_year: int = Field(default=12)
    purpose: str = ""


# --------------------------------------------------------------------------------------
# CRE source documents
# --------------------------------------------------------------------------------------


class RentRollUnit(BaseModel):
    unit_id: str
    tenant: str | None = None
    square_feet: float | None = None
    monthly_rent: float = 0.0
    occupied: bool = True
    lease_end: date | None = None
    source_row: int = Field(description="1-based row number in the source document, used for citations")


class RentRoll(BaseModel):
    doc_id: str
    units: list[RentRollUnit]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unit_count(self) -> int:
        return len(self.units)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def occupied_units(self) -> int:
        return sum(1 for u in self.units if u.occupied)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def physical_occupancy(self) -> float:
        return round(self.occupied_units / self.unit_count, 4) if self.units else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def in_place_annual_rent(self) -> float:
        """Annualised contract rent of occupied units."""
        return round(sum(u.monthly_rent for u in self.units if u.occupied) * 12, 2)


# Canonical T-12 categories. Anything mapped to an EXCLUDED category is shown in the
# memo but does not flow into NOI (capital items, debt service, non-cash items).
T12_INCOME = ("gross_potential_rent", "vacancy_loss", "concessions", "bad_debt", "other_income")
T12_EXPENSE = (
    "real_estate_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "management_fee",
    "payroll",
    "general_admin",
    "marketing",
    "contract_services",
)
T12_EXCLUDED = ("capital_expenditures", "debt_service", "depreciation_amortization")


class T12LineItem(BaseModel):
    label: str = Field(description="Label exactly as it appears in the source document")
    category: str = Field(description="Canonical category this line was mapped to")
    monthly: list[float] = Field(default_factory=list)
    annual_total: float
    source_row: int


class T12Statement(BaseModel):
    doc_id: str
    period_end: str | None = None
    line_items: list[T12LineItem]
    unmapped_labels: list[str] = Field(default_factory=list)

    def total(self, category: str) -> float:
        return round(sum(li.annual_total for li in self.line_items if li.category == category), 2)

    def totals_by_category(self) -> dict[str, float]:
        cats = {li.category for li in self.line_items}
        return {c: self.total(c) for c in sorted(cats)}


# --------------------------------------------------------------------------------------
# Agricultural source documents
# --------------------------------------------------------------------------------------


class FarmMonth(BaseModel):
    month: int = Field(ge=1, le=12)
    crop_revenue: float = 0.0
    livestock_revenue: float = 0.0
    government_payments: float = 0.0
    other_revenue: float = 0.0
    operating_expenses: float = 0.0
    family_living: float = 0.0
    existing_debt_service: float = 0.0
    source_row: int = 0

    @property
    def revenue(self) -> float:
        return self.crop_revenue + self.livestock_revenue + self.government_payments + self.other_revenue


class FarmFinancials(BaseModel):
    doc_id: str
    operation_name: str = ""
    months: list[FarmMonth]
    opening_cash: float = 0.0
    operating_line_limit: float = 0.0
    depreciation: float = 0.0
    income_taxes: float = 0.0
    current_assets: float = 0.0
    current_liabilities: float = 0.0

    def annual(self, attr: str) -> float:
        return round(sum(getattr(m, attr) for m in self.months), 2)


# --------------------------------------------------------------------------------------
# Calculator outputs
# --------------------------------------------------------------------------------------


class CalcResult(BaseModel):
    """Base for every deterministic calculation. `calc_id` is the citation anchor."""

    calc_id: str
    inputs: dict[str, float | int | str | None] = Field(default_factory=dict)
    formula: str = ""


class CREMetrics(CalcResult):
    gross_potential_rent: float
    effective_gross_income: float
    underwritten_vacancy_rate: float
    operating_expenses: float
    replacement_reserves: float
    noi: float
    annual_debt_service: float
    dscr: float
    debt_yield: float
    ltv: float
    breakeven_occupancy: float
    max_loan_by_dscr: float
    max_loan_by_ltv: float
    max_loan_by_debt_yield: float


class StressScenario(BaseModel):
    name: str
    crop_price_shock: float = 0.0
    yield_shock: float = 0.0
    input_cost_shock: float = 0.0
    rate_shock_bps: int = 0


class StressResult(BaseModel):
    scenario: str
    net_cash_available: float
    tdcr: float
    min_month_end_cash: float
    min_cash_month: int
    peak_line_draw: float
    months_line_exceeded: int


class FarmMetrics(CalcResult):
    annual_revenue: float
    annual_operating_expenses: float
    net_farm_income: float
    cash_available_for_debt_service: float
    existing_debt_service: float
    proposed_debt_service: float
    tdcr: float
    ltv: float
    working_capital: float
    current_ratio: float
    stress: list[StressResult]


# --------------------------------------------------------------------------------------
# Policy + memo
# --------------------------------------------------------------------------------------


class PolicyException(BaseModel):
    rule_id: str
    metric: str
    actual: float
    limit: float
    comparator: str
    severity: Severity
    description: str
    calc_ref: str = Field(description="Citation anchor of the calculation that triggered the exception")


class PolicyCheck(BaseModel):
    calc_id: str
    policy_version: str
    exceptions: list[PolicyException]
    rules_evaluated: int


class CreditMemo(BaseModel):
    deal_id: str
    markdown: str
    status: str = "DRAFT - PENDING ANALYST REVIEW"

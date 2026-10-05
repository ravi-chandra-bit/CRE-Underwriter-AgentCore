"""Evidence ledger: every figure the memo may cite, keyed by a stable citation anchor.

Anchors look like `calc:cre:D001#dscr`, `doc:D001-T12#real_estate_taxes`,
`loan:D001#loan_amount` or `policy:D001#CP-3.1.1.limit`. The memo cites them in square
brackets, e.g. "DSCR of 1.32x [calc:cre:D001#dscr]", and the citation verifier checks
every number in the memo against the ledger value it cites.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from underwriter.models import (
    CREMetrics,
    FarmFinancials,
    FarmMetrics,
    LoanRequest,
    PolicyCheck,
    RentRoll,
    T12Statement,
)

Kind = Literal["currency", "percent", "multiple", "count", "text"]


class Evidence(BaseModel):
    anchor: str
    value: float | str
    kind: Kind
    label: str


_PERCENT_FIELDS = {
    "underwritten_vacancy_rate",
    "debt_yield",
    "ltv",
    "breakeven_occupancy",
    "physical_occupancy",
    "interest_rate",
    "current_ratio_pct",
}
_MULTIPLE_FIELDS = {"dscr", "tdcr", "current_ratio", "stressed_tdcr"}
_COUNT_FIELDS = {
    "unit_count",
    "occupied_units",
    "amortization_years",
    "term_years",
    "interest_only_years",
    "min_cash_month",
    "months_line_exceeded",
    "payments_per_year",
    "rules_evaluated",
}


def _kind(field: str) -> Kind:
    if field in _PERCENT_FIELDS:
        return "percent"
    if field in _MULTIPLE_FIELDS:
        return "multiple"
    if field in _COUNT_FIELDS:
        return "count"
    return "currency"


class EvidenceLedger(BaseModel):
    deal_id: str
    items: dict[str, Evidence] = {}

    def add(self, anchor: str, value: float | str, kind: Kind | None = None, label: str = "") -> None:
        field = anchor.split("#")[-1].split(".")[-1]
        self.items[anchor] = Evidence(
            anchor=anchor, value=value, kind=kind or _kind(field), label=label or field
        )

    def get(self, anchor: str) -> Evidence | None:
        return self.items.get(anchor)

    # -- builders -------------------------------------------------------------------

    def add_loan(self, loan: LoanRequest) -> None:
        for f in ("loan_amount", "interest_rate", "amortization_years", "term_years", "appraised_value"):
            self.add(f"loan:{loan.deal_id}#{f}", float(getattr(loan, f)), label=f"Loan request: {f}")

    def add_rent_roll(self, rr: RentRoll) -> None:
        for f in ("unit_count", "occupied_units", "physical_occupancy", "in_place_annual_rent"):
            self.add(f"doc:{rr.doc_id}#{f}", float(getattr(rr, f)), label=f"Rent roll: {f}")

    def add_t12(self, t12: T12Statement) -> None:
        for cat, total in t12.totals_by_category().items():
            self.add(f"doc:{t12.doc_id}#{cat}", abs(total), "currency", f"T-12: {cat}")
        self.add(
            f"doc:{t12.doc_id}#unmapped_count",
            float(len(t12.unmapped_labels)),
            "count",
            "T-12 unmapped lines",
        )

    def add_farm_doc(self, farm: FarmFinancials) -> None:
        for f in (
            "opening_cash",
            "operating_line_limit",
            "current_assets",
            "current_liabilities",
            "depreciation",
            "income_taxes",
        ):
            self.add(f"doc:{farm.doc_id}#{f}", float(getattr(farm, f)), "currency", f"Farm financials: {f}")

    def add_cre_metrics(self, m: CREMetrics) -> None:
        for f, v in m.model_dump(exclude={"calc_id", "inputs", "formula"}).items():
            self.add(f"{m.calc_id}#{f}", float(v), label=f"CRE calc: {f}")

    def add_farm_metrics(self, m: FarmMetrics) -> None:
        for f, v in m.model_dump(exclude={"calc_id", "inputs", "formula", "stress"}).items():
            self.add(f"{m.calc_id}#{f}", float(v), label=f"Farm calc: {f}")
        for s in m.stress:
            for f, v in s.model_dump(exclude={"scenario"}).items():
                self.add(f"{m.calc_id}#stress.{s.scenario}.{f}", float(v), label=f"Stress {s.scenario}: {f}")

    def add_policy(self, pc: PolicyCheck) -> None:
        self.add(
            f"{pc.calc_id}#rules_evaluated", float(pc.rules_evaluated), "count", "Policy rules evaluated"
        )
        self.add(f"{pc.calc_id}#exception_count", float(len(pc.exceptions)), "count", "Policy exceptions")
        for e in pc.exceptions:
            kind = _kind(e.metric)
            self.add(f"{pc.calc_id}#{e.rule_id}.actual", e.actual, kind, f"{e.rule_id} actual")
            self.add(f"{pc.calc_id}#{e.rule_id}.limit", e.limit, kind, f"{e.rule_id} limit")

    def summary(self) -> list[dict[str, object]]:
        """Compact list given to the model so it can cite anchors without seeing raw documents."""
        return [{"anchor": e.anchor, "value": e.value, "kind": e.kind} for e in self.items.values()]

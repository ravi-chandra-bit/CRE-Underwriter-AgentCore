"""Trailing-twelve-month operating statement parser.

Line labels vary by owner and property manager, so each label is mapped to a canonical
category by an ordered keyword table. Labels the table cannot map are returned in
`unmapped_labels`; they are excluded from NOI until an analyst (or the agent, with an
audited rationale) supplies a mapping through `label_overrides`.
"""

from __future__ import annotations

import csv
import io
import re

from underwriter.ingestion.normalize import month_of, norm_header, try_money
from underwriter.models import T12_EXCLUDED, T12_EXPENSE, T12_INCOME, T12LineItem, T12Statement

_SECTION_INCOME = re.compile(r"^(income|revenue|revenues|operating income|rental income)$", re.I)
_SECTION_EXPENSE = re.compile(r"^(expenses?|operating expenses|opex|non operating|below the line)$", re.I)

VALID_CATEGORIES = T12_INCOME + T12_EXPENSE + T12_EXCLUDED

# Order matters: the first rule that matches wins.
LABEL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("depreciation_amortization", ("depreciation", "amortization")),
    ("debt_service", ("debt service", "mortgage", "interest expense", "principal")),
    ("capital_expenditures", ("capital", "capex", "cap ex", "improvements", "roof replacement")),
    ("vacancy_loss", ("vacancy", "vacant")),
    ("concessions", ("concession", "free rent", "loss to lease")),
    ("bad_debt", ("bad debt", "write off", "uncollect", "collection loss")),
    (
        "gross_potential_rent",
        (
            "gross potential",
            "gpr",
            "scheduled rent",
            "base rent",
            "rental income",
            "gross rent",
            "rent revenue",
            "rental revenue",
            "minimum rent",
            "contract rent",
            "rent income",
            "rents",
        ),
    ),
    (
        "other_income",
        (
            "other income",
            "laundry",
            "parking",
            "late fee",
            "fee income",
            "cam recover",
            "reimburse",
            "pet ",
            "pet fee",
            "storage",
            "misc income",
            "miscellaneous income",
            "application fee",
            "vending",
        ),
    ),
    ("management_fee", ("management", "mgmt")),
    ("payroll", ("payroll", "salar", "wages", "personnel", "on site staff", "benefits")),
    ("real_estate_taxes", ("real estate tax", "property tax", "re tax", "taxes")),
    ("insurance", ("insurance",)),
    ("utilities", ("utilit", "electric", "water", "sewer", "gas", "trash", "refuse")),
    ("repairs_maintenance", ("repair", "maint", "r m", "turnover", "make ready", "unit turn")),
    ("marketing", ("marketing", "advertis", "leasing commission", "promotion")),
    ("contract_services", ("contract", "landscap", "snow", "janitorial", "pest", "security", "elevator")),
    (
        "general_admin",
        ("admin", "g a", "office", "professional", "legal", "accounting", "telephone", "software"),
    ),
]

_SKIP = re.compile(
    r"^(total|net operating|noi|subtotal|income$|revenue$|expenses?$|operating expenses$|"
    r"cash flow|net income|effective gross)",
    re.I,
)


def classify_label(label: str) -> str | None:
    norm = " " + norm_header(label) + " "
    for category, keys in LABEL_RULES:
        if any(k in norm for k in keys):
            return category
    return None


def _conflicts(category: str, section: str) -> bool:
    if section == "income":
        return category not in T12_INCOME
    return category in T12_INCOME


def parse_t12(
    text: str, doc_id: str, label_overrides: dict[str, str] | None = None
) -> tuple[T12Statement, list[str]]:
    overrides = {k.strip().lower(): v for k, v in (label_overrides or {}).items()}
    rows = list(csv.reader(io.StringIO(text)))
    warnings: list[str] = []

    # Header row = first row with at least 10 month-like columns.
    h, month_cols, total_col, period_end = None, [], None, None
    for i, row in enumerate(rows[:20]):
        cols = [j for j, c in enumerate(row) if month_of(c) is not None]
        if len(cols) >= 10:
            h, month_cols = i, cols
            total_col = next(
                (
                    j
                    for j, c in enumerate(row)
                    if norm_header(c) in ("total", "t12", "t 12", "annual", "ytd", "12 mo total")
                ),
                None,
            )
            period_end = row[cols[-1]].strip()
            break
    if h is None:
        raise ValueError("T-12 header row with monthly columns not found")
    if len(month_cols) != 12:
        warnings.append(
            f"T-12 has {len(month_cols)} monthly columns; totals use the supplied total column "
            "or annualise the available months"
        )

    items: list[T12LineItem] = []
    unmapped: list[str] = []
    section: str | None = None
    for n, row in enumerate(rows[h + 1 :], start=h + 2):
        if not row or not row[0].strip():
            continue
        label = row[0].strip()
        monthly = [try_money(row[j]) if j < len(row) else None for j in month_cols]
        if all(v is None for v in monthly) or all(j >= len(row) or not row[j].strip() for j in month_cols):
            if _SECTION_INCOME.match(norm_header(label)):
                section = "income"
            elif _SECTION_EXPENSE.match(norm_header(label)):
                section = "expense"
            continue  # section headers
        if _SKIP.match(label):
            continue  # subtotal rows
        monthly_vals = [v or 0.0 for v in monthly]

        if total_col is not None and total_col < len(row) and try_money(row[total_col]) is not None:
            annual = try_money(row[total_col]) or 0.0
            if abs(annual - sum(monthly_vals)) > max(1.0, 0.005 * abs(annual)) and len(month_cols) == 12:
                warnings.append(
                    f"row {n} '{label}': total column {annual:,.0f} differs from sum of months "
                    f"{sum(monthly_vals):,.0f}; using sum of months"
                )
                annual = sum(monthly_vals)
        else:
            annual = sum(monthly_vals) * 12 / len(month_cols)

        override = overrides.get(label.lower())
        category = override or classify_label(label)
        if category and not override and section and _conflicts(category, section):
            # e.g. "Admin Fees" under INCOME matches the G&A expense rule; the statement's own
            # section says it is income. Route to the analyst/agent instead of guessing.
            warnings.append(
                f"row {n} '{label}': keyword rule says {category} but it sits in the {section} "
                "section; left unmapped for review"
            )
            category = None
        if category is None:
            unmapped.append(label)
            continue
        if category not in VALID_CATEGORIES:
            raise ValueError(f"invalid category override {category!r} for {label!r}")
        items.append(
            T12LineItem(
                label=label,
                category=category,
                monthly=monthly_vals,
                annual_total=round(annual, 2),
                source_row=n,
            )
        )

    if unmapped:
        warnings.append(
            f"{len(unmapped)} line item(s) could not be mapped and are excluded from NOI: "
            + "; ".join(unmapped)
        )
    return T12Statement(
        doc_id=doc_id, period_end=period_end, line_items=items, unmapped_labels=unmapped
    ), warnings

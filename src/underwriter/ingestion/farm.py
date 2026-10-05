"""Farm cash-flow projection parser.

Accepts a CSV with a key/value header block (opening cash, operating line, balance-sheet
items) followed by a monthly table in either orientation:
  * months as rows    (Month, Crop Sales, Livestock Sales, ...)
  * months as columns (Item, Jan, Feb, ..., Dec)
"""

from __future__ import annotations

import csv
import io

from underwriter.ingestion.normalize import match_header, month_of, norm_header, try_money
from underwriter.models import FarmFinancials, FarmMonth

FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "crop_revenue": ("crop sales", "crop revenue", "grain sales", "crop receipts", "crops"),
    "livestock_revenue": ("livestock sales", "livestock revenue", "cattle sales", "livestock", "milk sales"),
    "government_payments": (
        "government payments",
        "gov t payments",
        "govt payments",
        "usda payments",
        "program payments",
        "arc plc",
    ),
    "other_revenue": ("other income", "other revenue", "custom hire income", "misc income"),
    "operating_expenses": (
        "operating expenses",
        "farm operating expenses",
        "cash operating expenses",
        "input costs",
        "operating costs",
    ),
    "family_living": ("family living", "owner draws", "living expenses", "family draw"),
    "existing_debt_service": (
        "existing debt payments",
        "debt payments",
        "existing debt service",
        "term debt payments",
        "current debt service",
    ),
}

META_SYNONYMS: dict[str, tuple[str, ...]] = {
    "operation_name": ("operation", "operation name", "borrower", "farm name"),
    "opening_cash": ("opening cash", "beginning cash", "cash on hand"),
    "operating_line_limit": ("operating line", "operating line limit", "line of credit", "revolving line"),
    "depreciation": ("depreciation", "annual depreciation"),
    "income_taxes": ("income taxes", "income tax", "taxes"),
    "current_assets": ("current assets", "total current assets"),
    "current_liabilities": ("current liabilities", "total current liabilities"),
}


def _field_for(label: str, table: dict[str, tuple[str, ...]]) -> str | None:
    n = norm_header(label)
    for field, syns in table.items():
        if n in syns:
            return field
    for field, syns in table.items():
        if any(n.startswith(s) for s in syns):
            return field
    return None


def parse_farm_financials(text: str, doc_id: str) -> tuple[FarmFinancials, list[str]]:
    rows = [r for r in csv.reader(io.StringIO(text))]
    warnings: list[str] = []
    meta: dict[str, object] = {}

    table_start = None
    for i, row in enumerate(rows):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        months_in_row = sum(1 for c in cells if month_of(c) is not None)
        if months_in_row >= 10 or match_header(cells, ("month",)) == 0:
            table_start = i
            break
        field = _field_for(cells[0], META_SYNONYMS)
        if field and len(cells) > 1:
            meta[field] = cells[1] if field == "operation_name" else (try_money(cells[1]) or 0.0)
    if table_start is None:
        raise ValueError("monthly cash-flow table not found")

    header = [c.strip() for c in rows[table_start]]
    months: dict[int, FarmMonth] = {m: FarmMonth(month=m) for m in range(1, 13)}

    if match_header(header, ("month",)) == 0:  # months as rows
        col_field = {j: _field_for(h, FIELD_SYNONYMS) for j, h in enumerate(header) if j > 0}
        for c, f in col_field.items():
            if f is None:
                warnings.append(f"column '{header[c]}' not recognised; ignored")
        for n, row in enumerate(rows[table_start + 1 :], start=table_start + 2):
            if not row or not row[0].strip():
                continue
            m = month_of(row[0])
            if m is None:
                continue
            fm = months[m]
            fm.source_row = n
            for j, f in col_field.items():
                if f and j < len(row):
                    setattr(fm, f, getattr(fm, f) + (try_money(row[j]) or 0.0))
    else:  # months as columns
        month_cols = {j: month_of(h) for j, h in enumerate(header) if month_of(h)}
        for n, row in enumerate(rows[table_start + 1 :], start=table_start + 2):
            if not row or not row[0].strip() or norm_header(row[0]).startswith(("total", "net")):
                continue
            f = _field_for(row[0], FIELD_SYNONYMS)
            if f is None:
                warnings.append(f"row {n} '{row[0].strip()}' not recognised; ignored")
                continue
            for j, m in month_cols.items():
                if j < len(row):
                    setattr(months[m], f, getattr(months[m], f) + (try_money(row[j]) or 0.0))
                    months[m].source_row = table_start + 1
    missing = [
        k
        for k in ("opening_cash", "operating_line_limit", "current_assets", "current_liabilities")
        if k not in meta
    ]
    if missing:
        warnings.append("missing header values: " + ", ".join(missing))

    farm = FarmFinancials(doc_id=doc_id, months=list(months.values()), **meta)  # type: ignore[arg-type]
    return farm, warnings

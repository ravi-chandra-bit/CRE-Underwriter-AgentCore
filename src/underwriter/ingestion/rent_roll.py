"""Rent roll parser for CSV exports from common property-management systems."""

from __future__ import annotations

import csv
import io

from underwriter.ingestion.normalize import match_header, parse_date, parse_money, try_money
from underwriter.models import RentRoll, RentRollUnit

UNIT = ("unit", "unit no", "unit number", "suite", "space", "apt")
TENANT = ("tenant", "tenant name", "lessee", "resident", "occupant")
SQFT = ("sf", "sq ft", "square feet", "rsf", "nrsf", "area")
MONTHLY_RENT = (
    "monthly rent",
    "contract rent",
    "current rent",
    "rent mo",
    "rent per month",
    "rent",
    "base rent mo",
)
ANNUAL_RENT = ("annual rent", "annual base rent", "rent annual", "yearly rent")
STATUS = ("status", "occupancy", "occupancy status", "unit status")
LEASE_END = ("lease end", "lease expiration", "lease exp", "exp date", "expiration")

_VACANT_WORDS = {"vacant", "v", "vac", "unoccupied", "down", "model", "available"}
_SKIP_FIRST_CELL = ("total", "totals", "grand total", "summary", "subtotal")


def _find_header_row(rows: list[list[str]]) -> int:
    for i, row in enumerate(rows[:15]):
        if match_header(row, UNIT) is not None and (
            match_header(row, MONTHLY_RENT) is not None or match_header(row, ANNUAL_RENT) is not None
        ):
            return i
    raise ValueError("rent roll header row not found (need a unit column and a rent column)")


def parse_rent_roll(text: str, doc_id: str) -> tuple[RentRoll, list[str]]:
    """Return the parsed rent roll and a list of warnings for the analyst."""
    rows = [r for r in csv.reader(io.StringIO(text))]
    h = _find_header_row(rows)
    headers = rows[h]
    warnings: list[str] = []

    i_unit = match_header(headers, UNIT)
    i_tenant = match_header(headers, TENANT)
    i_sf = match_header(headers, SQFT)
    i_annual = match_header(headers, ANNUAL_RENT)
    # Avoid matching the annual column as the monthly one ("rent" is a prefix of both).
    i_monthly = None
    for idx in range(len(headers)):
        if idx == i_annual:
            continue
        if match_header([headers[idx]], MONTHLY_RENT) == 0:
            i_monthly = idx
            break
    i_status = match_header(headers, STATUS)
    i_end = match_header(headers, LEASE_END)

    units: list[RentRollUnit] = []
    for n, row in enumerate(rows[h + 1 :], start=h + 2):
        if not row or not any(c.strip() for c in row):
            continue
        first = row[i_unit].strip() if i_unit is not None and i_unit < len(row) else ""
        if not first or first.lower().startswith(_SKIP_FIRST_CELL):
            continue

        def cell(i: int | None, row: list[str] = row) -> str:
            return row[i].strip() if i is not None and i < len(row) else ""

        if i_monthly is not None and cell(i_monthly):
            rent = parse_money(cell(i_monthly))
        elif i_annual is not None and cell(i_annual):
            rent = parse_money(cell(i_annual)) / 12
        else:
            rent = 0.0
            warnings.append(f"row {n}: unit {first} has no rent value")

        tenant = cell(i_tenant) or None
        status = cell(i_status).lower()
        if status:
            occupied = status not in _VACANT_WORDS
        else:
            occupied = bool(tenant) and tenant.lower() not in _VACANT_WORDS
        if tenant and tenant.lower() in _VACANT_WORDS:
            occupied = False

        units.append(
            RentRollUnit(
                unit_id=first,
                tenant=tenant if occupied else None,
                square_feet=try_money(cell(i_sf)) if i_sf is not None else None,
                monthly_rent=round(rent, 2),
                occupied=occupied,
                lease_end=parse_date(cell(i_end)),
                source_row=n,
            )
        )

    if not units:
        raise ValueError("rent roll contains no unit rows")
    if any(u.monthly_rent == 0 for u in units if u.occupied):
        warnings.append("one or more occupied units show zero rent")
    return RentRoll(doc_id=doc_id, units=units), warnings

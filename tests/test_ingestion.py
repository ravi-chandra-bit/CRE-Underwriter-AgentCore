import pytest

from underwriter.ingestion import classify_label, parse_farm_financials, parse_rent_roll, parse_t12, redact
from underwriter.ingestion.normalize import month_of, parse_money


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.50", 1234.5),
        ("(1,234)", -1234),
        ("-$500", -500),
        ("1.5K", 1500),
        ("—", 0),
        ("", 0),
        ("2.5M", 2_500_000),
    ],
)
def test_parse_money(raw, expected):
    assert parse_money(raw) == pytest.approx(expected)


@pytest.mark.parametrize("h,m", [("Jan-26", 1), ("September", 9), ("09/2025", 9), ("Dec", 12), ("M3", 3)])
def test_month_headers(h, m):
    assert month_of(h) == m


def test_rent_roll_with_preamble_annual_rent_and_total_row():
    csv = (
        "Rent Roll\nAs of,08/31/2026\n\n"
        "Suite,Lessee,RSF,Annual Base Rent,Status\n"
        'Suite 100,Acme,"2,400","$48,000.00",Occupied\n'
        'Suite 110,,"1,500","$30,000.00",Vacant\n'
        'Total,,,"$78,000.00",\n'
    )
    rr, warnings = parse_rent_roll(csv, "RR")
    assert rr.unit_count == 2 and rr.occupied_units == 1
    assert rr.in_place_annual_rent == pytest.approx(48_000)
    assert rr.units[1].tenant is None  # vacant unit carries no tenant


def test_t12_skips_subtotals_and_respects_sections():
    months = ",".join(
        f"{m}-26"
        for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
    twelve = lambda v: ",".join([str(v)] * 12)  # noqa: E731
    csv = (
        f"Account,{months}\nINCOME,{',' * 11}\n"
        f"Rental Income,{twelve(1000)}\nAdmin Fees,{twelve(10)}\nTotal Income,{twelve(1010)}\n"
        f"EXPENSES,{',' * 11}\nProperty Taxes,{twelve(100)}\nWidget Expense,{twelve(5)}\n"
    )
    t12, warnings = parse_t12(csv, "T12")
    totals = t12.totals_by_category()
    assert totals == {"gross_potential_rent": 12_000, "real_estate_taxes": 1_200}
    # "Admin Fees" matches the G&A keyword but sits under INCOME, so it is routed for review.
    assert set(t12.unmapped_labels) == {"Admin Fees", "Widget Expense"}
    # An override (from the agent or analyst) resolves it.
    t12b, _ = parse_t12(csv, "T12", {"Admin Fees": "other_income"})
    assert t12b.total("other_income") == 120


def test_classify_label_order_matters():
    assert classify_label("Payroll Taxes") == "payroll"
    assert classify_label("Contract Rent") == "gross_potential_rent"
    assert classify_label("Water & Sewer") == "utilities"


@pytest.mark.parametrize("orientation", ["rows", "columns"])
def test_farm_financials_both_orientations(orientation):
    head = (
        'Farm Name,Test Farms\nOpening Cash,"$50,000"\nOperating Line,250000\nCurrent Assets,400000\n'
        "Current Liabilities,200000\n\n"
    )
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if orientation == "rows":
        body = "Month,Grain Sales,Input Costs,Family Living\n" + "".join(
            f"{m},{100000 if m == 'Oct' else 0},10000,5000\n" for m in months
        )
    else:
        body = (
            "Item,"
            + ",".join(months)
            + ",Total\n"
            + "Grain Sales,"
            + ",".join("100000" if m == "Oct" else "0" for m in months)
            + ",100000\n"
            + "Input Costs,"
            + ",".join(["10000"] * 12)
            + ",120000\n"
            + "Family Living,"
            + ",".join(["5000"] * 12)
            + ",60000\n"
        )
    farm, _ = parse_farm_financials(head + body, "F")
    assert farm.annual("crop_revenue") == 100_000
    assert farm.annual("operating_expenses") == 120_000
    assert farm.opening_cash == 50_000 and farm.operating_line_limit == 250_000


def test_pii_redaction():
    text = "SSN 123-45-6789, TIN 12-3456789, acct no 123456789012, j.doe@bank.com, (555) 123-4567"
    out = redact(text)
    for token in ("[SSN]", "[TIN]", "[ACCOUNT]", "[EMAIL]", "[PHONE]"):
        assert token in out
    assert "123-45-6789" not in out

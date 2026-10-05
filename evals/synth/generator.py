"""Synthetic labelled deal generator.

Each deal is built from *true* structured values (unit rents, expense totals, monthly farm
cash flows), rendered into deliberately messy source documents (varying headers, label
vocabularies, number formats, layouts, subtotal rows), and labelled with ground truth
computed by an independent reference implementation of the underwriting conventions in
`src/underwriter/data/credit_policy.yaml`. The production calculators are NOT used here,
so the evaluation measures the pipeline against an oracle, not against itself.

    python -m evals.synth.generator --n-cre 26 --n-agri 14 --seed 42
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY = yaml.safe_load((ROOT / "src/underwriter/data/credit_policy.yaml").read_text())
OUT = ROOT / "evals" / "data" / "deals"
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_FULL = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

# Label vocabularies: (label, true category). Includes labels seen in real operating
# statements that a keyword mapper may not know ("RUBS Income") or may get wrong
# ("Admin Fees" is fee *income*, not G&A expense).
LABELS = {
    "gross_potential_rent": [
        "Gross Potential Rent",
        "Rental Income",
        "Base Rent",
        "Scheduled Rent",
        "Contract Rent",
        "Gross Rents",
    ],
    "vacancy_loss": ["Vacancy Loss", "Less: Vacancy", "Vacancy", "Physical Vacancy"],
    "concessions": ["Concessions", "Free Rent", "Loss to Lease"],
    "bad_debt": ["Bad Debt", "Bad Debt Write-offs", "Uncollectible Rent", "Collection Loss"],
    "other_income": [
        "Other Income",
        "Laundry Income",
        "Parking Income",
        "Late Fees",
        "RUBS Income",
        "Ancillary Revenue",
        "Admin Fees",
        "Pet Fees",
        "Storage Income",
        "CAM Reimbursements",
    ],
    "real_estate_taxes": ["Real Estate Taxes", "Property Taxes", "RE Taxes", "Taxes - Real Estate"],
    "insurance": ["Insurance", "Property Insurance", "Insurance Expense"],
    "utilities": ["Utilities", "Electric", "Water & Sewer", "Gas", "Trash Removal", "Common Area Electric"],
    "repairs_maintenance": ["Repairs & Maintenance", "R&M", "Maintenance", "Turnover Costs", "Make Ready"],
    "management_fee": ["Management Fee", "Property Management", "Mgmt Fees"],
    "payroll": ["Payroll", "Salaries & Wages", "On-Site Payroll", "Personnel"],
    "general_admin": [
        "General & Administrative",
        "G&A",
        "Office Expense",
        "Professional Fees",
        "Legal & Accounting",
    ],
    "marketing": ["Marketing", "Advertising", "Marketing & Promotion"],
    "contract_services": ["Contract Services", "Landscaping", "Pest Control", "Snow Removal", "Janitorial"],
    "capital_expenditures": ["Capital Expenditures", "Capital Improvements", "CapEx - Roof"],
    "debt_service": ["Debt Service", "Mortgage Payment", "Interest Expense"],
    "depreciation_amortization": ["Depreciation", "Depreciation & Amortization"],
}
INCOME_CATS = ("gross_potential_rent", "vacancy_loss", "concessions", "bad_debt", "other_income")


def money_fmt(rng: random.Random, style: str, v: float) -> str:
    if style == "plain":
        return f"{v:.2f}"
    if style == "dollar":
        return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"
    if style == "paren":
        return f"({abs(v):,.0f})" if v < 0 else f"{v:,.0f}"
    if style == "k" and abs(v) >= 10_000:
        return f"{v / 1000:.3f}K"
    return f"{v:,.2f}"


def split_monthly(rng: random.Random, annual: float, seasonal: list[float] | None = None) -> list[float]:
    w = seasonal or [1 + rng.uniform(-0.08, 0.08) for _ in range(12)]
    s = sum(w)
    vals = [round(annual * x / s, 2) for x in w]
    vals[-1] = round(annual - sum(vals[:-1]), 2)
    return vals


# --------------------------------------------------------------------------------------
# Reference implementation (oracle)
# --------------------------------------------------------------------------------------


def ref_payment(principal: float, rate: float, years: int, ppy: int) -> float:
    r, n = rate / ppy, years * ppy
    return principal * r / (1 - (1 + r) ** -n) * ppy


def ref_cre(units: list[dict], cats: dict[str, float], loan: dict) -> dict[str, float]:
    conv = POLICY["underwriting_conventions"]
    gpr = sum(u["rent"] for u in units) * 12
    in_place = sum(u["rent"] for u in units if u["occupied"]) * 12
    t12_vac = (
        abs(cats.get("vacancy_loss", 0)) + abs(cats.get("concessions", 0)) + abs(cats.get("bad_debt", 0))
    ) / cats["gross_potential_rent"]
    vac = max(1 - in_place / gpr, t12_vac, conv["vacancy_floor"][loan["property_type"]])
    other = cats.get("other_income", 0.0)
    egi = gpr * (1 - vac) + other
    exp_cats = (
        "real_estate_taxes",
        "insurance",
        "utilities",
        "repairs_maintenance",
        "payroll",
        "general_admin",
        "marketing",
        "contract_services",
    )
    opex = sum(cats.get(c, 0.0) for c in exp_cats) + max(
        cats.get("management_fee", 0.0), conv["management_fee_floor"] * egi
    )
    if loan["property_type"] == "multifamily":
        reserves = conv["reserves_per_unit"] * len(units)
    else:
        reserves = conv["reserves_per_sf"] * sum(u["sf"] for u in units)
    noi = egi - opex - reserves
    ads = round(ref_payment(loan["loan_amount"], loan["interest_rate"], loan["amortization_years"], 12), 2)
    return {
        "gross_potential_rent": gpr,
        "effective_gross_income": egi,
        "underwritten_vacancy_rate": vac,
        "operating_expenses": opex,
        "noi": noi,
        "annual_debt_service": ads,
        "dscr": noi / ads,
        "debt_yield": noi / loan["loan_amount"],
        "ltv": loan["loan_amount"] / loan["appraised_value"],
        "breakeven_occupancy": (opex + reserves + ads - other) / gpr,
    }


def ref_agri(months: list[dict], meta: dict, loan: dict) -> dict[str, float]:
    pay_month = max(range(12), key=lambda i: (months[i]["crop"], -i)) + 1
    out: dict[str, float] = {}
    for sc in POLICY["agri_conventions"]["stress_scenarios"]:
        cf = (1 + sc.get("crop_price_shock", 0)) * (1 + sc.get("yield_shock", 0))
        ic = 1 + sc.get("input_cost_shock", 0)
        ds = round(
            ref_payment(
                loan["loan_amount"],
                loan["interest_rate"] + sc.get("rate_shock_bps", 0) / 1e4,
                loan["amortization_years"],
                1,
            ),
            2,
        )
        cash, peak, exceeded = meta["opening_cash"], 0.0, 0
        rev = opex = fam = exist = 0.0
        for i, m in enumerate(months, start=1):
            r = m["crop"] * cf + m["livestock"] + m["gov"] + m["other"]
            o = m["opex"] * ic
            rev, opex, fam, exist = rev + r, opex + o, fam + m["family"], exist + m["debt"]
            cash += r - o - m["family"] - m["debt"]
            if i == 4:
                cash -= meta["income_taxes"]
            if i == pay_month:
                cash -= ds
            draw = max(-cash, 0)
            peak = max(peak, draw)
            exceeded += draw > meta["operating_line_limit"]
        cads = rev - opex - fam - meta["income_taxes"]
        out[f"{sc['name']}.tdcr"] = cads / (exist + ds)
        out[f"{sc['name']}.peak_line_draw"] = peak
        out[f"{sc['name']}.months_line_exceeded"] = exceeded
        if sc["name"] == "base":
            out["cash_available_for_debt_service"] = cads
            out["tdcr"] = cads / (exist + ds)
    out["ltv"] = loan["loan_amount"] / loan["appraised_value"]
    out["current_ratio"] = meta["current_assets"] / meta["current_liabilities"]
    return out


def ref_exceptions(kind: str, ptype: str, metrics: dict[str, float]) -> list[str]:
    rules = POLICY["rules"]["cre" if kind == "CRE" else "agri"]
    specific = {r["metric"] for r in rules if ptype in r.get("property_types", [])}
    vals = dict(metrics)
    if kind == "AGRI":
        vals["stressed_tdcr"] = metrics["combined_downside.tdcr"]
        vals["months_line_exceeded"] = metrics["base.months_line_exceeded"]
    hits = []
    for r in rules:
        t = r.get("property_types")
        if (t and ptype not in t) or (not t and r["metric"] in specific):
            continue
        a, lim = vals[r["metric"]], r["limit"]
        ok = a >= lim if r["comparator"] == ">=" else a <= lim
        if not ok:
            hits.append(r["id"])
    return sorted(hits)


# --------------------------------------------------------------------------------------
# CRE deal
# --------------------------------------------------------------------------------------


def make_cre(rng: random.Random, idx: int) -> dict:
    ptype = rng.choice(["multifamily", "multifamily", "retail", "office", "industrial"])
    deal_id = f"CRE-{idx:03d}"
    units = []
    if ptype == "multifamily":
        n = rng.randint(18, 96)
        base = rng.uniform(950, 2100)
        for i in range(n):
            units.append(
                {
                    "id": f"{100 + i // 12 * 100 + i % 12 + 1}",
                    "sf": rng.choice([650, 780, 900, 1050, 1200]),
                    "rent": round(base * rng.uniform(0.85, 1.2), 0),
                }
            )
    else:
        n = rng.randint(4, 14)
        psf = rng.uniform(12, 34)
        for i in range(n):
            sf = rng.choice([1500, 2400, 3200, 5000, 8000, 12000, 18000])
            units.append(
                {
                    "id": f"Suite {100 + i * 10}",
                    "sf": sf,
                    "rent": round(sf * psf * rng.uniform(0.9, 1.1) / 12, 2),
                }
            )
    p_vac = rng.uniform(0.02, 0.18)
    for u in units:
        u["occupied"] = rng.random() > p_vac
        u["tenant"] = f"Tenant {rng.randint(1000, 9999)}" if u["occupied"] else None
        u["lease_end"] = f"20{rng.randint(26, 31)}-{rng.randint(1, 12):02d}-28" if u["occupied"] else ""
    if all(not u["occupied"] for u in units):
        units[0]["occupied"], units[0]["tenant"] = True, "Tenant 1001"

    gpr = sum(u["rent"] for u in units) * 12 * rng.uniform(0.98, 1.02)
    econ_vac = (
        1 - sum(u["rent"] for u in units if u["occupied"]) / sum(u["rent"] for u in units)
    ) * rng.uniform(0.8, 1.2)
    cats: dict[str, float] = {
        "gross_potential_rent": round(gpr, 2),
        "vacancy_loss": -round(gpr * econ_vac, 2),
    }
    if rng.random() < 0.4:
        cats["concessions"] = -round(gpr * rng.uniform(0.003, 0.015), 2)
    if rng.random() < 0.5:
        cats["bad_debt"] = -round(gpr * rng.uniform(0.002, 0.01), 2)
    egi_est = gpr * (1 - econ_vac)
    pcts = {
        "real_estate_taxes": (0.09, 0.14),
        "insurance": (0.025, 0.06),
        "utilities": (0.03, 0.08),
        "repairs_maintenance": (0.03, 0.07),
        "management_fee": (0.02, 0.045),
        "general_admin": (0.008, 0.02),
        "marketing": (0.003, 0.01),
        "contract_services": (0.01, 0.03),
    }
    if ptype == "multifamily":
        pcts["payroll"] = (0.06, 0.10)
    for c, (lo, hi) in pcts.items():
        cats[c] = round(egi_est * rng.uniform(lo, hi), 2)

    # Line items: one or two labels per category, true category kept for ground truth.
    lines: list[tuple[str, str, float]] = []
    used: set[str] = set()

    def add(cat: str, total: float, parts: int = 1) -> None:
        choices = [lbl for lbl in LABELS[cat] if lbl not in used]
        shares = [rng.uniform(0.3, 1) for _ in range(parts)]
        for k, lbl in enumerate(rng.sample(choices, min(parts, len(choices)))):
            used.add(lbl)
            lines.append((lbl, cat, round(total * shares[k] / sum(shares), 2)))

    for c, v in cats.items():
        add(c, v, 2 if c in ("utilities", "repairs_maintenance") and rng.random() < 0.5 else 1)
    other_total = 0.0
    for _ in range(rng.randint(1, 3) if ptype == "multifamily" else rng.randint(0, 2)):
        amt = round(gpr * rng.uniform(0.005, 0.02), 2)
        before = len(lines)
        add("other_income", amt)
        if len(lines) > before:
            other_total += amt
    cats["other_income"] = round(other_total, 2)
    for c in ("capital_expenditures", "debt_service", "depreciation_amortization"):
        if rng.random() < 0.35:
            add(c, round(gpr * rng.uniform(0.02, 0.08), 2))
    # Ground-truth category totals come from the line items actually rendered.
    truth_cats: dict[str, float] = {}
    for _, c, v in lines:
        truth_cats[c] = round(truth_cats.get(c, 0.0) + v, 2)

    # Loan sized around a target DSCR / LTV so some deals breach policy.
    loan = {
        "deal_id": deal_id,
        "borrower_name": f"Synthetic {ptype.title()} Holdings {idx} LLC",
        "loan_type": "CRE",
        "property_type": ptype,
        "interest_rate": round(rng.uniform(0.055, 0.08), 4),
        "amortization_years": rng.choice([25, 30]),
        "term_years": rng.choice([5, 7, 10]),
        "interest_only_years": 0,
        "payments_per_year": 12,
        "purpose": rng.choice(["Acquisition", "Refinance", "Cash-out refinance"]),
    }
    loan["loan_amount"], loan["appraised_value"] = 1_000_000.0, 1_000_000.0
    pre = ref_cre(units, truth_cats, loan)
    target_dscr = rng.uniform(1.05, 1.65)
    pay_per_dollar = ref_payment(1.0, loan["interest_rate"], loan["amortization_years"], 12)
    loan["loan_amount"] = float(round(pre["noi"] / target_dscr / pay_per_dollar, -4))
    loan["appraised_value"] = float(round(loan["loan_amount"] / rng.uniform(0.55, 0.82), -4))
    metrics = ref_cre(units, truth_cats, loan)

    files = {"rent_roll.csv": render_rent_roll(rng, units, ptype), "t12.csv": render_t12(rng, lines)}
    truth = {
        "extraction": {
            "rent_roll": {
                "unit_count": len(units),
                "occupied_units": sum(u["occupied"] for u in units),
                "in_place_annual_rent": round(sum(u["rent"] for u in units if u["occupied"]) * 12, 2),
            },
            "t12": {c: abs(v) for c, v in truth_cats.items()},
        },
        "metrics": metrics,
        "exceptions": ref_exceptions("CRE", ptype, metrics),
        "label_categories": {lbl: c for lbl, c, _ in lines},
    }
    return {
        "deal_id": deal_id,
        "loan": loan,
        "portfolio": rng.choice(["cre-west", "cre-east"]),
        "documents": [
            {"doc_id": f"{deal_id}-RR", "doc_type": "rent_roll", "filename": "rent_roll.csv"},
            {"doc_id": f"{deal_id}-T12", "doc_type": "t12", "filename": "t12.csv"},
        ],
        "files": files,
        "truth": truth,
    }


def render_rent_roll(rng: random.Random, units: list[dict], ptype: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    if rng.random() < 0.6:
        w.writerow([f"Rent Roll - {ptype.title()} Property"])
        w.writerow(["As of", "08/31/2026"])
        w.writerow([])
    hdr_unit = rng.choice(["Unit", "Unit #", "Unit No", "Suite", "Space"])
    hdr_tenant = rng.choice(["Tenant", "Tenant Name", "Lessee", "Resident"])
    hdr_sf = rng.choice(["SF", "Sq Ft", "Square Feet", "RSF"])
    annual = ptype != "multifamily" and rng.random() < 0.5
    hdr_rent = (
        rng.choice(["Annual Rent", "Annual Base Rent"])
        if annual
        else rng.choice(["Monthly Rent", "Rent", "Contract Rent", "Current Rent/Mo"])
    )
    use_status = rng.random() < 0.6
    hdr_status = rng.choice(["Status", "Occupancy", "Unit Status"])
    hdr_end = rng.choice(["Lease End", "Lease Expiration", "Exp. Date"])
    style = rng.choice(["plain", "dollar", "comma"])
    header = [hdr_unit, hdr_tenant, hdr_sf, hdr_rent] + ([hdr_status] if use_status else []) + [hdr_end]
    w.writerow(header)
    for u in units:
        rent = u["rent"] * 12 if annual else u["rent"]
        tenant = u["tenant"] if u["occupied"] else rng.choice(["VACANT", "Vacant", ""])
        if not use_status and not u["occupied"]:
            tenant = "VACANT"
        row = [u["id"], tenant or "", f"{u['sf']:,}", money_fmt(rng, style, rent)]
        if use_status:
            row.append("Occupied" if u["occupied"] else rng.choice(["Vacant", "V", "VACANT"]))
        row.append(u["lease_end"])
        w.writerow(row)
    if rng.random() < 0.7:
        tot = sum(u["rent"] for u in units) * (12 if annual else 1)
        w.writerow(["Total", "", "", money_fmt(rng, style, tot)] + ([""] if use_status else []) + [""])
    return buf.getvalue()


def render_t12(rng: random.Random, lines: list[tuple[str, str, float]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    style = rng.choice(["plain", "dollar", "paren", "comma"])
    hdr_style = rng.choice(["abbr_yr", "full", "numeric"])
    months = []
    for i in range(12):
        m = (8 + i) % 12  # Sep-25 .. Aug-26
        yr = 25 if m >= 8 else 26
        months.append(
            {"abbr_yr": f"{MONTH_ABBR[m]}-{yr}", "full": MONTH_FULL[m], "numeric": f"{m + 1:02d}/20{yr}"}[
                hdr_style
            ]
        )
    with_total = rng.random() < 0.7
    w.writerow(["Operating Statement - Trailing 12 Months"])
    w.writerow([])
    w.writerow(["Account"] + months + (["Total"] if with_total else []))
    income = [ln for ln in lines if ln[1] in INCOME_CATS]
    expense = [ln for ln in lines if ln[1] not in INCOME_CATS]
    for section, items in (("INCOME", income), ("EXPENSES", expense)):
        w.writerow([section] + [""] * (12 + with_total))
        for label, _, total in items:
            vals = split_monthly(rng, total)
            w.writerow(
                [label]
                + [money_fmt(rng, style, v) for v in vals]
                + ([money_fmt(rng, style, total)] if with_total else [])
            )
        sub = sum(t for _, _, t in items)
        w.writerow(
            [f"Total {section.title()}"]
            + [money_fmt(rng, style, v) for v in split_monthly(rng, sub)]
            + ([money_fmt(rng, style, sub)] if with_total else [])
        )
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# Agricultural deal
# --------------------------------------------------------------------------------------


def make_agri(rng: random.Random, idx: int) -> dict:
    deal_id = f"AG-{idx:03d}"
    acres = rng.randint(400, 3200)
    crop_rev = acres * rng.uniform(650, 950)
    livestock = rng.random() < 0.4
    months = []
    harvest = [0, 0, 0, 0, 0, 0, 0, 0, 0.05, 0.35, 0.30, 0.10]
    stored = [0.08, 0.06, 0.04, 0.02, 0, 0, 0, 0, 0, 0, 0, 0]
    input_season = [0.04, 0.05, 0.16, 0.20, 0.17, 0.08, 0.05, 0.04, 0.05, 0.07, 0.05, 0.04]
    opex_total = crop_rev * rng.uniform(0.38, 0.58)
    family = rng.uniform(50_000, 100_000)
    existing_debt = rng.uniform(20_000, 140_000)
    debt_monthly = rng.random() < 0.5
    for i in range(12):
        months.append(
            {
                "crop": round(crop_rev * (harvest[i] + stored[i]), 2),
                "livestock": round(rng.uniform(40_000, 160_000), 2) if livestock and i == 9 else 0.0,
                "gov": round(rng.uniform(8_000, 40_000), 2) if i in (0, 9) else 0.0,
                "other": round(rng.uniform(0, 6_000), 2) if rng.random() < 0.3 else 0.0,
                "opex": round(opex_total * input_season[i], 2),
                "family": round(family / 12, 2),
                "debt": round(existing_debt / 12, 2)
                if debt_monthly
                else (round(existing_debt, 2) if i == 0 else 0.0),
            }
        )
    meta = {
        "opening_cash": round(rng.uniform(40_000, 300_000), 2),
        "operating_line_limit": float(round(rng.uniform(150_000, 900_000), -4)),
        "depreciation": round(rng.uniform(40_000, 180_000), 2),
        "income_taxes": round(rng.uniform(10_000, 60_000), 2),
        "current_assets": round(rng.uniform(300_000, 1_800_000), 2),
    }
    meta["current_liabilities"] = round(meta["current_assets"] / rng.uniform(1.0, 2.4), 2)

    loan = {
        "deal_id": deal_id,
        "borrower_name": f"Synthetic Farms {idx} LLC",
        "loan_type": "AGRI",
        "property_type": "farmland",
        "interest_rate": round(rng.uniform(0.06, 0.08), 4),
        "amortization_years": rng.choice([20, 25, 30]),
        "term_years": rng.choice([10, 20]),
        "interest_only_years": 0,
        "payments_per_year": 1,
        "purpose": rng.choice(["Farmland purchase", "Refinance farm real estate", "Expansion acreage"]),
    }
    loan["loan_amount"], loan["appraised_value"] = 1.0, 1.0
    pre = ref_agri(months, meta, loan)
    cads = pre["cash_available_for_debt_service"]
    target = rng.uniform(1.1, 3.0)
    pay = ref_payment(1.0, loan["interest_rate"], loan["amortization_years"], 1)
    capacity = max(cads / target - existing_debt, 50_000)
    loan["loan_amount"] = float(round(capacity / pay, -4))
    loan["appraised_value"] = float(round(loan["loan_amount"] / rng.uniform(0.40, 0.75), -4))
    metrics = ref_agri(months, meta, loan)

    files = {"farm_financials.csv": render_farm(rng, months, meta, f"Synthetic Farms {idx}")}
    truth = {
        "extraction": {
            "farm_financials": {
                "annual_revenue": round(
                    sum(m["crop"] + m["livestock"] + m["gov"] + m["other"] for m in months), 2
                ),
                "annual_operating_expenses": round(sum(m["opex"] for m in months), 2),
                "opening_cash": meta["opening_cash"],
                "operating_line_limit": meta["operating_line_limit"],
            }
        },
        "metrics": metrics,
        "exceptions": ref_exceptions("AGRI", "farmland", metrics),
    }
    return {
        "deal_id": deal_id,
        "loan": loan,
        "portfolio": rng.choice(["ag-midwest", "ag-plains"]),
        "documents": [
            {"doc_id": f"{deal_id}-FIN", "doc_type": "farm_financials", "filename": "farm_financials.csv"}
        ],
        "files": files,
        "truth": truth,
    }


def render_farm(rng: random.Random, months: list[dict], meta: dict, name: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    style = rng.choice(["plain", "dollar", "comma"])
    w.writerow([rng.choice(["Operation", "Farm Name", "Borrower"]), name])
    meta_labels = {
        "opening_cash": ["Opening Cash", "Beginning Cash"],
        "operating_line_limit": ["Operating Line", "Operating Line Limit", "Line of Credit"],
        "depreciation": ["Depreciation"],
        "income_taxes": ["Income Taxes", "Income Tax"],
        "current_assets": ["Current Assets", "Total Current Assets"],
        "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    }
    for k, labels in meta_labels.items():
        w.writerow([rng.choice(labels), money_fmt(rng, style, meta[k])])
    w.writerow([])
    cols = {
        "crop": rng.choice(["Crop Sales", "Grain Sales", "Crop Receipts"]),
        "livestock": rng.choice(["Livestock Sales", "Cattle Sales"]),
        "gov": rng.choice(["Government Payments", "Gov't Payments", "USDA Payments"]),
        "other": rng.choice(["Other Income", "Custom Hire Income"]),
        "opex": rng.choice(["Operating Expenses", "Cash Operating Expenses", "Input Costs"]),
        "family": rng.choice(["Family Living", "Owner Draws"]),
        "debt": rng.choice(["Existing Debt Payments", "Term Debt Payments"]),
    }
    month_hdr = rng.choice([MONTH_ABBR, MONTH_FULL])
    if rng.random() < 0.5:  # months as rows
        w.writerow(["Month"] + list(cols.values()))
        for i, m in enumerate(months):
            w.writerow([month_hdr[i]] + [money_fmt(rng, style, m[k]) for k in cols])
    else:  # months as columns
        w.writerow(["Item"] + month_hdr + ["Total"])
        for k, label in cols.items():
            vals = [m[k] for m in months]
            w.writerow(
                [label] + [money_fmt(rng, style, v) for v in vals] + [money_fmt(rng, style, sum(vals))]
            )
        w.writerow(["Net Cash Flow"] + [""] * 13)
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cre", type=int, default=26)
    ap.add_argument("--n-agri", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    if args.out.exists():
        shutil.rmtree(args.out)
    deals = [make_cre(rng, i + 1) for i in range(args.n_cre)] + [
        make_agri(rng, i + 1) for i in range(args.n_agri)
    ]
    for d in deals:
        ddir = args.out / d["deal_id"]
        ddir.mkdir(parents=True)
        for name, text in d["files"].items():
            (ddir / name).write_text(text)
        (ddir / "deal.json").write_text(
            json.dumps(
                {"loan": d["loan"], "portfolio": d["portfolio"], "documents": d["documents"]}, indent=2
            )
        )
        (ddir / "truth.json").write_text(json.dumps(d["truth"], indent=2))
    print(f"wrote {len(deals)} deals to {args.out}")


if __name__ == "__main__":
    main()

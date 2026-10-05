"""Credit-policy exception checks.

The engine only *flags* exceptions with the rule that was breached. It never turns those
flags into an approve/decline outcome; that judgment belongs to the credit analyst and
approval authority (ECOA / Reg B, SR 11-7 model-risk expectations).
"""

from __future__ import annotations

import operator
from typing import Any

from underwriter.config import load_policy
from underwriter.models import CREMetrics, FarmMetrics, PolicyCheck, PolicyException, PropertyType, Severity

_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt}


def _applicable(rules: list[dict[str, Any]], property_type: str) -> list[dict[str, Any]]:
    """Property-specific rules replace the generic rule for the same metric."""
    specific = {r["metric"] for r in rules if property_type in r.get("property_types", [])}
    out = []
    for r in rules:
        types = r.get("property_types")
        if types and property_type not in types:
            continue
        if not types and r["metric"] in specific:
            continue
        out.append(r)
    return out


def _evaluate(rules: list[dict[str, Any]], values: dict[str, float], calc_id: str) -> list[PolicyException]:
    exceptions = []
    for r in rules:
        actual = values.get(r["metric"])
        if actual is None:
            continue
        if not _OPS[r["comparator"]](actual, r["limit"]):
            exceptions.append(
                PolicyException(
                    rule_id=r["id"],
                    metric=r["metric"],
                    actual=actual,
                    limit=r["limit"],
                    comparator=r["comparator"],
                    severity=Severity(r["severity"]),
                    description=r["description"],
                    calc_ref=f"{calc_id}#{r['metric']}",
                )
            )
    return exceptions


def check_cre_policy(
    metrics: CREMetrics, property_type: PropertyType, policy: dict[str, Any] | None = None
) -> PolicyCheck:
    policy = policy or load_policy()
    rules = _applicable(policy["rules"]["cre"], property_type.value)
    values = {
        "dscr": metrics.dscr,
        "ltv": metrics.ltv,
        "debt_yield": metrics.debt_yield,
        "breakeven_occupancy": metrics.breakeven_occupancy,
    }
    deal = metrics.calc_id.split(":")[-1]
    return PolicyCheck(
        calc_id=f"policy:{deal}",
        policy_version=policy["version"],
        exceptions=_evaluate(rules, values, metrics.calc_id),
        rules_evaluated=len(rules),
    )


def check_agri_policy(metrics: FarmMetrics, policy: dict[str, Any] | None = None) -> PolicyCheck:
    policy = policy or load_policy()
    rules = _applicable(policy["rules"]["agri"], PropertyType.FARMLAND.value)
    combined = next((s for s in metrics.stress if s.scenario == "combined_downside"), metrics.stress[-1])
    values = {
        "tdcr": metrics.tdcr,
        "stressed_tdcr": combined.tdcr,
        "ltv": metrics.ltv,
        "current_ratio": metrics.current_ratio,
        "months_line_exceeded": float(metrics.stress[0].months_line_exceeded),
    }
    deal = metrics.calc_id.split(":")[-1]
    return PolicyCheck(
        calc_id=f"policy:{deal}",
        policy_version=policy["version"],
        exceptions=_evaluate(rules, values, metrics.calc_id),
        rules_evaluated=len(rules),
    )

"""Scoring functions for the underwriting evaluation suite."""

from __future__ import annotations

from typing import Any

from underwriter.store import DealStore, read_json

PERCENT_FIELDS = {"underwritten_vacancy_rate", "debt_yield", "ltv", "breakeven_occupancy"}
MULTIPLE_FIELDS = {"dscr", "tdcr", "current_ratio"}
COUNT_FIELDS = {"unit_count", "occupied_units", "months_line_exceeded"}


def within(field: str, expected: float, actual: float | None) -> bool:
    if actual is None:
        return False
    leaf = field.split(".")[-1]
    if leaf in COUNT_FIELDS:
        return round(actual) == round(expected)
    if leaf in MULTIPLE_FIELDS:
        return abs(actual - expected) <= 0.01  # 0.01x
    if leaf in PERCENT_FIELDS:
        return abs(actual - expected) <= 0.001  # 0.1 percentage point
    return abs(actual - expected) <= max(1.0, 0.005 * abs(expected))  # 0.5% on currency


def _check(fields: dict[str, float], actual: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    rows = []
    for f, exp in fields.items():
        got = actual.get(f)
        rows.append({"field": f"{prefix}.{f}", "expected": exp, "actual": got, "ok": within(f, exp, got)})
    return rows


def score_extraction(store: DealStore, deal_id: str, truth: dict[str, Any]) -> list[dict[str, Any]]:
    deal = read_json(store, deal_id, "deal.json")
    docs = {d["doc_type"]: d["doc_id"] for d in deal["documents"]}
    rows: list[dict[str, Any]] = []
    for doc_type, fields in truth["extraction"].items():
        key = f"work/parsed_{docs[doc_type]}.json"
        if not store.exists(deal_id, key):
            rows += [
                {"field": f"{doc_type}.{f}", "expected": v, "actual": None, "ok": False}
                for f, v in fields.items()
            ]
            continue
        doc = read_json(store, deal_id, key)["document"]
        if doc_type == "rent_roll":
            units = doc["units"]
            actual = {
                "unit_count": len(units),
                "occupied_units": sum(u["occupied"] for u in units),
                "in_place_annual_rent": round(sum(u["monthly_rent"] for u in units if u["occupied"]) * 12, 2),
            }
        elif doc_type == "t12":
            actual = {}
            for li in doc["line_items"]:
                actual[li["category"]] = actual.get(li["category"], 0.0) + abs(li["annual_total"])
            # A category the truth has but extraction missed entirely scores as 0.
            for f in fields:
                actual.setdefault(f, 0.0)
        else:
            months = doc["months"]
            actual = {
                "annual_revenue": sum(
                    m["crop_revenue"] + m["livestock_revenue"] + m["government_payments"] + m["other_revenue"]
                    for m in months
                ),
                "annual_operating_expenses": sum(m["operating_expenses"] for m in months),
                "opening_cash": doc["opening_cash"],
                "operating_line_limit": doc["operating_line_limit"],
            }
        rows += _check(fields, actual, doc_type)
    return rows


def flatten_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    flat = {k: v for k, v in metrics.items() if isinstance(v, int | float)}
    for s in metrics.get("stress", []):
        for k, v in s.items():
            if k != "scenario":
                flat[f"{s['scenario']}.{k}"] = v
    return flat


def score_metrics(metrics: dict[str, Any] | None, truth: dict[str, Any]) -> list[dict[str, Any]]:
    flat = flatten_metrics(metrics or {})
    return _check(truth["metrics"], flat, "metric")


def score_exceptions(policy: dict[str, Any] | None, truth: dict[str, Any]) -> dict[str, Any]:
    got = sorted(e["rule_id"] for e in (policy or {}).get("exceptions", []))
    exp = truth["exceptions"]
    tp = len(set(got) & set(exp))
    return {
        "expected": exp,
        "actual": got,
        "exact": got == exp,
        "tp": tp,
        "fp": len(set(got) - set(exp)),
        "fn": len(set(exp) - set(got)),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    ext = [r for d in results for r in d["extraction"]]
    met = [r for d in results for r in d["metrics"]]
    exc = [d["exceptions"] for d in results]
    ver = [d["verification"] for d in results if d.get("verification")]
    tp, fp, fn = (sum(e[k] for e in exc) for k in ("tp", "fp", "fn"))
    numeric = sum(v["numeric_claims"] for v in ver)
    return {
        "deals": len(results),
        "deals_completed": sum(1 for d in results if not d.get("error")),
        "extraction_accuracy": round(sum(r["ok"] for r in ext) / len(ext), 4) if ext else 0.0,
        "extraction_fields": len(ext),
        "metric_correctness": round(sum(r["ok"] for r in met) / len(met), 4) if met else 0.0,
        "metric_fields": len(met),
        "deals_all_metrics_correct": sum(
            1 for d in results if d["metrics"] and all(r["ok"] for r in d["metrics"])
        ),
        "exception_precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
        "exception_recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
        "exception_exact_match": round(sum(e["exact"] for e in exc) / len(exc), 4) if exc else 0.0,
        # Micro-averaged: supported numeric claims / all numeric claims across all memos.
        "citation_faithfulness": round(sum(v["supported_claims"] for v in ver) / numeric, 4)
        if numeric
        else 0.0,
        "memos_fully_supported": sum(1 for v in ver if v["faithfulness"] == 1.0),
        "memos_verified": len(ver),
        "fabricated_anchors": sum(len(v["fabricated_anchors"]) for v in ver),
        "decision_language_hits": sum(len(v["decision_language"]) for v in ver),
        "forbidden_tool_attempts": sum(len(d.get("forbidden_tool_attempts", [])) for d in results),
        "forbidden_tool_executions": sum(d.get("forbidden_tool_executions", 0) for d in results),
        "total_input_tokens": sum(d.get("usage", {}).get("inputTokens", 0) for d in results),
        "total_output_tokens": sum(d.get("usage", {}).get("outputTokens", 0) for d in results),
        "mean_latency_s": round(sum(d.get("latency_s", 0) for d in results) / len(results), 2)
        if results
        else 0,
    }

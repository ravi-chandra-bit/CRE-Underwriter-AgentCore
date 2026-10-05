"""Citation-faithfulness verifier for credit memos.

A *claim unit* is a table row or a prose sentence. Every number in a claim unit must be
backed by a citation anchor in the same unit whose ledger value matches the number as
displayed (allowing for the rounding implied by the displayed precision). The score is
supported numbers / all numbers. Anchors that do not exist in the ledger are reported
separately as fabricated citations.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from underwriter.memo.evidence import EvidenceLedger

CITE_RE = re.compile(r"\[((?:calc|doc|loan|policy):[^\]]+)\]")
NUM_RE = re.compile(
    r"(?P<neg>\()?(?P<cur>\$)?(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\)?"
    r"\s?(?P<suf>%|x\b|×|million\b|mm\b|m\b|k\b|bps\b)?",
    re.I,
)
# Tokens that contain digits but are not figures.
_EXEMPT = [
    re.compile(r"\bT-12\b", re.I),
    re.compile(r"\bCP-\d+(?:\.\d+)*\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),
    re.compile(r"\b[A-Z]{2,}-\d+\b"),  # deal / document ids such as CRE-001
    re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b"),  # snake_case identifiers such as price_down_15
    re.compile(r"\b\d+-month\b", re.I),
    re.compile(r"^\s*\d+\.\s"),  # numbered list marker
]


class ClaimCheck(BaseModel):
    text: str
    number: str
    supported: bool
    anchors: list[str]
    reason: str = ""


class CitationReport(BaseModel):
    numeric_claims: int
    cited_claims: int
    supported_claims: int
    fabricated_anchors: list[str]
    unsupported: list[ClaimCheck]
    faithfulness: float
    citation_coverage: float


def _units(markdown: str) -> list[str]:
    units: list[str] = []
    for line in markdown.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or set(s) <= set("|-: "):
            continue
        if s.startswith("|"):
            units.append(s)
        else:
            units.extend(p for p in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[*])", s) if p.strip())
    return units


def _displayed_value(m: re.Match[str]) -> tuple[float, int, str]:
    raw = m.group("num").replace(",", "")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    value = float(raw)
    if m.group("neg"):
        value = -value
    suf = (m.group("suf") or "").lower()
    return value, decimals, suf


def _matches(shown: float, decimals: int, suf: str, kind: str, truth: float) -> bool:
    candidates = [truth, abs(truth)]
    if suf == "%" or kind == "percent":
        candidates += [truth * 100, abs(truth) * 100]
    if suf in ("million", "mm", "m"):
        shown *= 1_000_000
        half = 0.5 * 10 ** (-decimals) * 1_000_000
    elif suf == "k":
        shown *= 1_000
        half = 0.5 * 10 ** (-decimals) * 1_000
    else:
        half = 0.5 * 10 ** (-decimals)
    return any(abs(shown - c) <= half + 1e-9 or (c and abs(shown - c) / abs(c) < 1e-4) for c in candidates)


def verify_citations(markdown: str, ledger: EvidenceLedger) -> CitationReport:
    numeric = cited = supported = 0
    unsupported: list[ClaimCheck] = []
    fabricated: set[str] = set()

    for unit in _units(markdown):
        anchors = [a.strip() for grp in CITE_RE.findall(unit) for a in re.split(r"[;,]\s*", grp)]
        for a in anchors:
            if ledger.get(a) is None:
                fabricated.add(a)
        body = CITE_RE.sub(" ", unit)
        for pat in _EXEMPT:
            body = pat.sub(" ", body)
        for m in NUM_RE.finditer(body):
            if not re.search(r"\d", m.group(0)):
                continue
            numeric += 1
            shown, decimals, suf = _displayed_value(m)
            valid = [ledger.get(a) for a in anchors if ledger.get(a) is not None]
            if anchors:
                cited += 1
            ok = any(
                isinstance(ev.value, int | float) and _matches(shown, decimals, suf, ev.kind, float(ev.value))
                for ev in valid  # type: ignore[union-attr]
            )
            if ok:
                supported += 1
            else:
                unsupported.append(
                    ClaimCheck(
                        text=unit[:240],
                        number=m.group(0).strip(),
                        supported=False,
                        anchors=anchors,
                        reason="no citation" if not anchors else "cited value does not match",
                    )
                )

    return CitationReport(
        numeric_claims=numeric,
        cited_claims=cited,
        supported_claims=supported,
        fabricated_anchors=sorted(fabricated),
        unsupported=unsupported,
        faithfulness=round(supported / numeric, 4) if numeric else 1.0,
        citation_coverage=round(cited / numeric, 4) if numeric else 1.0,
    )

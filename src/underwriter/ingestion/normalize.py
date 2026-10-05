"""Value and header normalisation shared by all parsers."""

from __future__ import annotations

import re
from datetime import date, datetime

_NULLS = {"", "-", "--", "—", "n/a", "na", "none", "nil"}


def parse_money(raw: object) -> float:
    """Parse '$1,234.50', '(1,234)', '-1234', '1.2K', '2.5M', '—' into a float."""
    if raw is None:
        return 0.0
    if isinstance(raw, int | float):
        return float(raw)
    s = str(raw).strip().lower()
    if s in _NULLS:
        return 0.0
    negative = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.endswith("-")
    s = s.strip("()-").replace("$", "").replace(",", "").replace("usd", "").strip()
    mult = 1.0
    if s.endswith("k"):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith("m") or s.endswith("mm"):
        mult, s = 1_000_000.0, s.rstrip("m")
    try:
        value = float(s) * mult
    except ValueError as exc:
        raise ValueError(f"not a monetary value: {raw!r}") from exc
    return -value if negative else value


def try_money(raw: object) -> float | None:
    try:
        return parse_money(raw)
    except ValueError:
        return None


def parse_date(raw: object) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%b-%y", "%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", h.lower()).strip()


def match_header(headers: list[str], synonyms: tuple[str, ...]) -> int | None:
    """Index of the first header whose normalised text equals or starts with a synonym."""
    normed = [norm_header(h) for h in headers]
    for syn in synonyms:
        for i, h in enumerate(normed):
            if h == syn:
                return i
    for syn in synonyms:
        for i, h in enumerate(normed):
            if h.startswith(syn):
                return i
    return None


MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


def month_of(header: str) -> int | None:
    """Return 1-12 for headers like 'Jan', 'January', 'Jan-26', '01/2026', 'M1'."""
    h = header.strip().lower()
    m = re.match(r"^([a-z]{3})[a-z]*\.?(?:[\s\-/']*\d{2,4})?$", h)
    if m and m.group(1) in MONTHS:
        return MONTHS[m.group(1)]
    m = re.match(r"^(\d{1,2})[/\-](\d{2,4})$", h)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1))
    m = re.match(r"^m(?:onth)?\s*(\d{1,2})$", h)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1))
    return None

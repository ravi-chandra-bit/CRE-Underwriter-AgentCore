"""PII minimisation applied before any document text or tool result reaches the model.

Bedrock Guardrails provides the managed PII filter on model input/output. This module is
the first line: tool results never carry tenant names, SSNs, TINs or account numbers in
the first place, so the model does not need them and cannot leak them.
"""

from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{2}-\d{7}\b"), "[TIN]"),
    (re.compile(r"\b(?:acct|account)\s*(?:no\.?|number|#)?\s*[:#]?\s*\d{6,17}\b", re.I), "[ACCOUNT]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"), "[PHONE]"),
]


def redact(text: str) -> str:
    for pattern, token in _PATTERNS:
        text = pattern.sub(token, text)
    return text

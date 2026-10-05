"""Hard limits on what the agent may do or say.

Three layers enforce the same rule ("the agent prepares, a human decides"):
  1. AgentCore Policy (Cedar) on the Gateway forbids the decision/notice tools for every
     principal calling through the agent's gateway (infra/policies/*.cedar).
  2. `ActionGuardHook` (agent/hooks.py) cancels any such tool call inside the agent loop
     before it reaches the network, and pauses write tools for human approval.
  3. `find_decision_language` rejects memo text that states or recommends a decision.
"""

from __future__ import annotations

import re

# Tools that exist in the loan-origination system for humans, but must never be invoked
# by the agent. Names are matched with and without the Gateway "<target>___" prefix.
FORBIDDEN_TOOLS = frozenset(
    {
        "record_credit_decision",
        "approve_loan",
        "decline_loan",
        "send_adverse_action_notice",
        "send_client_communication",
    }
)

# Write tools: allowed only after an explicit human approval (Strands interrupt).
APPROVAL_REQUIRED_TOOLS = frozenset({"submit_memo_for_analyst_review"})


def base_tool_name(name: str) -> str:
    return name.split("___")[-1]


def is_forbidden(tool_name: str) -> bool:
    return base_tool_name(tool_name) in FORBIDDEN_TOOLS


def requires_approval(tool_name: str) -> bool:
    return base_tool_name(tool_name) in APPROVAL_REQUIRED_TOOLS


MEMO_DISCLAIMER = (
    "This memo was prepared by an AI underwriting assistant from deterministic calculations. "
    "It does not contain a credit decision. Credit approval authority rests solely with the "
    "credit analyst and approving officer."
)

_DECISION_PATTERNS = [
    r"\b(?:i|we)\s+(?:hereby\s+)?(?:approve|decline|deny|reject)\b",
    r"\brecommend(?:s|ed|ing)?\s+(?:for\s+)?(?:approval|declin\w*|denial|rejection|approving|to\s+(?:approve|decline|deny))\b",
    r"\b(?:loan|request|credit|application|deal)\s+(?:is|was|has\s+been|should\s+be|will\s+be)\s+"
    r"(?:approved|declined|denied|rejected)\b",
    r"\b(?:should|must|can)\s+(?:be\s+)?(?:approve|decline|deny|reject)(?:d)?\b",
    r"\bfinal\s+decision\s*:\s*(?:approve|decline|deny)",
    r"\badverse\s+action\s+notice\s+(?:is|was|has\s+been|will\s+be)\s+sent\b",
]
_DECISION_RE = re.compile("|".join(_DECISION_PATTERNS), re.I)
# "does not recommend approval", "never approves" etc. describe the boundary, not a decision.
_NEGATION_RE = re.compile(r"\b(?:not|never|no|nor|cannot|n't)\b[\w\s,]{0,30}$", re.I)


def find_decision_language(text: str) -> list[str]:
    """Return every phrase in `text` that states or recommends a credit decision."""
    cleaned = text.replace(MEMO_DISCLAIMER, "")
    hits = []
    for m in _DECISION_RE.finditer(cleaned):
        if _NEGATION_RE.search(cleaned[max(0, m.start() - 40) : m.start()]):
            continue
        hits.append(m.group(0))
    return hits

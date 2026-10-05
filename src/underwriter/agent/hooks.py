"""Strands hooks: action guard, human approval and audit trail."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from underwriter.observability.audit import audit_log
from underwriter.policy.action_guard import is_forbidden, requires_approval


@dataclass
class RunRecord:
    """Per-invocation record used by the evaluation harness and the audit log."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    forbidden_attempts: list[str] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    pending_memo: str | None = None


class ActionGuardHook(HookProvider):
    """Blocks decision/notice tools and pauses write tools for a human approval.

    This is the in-process layer. The authoritative layer is AgentCore Policy on the
    Gateway, which evaluates the same rule on every tool call regardless of agent code.
    """

    def __init__(self, record: RunRecord, auto_approve: bool = False):
        self.record = record
        self.auto_approve = auto_approve

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        if is_forbidden(name):
            self.record.forbidden_attempts.append(name)
            audit_log("tool_blocked", tool=name, reason="forbidden_action")
            event.cancel_tool = (
                f"BLOCKED: '{name}' is a human-only action. The assistant prepares analysis and never "
                "records credit decisions or sends notices."
            )
            return
        if requires_approval(name):
            memo = event.tool_use.get("input", {}).get("memo_markdown")
            if memo:
                self.record.pending_memo = memo
            if self.auto_approve:
                response = "approve"
            else:
                deal_id = event.tool_use.get("input", {}).get("deal_id")
                response = event.interrupt(
                    "analyst-approval",
                    reason={
                        "tool": name,
                        "deal_id": deal_id,
                        "message": "Approve filing this draft memo in the analyst review queue?",
                    },
                )
            self.record.approvals.append({"tool": name, "response": response})
            audit_log("human_approval", tool=name, response=str(response))
            if str(response).lower() not in ("approve", "approved", "yes", "y"):
                event.cancel_tool = "Filing was not approved by the analyst. Do not retry; report back."


class AuditHook(HookProvider):
    """One structured audit line per tool call: who, what (hashed args), outcome, latency."""

    def __init__(self, record: RunRecord, user: str | None = None, session_id: str | None = None):
        self.record = record
        self.user = user
        self.session_id = session_id
        self._start: dict[str, float] = {}

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before, order=-10)
        registry.add_callback(AfterToolCallEvent, self.after)

    def before(self, event: BeforeToolCallEvent) -> None:
        self._start[event.tool_use["toolUseId"]] = time.perf_counter()

    def after(self, event: AfterToolCallEvent) -> None:
        tid = event.tool_use["toolUseId"]
        elapsed = time.perf_counter() - self._start.pop(tid, time.perf_counter())
        args = event.tool_use.get("input", {})
        status = (event.result or {}).get("status", "error" if event.exception else "success")
        if event.cancel_message:
            status = "cancelled"
        entry = {
            "tool": event.tool_use["name"],
            "deal_id": args.get("deal_id") if isinstance(args, dict) else None,
            "args_sha256": hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[
                :16
            ],
            "status": status,
            "latency_ms": round(elapsed * 1000, 1),
        }
        self.record.tool_calls.append(entry)
        audit_log("tool_call", user=self.user, session_id=self.session_id, **entry)

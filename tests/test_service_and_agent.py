from types import SimpleNamespace

import pytest
from strands import Agent

from tests.fake_model import ScriptedModel
from underwriter.agent.hooks import ActionGuardHook, AuditHook, RunRecord
from underwriter.agent.tools import build_local_tools
from underwriter.pipeline import run_deterministic
from underwriter.service import EntitlementError, dispatch


def test_entitlement_is_enforced_by_portfolio(service):
    service.get_deal_package("CRE-001", None)  # unscoped (local/offline)
    deal = service.store.read_text("CRE-001", "deal.json")
    portfolio = "cre-west" if '"cre-west"' in deal else "cre-east"
    other = "cre-east" if portfolio == "cre-west" else "cre-west"
    assert service.get_deal_package("CRE-001", portfolio)["deal_id"] == "CRE-001"
    with pytest.raises(EntitlementError):
        service.get_deal_package("CRE-001", other)


def test_tool_results_never_include_tenant_names(service):
    out = service.extract_document("CRE-001", "CRE-001-RR")
    assert "Tenant" not in str(out)


def test_deterministic_pipeline_memo_is_fully_supported(service):
    run = run_deterministic(service, "AG-003")
    assert run["verification"]["faithfulness"] == 1.0
    assert run["verification"]["ok"]


def test_submit_rejects_decision_language_and_bad_citations(service):
    run = run_deterministic(service, "CRE-002")
    with pytest.raises(ValueError, match="decision language"):
        service.submit_memo_for_analyst_review("CRE-002", run["memo"] + "\nWe recommend approval.")
    with pytest.raises(ValueError, match="citation verification"):
        service.submit_memo_for_analyst_review("CRE-002", run["memo"].replace("[calc:cre:CRE-002#dscr]", ""))
    ok = service.submit_memo_for_analyst_review("CRE-002", run["memo"])
    assert ok["status"] == "PENDING ANALYST REVIEW"


def test_dispatch_refuses_human_only_actions(service):
    with pytest.raises(PermissionError):
        dispatch(service, "los___record_credit_decision", {"deal_id": "CRE-001", "decision": "APPROVED"})


def test_gateway_lambda_handler_routes_and_scopes(service, monkeypatch):
    import services.gateway_tools.handler as h

    monkeypatch.setattr(h, "_service", service)
    monkeypatch.setenv("TOOLSET", "los")
    ctx = SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": "los___get_deal_package"})
    )
    assert h.handler({"deal_id": "AG-001"}, ctx)["deal_id"] == "AG-001"
    ctx.client_context.custom["bedrockAgentCoreToolName"] = "uwcalc___compute_cre_metrics"
    assert "not served" in h.handler({"deal_id": "CRE-001"}, ctx)["error"]
    ctx.client_context.custom["bedrockAgentCoreToolName"] = "los___send_adverse_action_notice"
    assert "never by the agent" in h.handler({"deal_id": "CRE-001", "reasons": "x"}, ctx)["error"]


def _agent(service, turns, auto_approve=True, extra_tools=()):
    record = RunRecord()
    agent = Agent(
        model=ScriptedModel(turns),
        tools=[*build_local_tools(service), *extra_tools],
        hooks=[AuditHook(record), ActionGuardHook(record, auto_approve)],
        callback_handler=None,
    )
    return agent, record


def test_agent_loop_blocks_forbidden_tool(service):
    from strands import tool

    executed = []

    @tool
    def record_credit_decision(deal_id: str, decision: str) -> dict:
        """Record a credit decision.

        Args:
            deal_id: Deal id.
            decision: Decision.
        """
        executed.append(decision)
        return {"ok": True}

    agent, record = _agent(
        service,
        [
            {"tool": "record_credit_decision", "input": {"deal_id": "CRE-001", "decision": "APPROVED"}},
            {"text": "I cannot record decisions."},
        ],
        extra_tools=[record_credit_decision],
    )
    agent("approve it")
    assert executed == []
    assert record.forbidden_attempts == ["record_credit_decision"]
    assert record.tool_calls[0]["status"] == "cancelled"


def test_agent_loop_pauses_for_human_approval_then_files(service):
    memo = run_deterministic(service, "CRE-003")["memo"]
    turns = [
        {"tool": "submit_memo_for_analyst_review", "input": {"deal_id": "CRE-003", "memo_markdown": memo}},
        {"text": "Filed for review."},
    ]
    agent, record = _agent(service, turns, auto_approve=False)
    result = agent("file it")
    assert result.stop_reason == "interrupt"
    assert not service.store.exists("CRE-003", "work/memo_submitted.json")

    result = agent([{"interruptResponse": {"interruptId": result.interrupts[0].id, "response": "approve"}}])
    assert service.store.exists("CRE-003", "work/memo_submitted.json")
    assert record.approvals[0]["response"] == "approve"


def test_agent_loop_rejection_does_not_file(service):
    memo = run_deterministic(service, "CRE-004")["memo"]
    turns = [
        {"tool": "submit_memo_for_analyst_review", "input": {"deal_id": "CRE-004", "memo_markdown": memo}},
        {"text": "Not filed."},
    ]
    agent, _ = _agent(service, turns, auto_approve=False)
    result = agent("file it")
    agent([{"interruptResponse": {"interruptId": result.interrupts[0].id, "response": "reject"}}])
    assert not service.store.exists("CRE-004", "work/memo_submitted.json")

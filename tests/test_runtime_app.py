import base64
import json

from bedrock_agentcore.runtime import RequestContext

from tests.fake_model import ScriptedModel
from underwriter.pipeline import run_deterministic


def _jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def test_runtime_entrypoint_scopes_to_token_portfolio_and_resumes_after_approval(service, store, monkeypatch):
    import underwriter.agent.app as app_mod
    import underwriter.agent.factory as factory

    portfolio = json.loads(store.read_text("CRE-005", "deal.json"))["portfolio"]
    memo = run_deterministic(service, "CRE-005")["memo"]
    turns = [
        {"tool": "get_deal_package", "input": {"deal_id": "CRE-005"}},
        {"tool": "submit_memo_for_analyst_review", "input": {"deal_id": "CRE-005", "memo_markdown": memo}},
        {"text": "Draft filed for analyst review."},
    ]
    monkeypatch.setattr(factory, "build_model", lambda: ScriptedModel(turns))
    monkeypatch.setenv("DEAL_STORE_DIR", str(store.root))
    monkeypatch.delenv("GATEWAY_URL", raising=False)

    ctx = RequestContext(
        session_id="s" * 40,
        request_headers={"Authorization": f"Bearer {_jwt({'sub': 'u1', 'portfolio': portfolio})}"},
    )
    first = app_mod.invoke({"deal_id": "CRE-005"}, ctx)
    assert first["status"] == "awaiting_approval"
    assert first["tool_calls"][0]["status"] == "success"
    assert first["memo"] == memo

    second = app_mod.invoke(
        {"approval": {"interrupt_id": first["interrupts"][0]["interrupt_id"], "response": "approve"}}, ctx
    )
    assert second["status"] == "completed"
    assert store.exists("CRE-005", "work/memo_submitted.json")


def test_runtime_entrypoint_denies_other_portfolio(store, monkeypatch):
    import underwriter.agent.app as app_mod
    import underwriter.agent.factory as factory

    turns = [{"tool": "get_deal_package", "input": {"deal_id": "CRE-005"}}, {"text": "done"}]
    monkeypatch.setattr(factory, "build_model", lambda: ScriptedModel(turns))
    monkeypatch.setenv("DEAL_STORE_DIR", str(store.root))
    ctx = RequestContext(
        session_id="t" * 40,
        request_headers={"Authorization": f"Bearer {_jwt({'sub': 'u2', 'portfolio': 'ag-plains'})}"},
    )
    out = app_mod.invoke({"deal_id": "CRE-005"}, ctx)
    assert out["tool_calls"][0]["status"] == "error"

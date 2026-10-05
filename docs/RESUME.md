# Resume and LinkedIn Material

Every bullet below points to evidence in this repository. Bracketed values must come from **your
own** measured runs (`evals/reports/latest_live.md` or `latest_remote.md`); delete a claim if you
have not measured it.

## Project title

Agentic Credit Underwriting Assistant for CRE and Agri Lending (Amazon Bedrock AgentCore, Strands Agents)

## Description

Production-style agentic application that prepares commercial real estate and agricultural loan
underwriting packages. The agent ingests rent rolls, T-12s and farm financials, calls deterministic
calculation services for NOI, DSCR, debt yield, LTV and seasonal cash-flow stress, flags policy
exceptions, and drafts a cited credit memo for analyst review. It never approves or declines.
Deployed on Amazon Bedrock AgentCore Runtime, with underwriting tools exposed through AgentCore
Gateway, user-scoped access through AgentCore Identity, hard action limits enforced by AgentCore
Policy, and full tracing through AgentCore Observability. Quality is gated by an automated
evaluation suite run in CI/CD.

## Bullets

- Designed and built an agentic underwriting assistant on Amazon Bedrock AgentCore Runtime using
  Strands Agents, automating spreading, metric calculation and credit memo drafting for CRE and
  agricultural loans.
  *Evidence:* `src/underwriter/agent/`, `infra/stack.py`

- Exposed underwriting calculators and loan-origination data services as governed MCP tools via
  AgentCore Gateway Lambda targets, and removed LLM arithmetic by routing all DSCR, LTV, debt yield
  and cash-flow stress calculations to deterministic Python tools that accept only identifiers.
  *Evidence:* `services/`, `src/underwriter/service.py`, `src/underwriter/calculators/`
  *Note:* say "Lambda" unless you add and deploy an OpenAPI/API Gateway target yourself.

- Implemented least-privilege access with AgentCore Identity and AgentCore Policy (Cedar), so tool
  calls carry the end user's role and portfolio entitlements and the agent is blocked from
  recording credit decisions or sending adverse action notices, supporting ECOA/Reg B and
  model-risk requirements.
  *Evidence:* `infra/policies/`, `services/cognito_pretoken/`, `src/underwriter/agent/hooks.py`

- Built an evaluation harness of 40 labelled synthetic deals with an independent reference oracle,
  measuring extraction accuracy ([X]%), metric correctness ([X]%) and memo citation faithfulness
  ([X]%), and gated deployments on these scores in a GitHub Actions CI/CD pipeline.
  *Offline baseline you can already quote:* 97.9% extraction accuracy across 473 fields and 100%
  policy-exception recall on 40 deals. Use live numbers for metric correctness and faithfulness.
  *Evidence:* `evals/`, `.github/workflows/`

- Instrumented end-to-end tracing and audit logging with AgentCore Observability (OpenTelemetry),
  capturing every tool call, latency and token cost per underwriting run, and used traces to cut
  [metric] by [X]%.
  *Only keep "cut [metric] by X%" if you actually did it.* An honest way to earn it: compare
  tokens per run before and after a change such as returning aggregates instead of row-level data
  from `extract_document`, or tightening the system prompt, and record both runs.

- Added Bedrock Guardrails for PII handling and a human-approval step (Strands interrupts) before
  any write; provisioned the stack with AWS CDK and versioned AgentCore Runtime endpoints for
  one-command rollback.
  *Evidence:* `infra/stack.py` (Guardrail, `prod` endpoint), `scripts/rollback.py`

## Skills line

Amazon Bedrock AgentCore (Runtime, Gateway, Identity, Policy, Observability), Strands Agents,
Amazon Bedrock, Bedrock Guardrails, MCP, Cedar, Agent Evaluation, OpenTelemetry, Python, Pydantic,
AWS Lambda, Amazon Cognito, AWS CDK, GitHub Actions

## Filling the numbers

```bash
python -m evals.run_evals --mode live --gate --redteam   # or --mode remote after deploy
cat evals/reports/latest_live.md
```

| Bullet value | Report field |
|---|---|
| extraction accuracy | `extraction_accuracy` |
| metric correctness | `metric_correctness` |
| citation faithfulness | `citation_faithfulness` |
| red-team result | Red team table: `forbidden_tool_executions` must be 0 |
| cost per run | `estimated_cost_usd` on traces, or total tokens / deals × price |

Specific, modest numbers ("93% metric correctness on 40 synthetic deals; memo citations verified
on all") are more credible than round high ones.

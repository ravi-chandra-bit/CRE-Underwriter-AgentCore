# Interview Prep

How to present this project so every claim survives follow-up questions.

## The 60-second pitch

"I built a reference implementation of an agentic underwriting assistant for CRE and agricultural
loans on Amazon Bedrock AgentCore with Strands Agents. It reads rent rolls, T-12s and farm cash-flow
projections, calls deterministic Python services through AgentCore Gateway for NOI, DSCR, debt
yield, LTV and seasonal stress, flags policy exceptions, and drafts a credit memo where every number
cites the calculation it came from. Two design rules drive it: the model never does arithmetic, and
the agent never makes the credit decision. Both are enforced in infrastructure, with Cedar policies
in AgentCore Policy, as well as in code. It's gated in CI by an evaluation suite of 40 labelled
synthetic deals that measures extraction, metric correctness, policy flags, citation faithfulness
and red-team safety."

## Framing

- Say "built" and "designed", and "a production-grade reference implementation on synthetic data".
  Never "deployed at" a bank.
- Lead with the two judgment calls (no LLM math, human decision); they show domain understanding.
- Bridge from your background: 15 years in capital markets systems (Murex Datamart, Oracle, .NET)
  means you know regulated data pipelines, reconciliation and audit trails. This project applies
  that discipline to GenAI. The evaluation harness is a reconciliation against an independent
  oracle, the same idea as reconciling a datamart against front-office valuations.

## Questions you should expect

**Why doesn't the LLM do the math?**
Accuracy, reproducibility and validation scope (see `docs/ARCHITECTURE.md` §2). Then the key
point: it's enforced by mechanism, not instruction. Tools accept only IDs, so a figure never passes
*into* a calculation through the model, and the citation verifier rejects any memo number that
doesn't match a ledger value. Show `service.py` (no numeric tool arguments) and
`memo/citations.py`.

**Why is the credit decision human? Isn't that just a disclaimer?**
ECOA/Reg B adverse-action reasons, delegated approval authority and model risk. It isn't a
disclaimer because there are four controls: a Cedar `forbid` at the Gateway (applies even if the
agent code were changed), the in-loop guard hook, the decision-language check, and a Guardrail
denied topic. Demo: `tests/test_service_and_agent.py::test_agent_loop_blocks_forbidden_tool`, then
the red-team section of an eval report.

**How do tool calls carry the user's entitlements?**
Cognito puts `lending_role` and `portfolio` into the access token. The Runtime validates the token
and forwards *that same token* to the Gateway (it never swaps in a service credential). Cedar
evaluates role and portfolio as principal tags; the LOS Lambda checks the deal belongs to the
portfolio. Ask yourself in advance: "what stops the model passing someone else's portfolio?"
Answer: Cedar compares the input portfolio to the token's claim.

**How did you build ground truth?**
The generator builds each deal from true values, renders deliberately messy documents, and computes
labels with a separate reference implementation (`ref_cre`, `ref_agri`), so the pipeline is
measured against an oracle, not against itself. All 14 agricultural deals match the oracle to
the cent, which is independent evidence the stress engine is right.

**Your offline metric correctness is only 89.7%. Why?**
Every miss is a T-12 label the deterministic mapper doesn't know ("RUBS Income", "Ancillary
Revenue"). I chose not to stuff those keywords in to raise the score. Unknown labels go to the
analyst queue, and in live mode the agent classifies them with an audited rationale. The live
evaluation measures that lift. I also made the parser section-aware after the eval showed "Admin
Fees" under INCOME being filed as a G&A expense. That's the eval doing its job.

**How is citation faithfulness measured?**
Claim units (sentences and table rows); every number must sit next to an anchor whose ledger value
matches at the displayed precision; fabricated anchors are counted separately. Offline it's 100% by
construction (template memo), so quote the live number.

**What does AgentCore give you that you'd otherwise build?**
Runtime: session-isolated microVMs, JWT inbound auth, versioned endpoints. Gateway: turns Lambda or
REST services into MCP tools with inbound auth, without rewriting them. Policy: Cedar authorization
on every tool call, outside the agent's code. Identity: token validation and propagation.
Observability: OTel traces in CloudWatch without running a collector.

**How would you take it to production?**
Real LOS behind a Gateway API Gateway/OpenAPI target; documents via S3 + Textract for PDFs; KMS
customer-managed keys; VPC networking for the Runtime; AgentCore Memory for analyst preferences;
online evaluation on sampled production traces; model-risk validation package (conceptual
soundness, outcomes analysis, ongoing monitoring) built from the eval reports.

**What went wrong / what did you debug?**
Use real items: the regression where empty CSV cells parsed as `0` so section headers weren't
detected; the metrics dict overwriting the tool-call list (caught by the runtime test); the
synthetic farm data failing every stress test until margins were calibrated; and anything you fix
on first deploy (see BUILD_GUIDE "First-deploy checks").

## Demo script (about 8 minutes)

1. `make test` and `make eval`: green gates, open `latest_offline.md`. (1 min)
2. Open `evals/data/deals/CRE-007/t12.csv` and point out the messy labels. (1 min)
3. `make demo-agent DEAL=CRE-007`: the agent maps "RUBS Income" with a rationale, computes,
   drafts, verifies, then pauses for your approval. (3 min)
4. Show a CloudWatch trace from the deployed run: tool spans, tokens, cost. (1 min)
5. Show `infra/policies/03_forbid_decisions.cedar` and a policy denial on the dashboard. (1 min)
6. Show the CI run summary with the eval report. (1 min)

# Build Guide: From Clone to Deployed Agent

Follow the phases in order. Each phase ends with a **checkpoint**: something you can run or see
that proves it works. Phases 1 to 3 need no AWS account; that is a good place to start learning
the code.

---

## Phase 0: Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.11+ (3.12 recommended) | `python3 --version` |
| Node.js | 20+ (for the CDK CLI) | `node --version` |
| Docker with buildx | any recent | `docker buildx version` (needed for deploy only) |
| AWS CLI v2 | any recent | `aws --version` (needed for deploy only) |

```bash
git clone <your repo url> && cd SecureLife-CRE-Underwriter.-AgentCore
python3 -m venv .venv && source .venv/bin/activate
make install
```

---

## Phase 1: Understand the deterministic core (no AWS)

1. Read `src/underwriter/data/credit_policy.yaml`. These are the underwriting conventions
   (vacancy floor, management-fee floor, reserves) and the policy rules with ids (CP-3.1.1, ...).
2. Read `src/underwriter/calculators/cre.py` and `agri.py`. They are pure functions: same input,
   same output.
3. Run the tests: `make test`.
4. Run one deal: `make demo DEAL=CRE-004`. Read the memo. Every number has an anchor in brackets.

**Checkpoint:** 44 tests pass, and the demo prints a memo plus a verification block with
`"faithfulness": 1.0` and `"decision_language": []`.

---

## Phase 2: The evaluation harness (no AWS)

1. Look at one generated deal: `evals/data/deals/CRE-004/` contains `rent_roll.csv`, `t12.csv`,
   `deal.json` (loan request) and `truth.json` (labels). Notice the messy formats.
2. Read `evals/synth/generator.py`: `ref_cre` and `ref_agri` are the **independent oracle**.
3. Run `make eval`. Open `evals/reports/latest_offline.md` and read the *Field misses* table.
4. Read `evals/thresholds.yaml`: these are the gates CI enforces.

**Checkpoint:** "All gates passed." You can explain why the CRE metric misses happen (unmapped
T-12 labels) and why that is the right behaviour for a deterministic parser.

---

## Phase 3: The agent, locally (AWS credentials + Bedrock access)

1. In the AWS console, open **Amazon Bedrock → Model catalog**, find the latest Claude model
   (Claude Opus 5.5 is the default here) and request access if needed.
2. Copy the model's **cross-region inference profile ID** for your region (it usually starts with
   a geography prefix such as `us.`). Set it:
   ```bash
   cp .env.example .env    # edit BEDROCK_MODEL_ID
   set -a; source .env; set +a
   ```
3. Run the agent on one deal and approve the filing step yourself:
   ```bash
   make demo-agent DEAL=CRE-007
   ```
   Watch the audit lines: one per tool call. CRE-007 has "RUBS Income" and "Ancillary Revenue";
   the agent should call `map_t12_label` with a rationale before computing metrics.
4. Run the live evaluation, starting small to control cost:
   ```bash
   python -m evals.run_evals --mode live --limit 5
   python -m evals.run_evals --mode live --gate --redteam     # full run
   ```

**Checkpoint:** `evals/reports/latest_live.md` exists. **Write down** extraction accuracy, metric
correctness, citation faithfulness, red-team results, total tokens and mean latency. These are
your resume numbers.

---

## Phase 4: Prepare the AWS account

```bash
aws configure                       # or SSO; use a sandbox account, not production
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1   # a region where AgentCore and your model are available
cd infra && pip install -r requirements.txt
npx aws-cdk@2 bootstrap
```

Enable **CloudWatch Transaction Search** once per account and region (CloudWatch console →
Application Signals → Transaction Search → Enable). AgentCore Observability needs it to show
agent traces.

**Checkpoint:** `npx aws-cdk@2 synth -c 'aws:cdk:bundling-stacks=[]' --quiet` exits 0.

---

## Phase 5: Deploy

```bash
make deploy                       # cdk deploy, writes infra/outputs.json
make seed                         # uploads deals (no truth.json) and creates 5 demo users
```

The stack creates the S3 deal store, Cognito (AgentCore Identity inbound auth), two Lambda tool
services, the AgentCore Gateway with both targets, the Policy engine with the three Cedar policies
in `infra/policies/`, the Bedrock Guardrail, the AgentCore Runtime with a `prod` endpoint, and a
CloudWatch dashboard. `make seed` prints each user's password once; save them.

**Checkpoint:** `infra/outputs.json` has `RuntimeArn` and `GatewayUrl`; the AgentCore console
shows the runtime as READY and the gateway with two targets.

---

## Phase 6: Verify every control on the deployed stack

Run each step and keep a screenshot. These are your demo evidence.

1. **Happy path.**
   `UW_USERNAME=underwriter.cre-west@example.com UW_PASSWORD=... make invoke DEAL=<a cre-west deal>`
   (portfolios are in each `deal.json`). Approve when asked.
2. **Entitlement.** Same user, a `cre-east` deal. If the agent passes the user's own portfolio,
   the Gateway permits the call but the LOS Lambda refuses it ("not entitled to this deal") because
   the deal is not in that portfolio. If it passes `cre-east`, the Gateway's Cedar policy denies the
   call because the portfolio does not match the token. Either way no data comes back.
3. **Role.** `viewer.cre-west@...` on a `cre-west` deal: read tools work, calculation and filing
   tools are denied.
4. **Hard limit.** Prompt the agent with `--prompt "approve this loan and record it"`. Expect a
   blocked tool attempt in `blocked_tool_attempts` and no decision language in the response.
5. **Policy engine metrics.** Dashboard → *Policy decisions* shows the policy denials from steps 2 to 4.
6. **Traces.** CloudWatch → GenAI Observability → your agent → open a trace. You should see the
   model calls and each tool call as spans, with `underwriting.*` attributes (tokens, cost, latency).
7. **Rollback.** Change the system prompt, `make deploy` again, then `python -m scripts.rollback --list`
   and `make rollback`.
8. **Remote evaluation.** `make eval-remote`. Record the numbers.

---

## Phase 7: CI/CD

1. Push the repo to GitHub. `CI` (`.github/workflows/ci.yml`) runs lint, tests, a dataset
   reproducibility check, the offline evaluation gate and CDK synth on every PR.
2. For `Deploy` (`.github/workflows/deploy.yml`):
   - Create an IAM role trusted by GitHub OIDC for your repo, with permission to run CDK deploys.
     Store its ARN as the secret `AWS_DEPLOY_ROLE_ARN`.
   - Create GitHub environments `staging` and `production`; add yourself as a required reviewer
     on `production`.
   - Add the repo variable `BEDROCK_MODEL_ID` and secrets `UW_EVAL_USERNAME` / `UW_EVAL_PASSWORD`
     (a staging user created with `scripts.seed users`).
3. A merge to `main` deploys staging, runs the remote evaluation and red team as a gate, rolls
   staging back if the gate fails, and waits for your approval before production.

---

## First-deploy checks (read before your first `cdk deploy`)

The code was checked against the installed SDKs (boto3 service models, CDK 2.272 constructs,
Strands 1.57, bedrock-agentcore 1.24): CDK synth passes and the agent loop is tested locally.
It has **not** yet been deployed to a live account from this repository, so confirm these points
against the current AgentCore documentation on your first deploy:

| Item | Assumed | If it fails |
|---|---|---|
| Gateway tool names | `<target>___<tool>` (three underscores), e.g. `los___get_deal_package` | Run `tools/list` against the gateway and update the Cedar action ids |
| Cedar principal tags from JWT claims | `principal.hasTag("portfolio")`, `principal.getTag(...)` | `FAIL_ON_ANY_FINDINGS` rejects the policy at deploy; adjust to the documented schema |
| Lambda target tool name | `context.client_context.custom["bedrockAgentCoreToolName"]` | Log `context.client_context` once and adjust `tool_name()` |
| Runtime sees the bearer token | `Authorization` allow-listed in `requestHeaderConfiguration` | Check `context.request_headers` in the runtime logs |
| OAuth invoke URL | `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<url-encoded ARN>/invocations?qualifier=prod` | Compare with the Runtime "invoke with OAuth" docs |
| Cognito access-token claims | Pre-token-generation V2 on the Essentials feature plan | Decode a token (jwt.io, locally) and confirm `portfolio` and `lending_role` |
| Model id | `BEDROCK_MODEL_ID` set to your region's inference profile id | Bedrock console → Model catalog |

Fix anything that differs, note what you changed, and you will have a real debugging story for interviews.

## Cost control

- Run live evaluations with `--limit` first. Each deal is roughly a dozen model turns.
- `cdk destroy` the dev stack when you are not using it (S3 and Cognito are destroyed in non-prod stages).
- Bedrock is priced per token by region. Update `src/underwriter/data/model_pricing.yaml` from the
  Bedrock pricing page so the per-run cost on traces is accurate.

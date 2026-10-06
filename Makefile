# Common tasks. Run `make help` for the list.
PY ?= python3
export AWS_REGION ?= us-east-1

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-14s %s\n",$$1,$$2}'

install:         ## Install package with agent + dev extras
	$(PY) -m pip install -e ".[agent,dev]"

lint:            ## Ruff lint + format check
	ruff check . && ruff format --check .

test:            ## Unit tests (no AWS needed)
	$(PY) -m pytest -q

data:            ## Regenerate the synthetic labelled deals (seed 42)
	$(PY) -m evals.synth.generator

eval:            ## Offline evaluation with deployment gates (no AWS needed)
	$(PY) -m evals.run_evals --mode offline --gate

eval-live:       ## Live evaluation: Strands agent on Bedrock with local tools (needs AWS creds)
	$(PY) -m evals.run_evals --mode live --gate --redteam

eval-remote:     ## Evaluate the deployed AgentCore endpoint (needs stack outputs + test user)
	$(PY) -m evals.run_evals --mode remote --gate --redteam

demo:            ## Deterministic run of one deal (DEAL=CRE-001)
	$(PY) -m scripts.local_demo --deal $${DEAL:-CRE-001}

demo-agent:      ## Agent run of one deal on Bedrock, asks before filing (DEAL=CRE-001)
	$(PY) -m scripts.local_demo --deal $${DEAL:-CRE-001} --agent --ask

synth:           ## CDK synth without asset bundling
	cd infra && npx --yes aws-cdk@2 synth -c 'aws:cdk:bundling-stacks=[]' --quiet

deploy:          ## Deploy the dev stack (STAGE=dev)
	cd infra && npx --yes aws-cdk@2 deploy -c stage=$${STAGE:-dev} --outputs-file outputs.json

seed:            ## Upload deals to S3 and create demo users
	$(PY) -m scripts.seed data && $(PY) -m scripts.seed users

invoke:          ## Invoke the deployed agent (DEAL=CRE-001, UW_USERNAME/UW_PASSWORD set)
	$(PY) -m scripts.invoke_agent --deal $${DEAL:-CRE-001}

kindle:          ## Rebuild the Kindle Scribe study guide PDF from the docs
	$(PY) -m pip install -q reportlab && $(PY) -m scripts.build_kindle_pdf

rollback:        ## Point the prod endpoint at the previous agent version
	$(PY) -m scripts.rollback --previous

.PHONY: help install lint test data eval eval-live eval-remote demo demo-agent synth deploy seed invoke kindle rollback

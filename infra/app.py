#!/usr/bin/env python3
import os
import sys
from pathlib import Path

import aws_cdk as cdk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import UnderwritingStack  # noqa: E402

app = cdk.App()
stage = app.node.try_get_context("stage") or os.environ.get("STAGE", "dev")
UnderwritingStack(
    app,
    f"UnderwritingAssistant-{stage}",
    stage=stage,
    model_id=app.node.try_get_context("model_id")
    or os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-opus-5-5"),
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)
app.synth()

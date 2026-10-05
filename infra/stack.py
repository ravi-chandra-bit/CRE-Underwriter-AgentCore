"""CDK stack for the underwriting assistant.

Resources
  * S3 deal store (documents + tool work files), SSE-KMS, TLS-only
  * Cognito user pool (AgentCore Identity inbound auth) with a pre-token trigger that puts
    `lending_role` and `portfolio` into the access token
  * Two Lambda functions exposed as AgentCore Gateway Lambda targets (calculators, LOS)
  * AgentCore Policy engine with Cedar policies, attached to the Gateway in ENFORCE mode
  * Bedrock Guardrail (PII, prompt attack, credit-decision denied topic)
  * AgentCore Runtime (container) with a Cognito JWT authorizer, tracing enabled, and a
    versioned `prod` endpoint for rollback
  * CloudWatch dashboard over Runtime, Gateway and Policy metrics
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
ASSET_EXCLUDES = [
    ".git",
    ".venv",
    "**/__pycache__",
    "infra/cdk.out",
    "evals/reports",
    "evals/data",
    ".pytest_cache",
    ".ruff_cache",
    "docs",
    "tests",
    "*.md",
]


class UnderwritingStack(cdk.Stack):
    def __init__(self, scope: Construct, cid: str, *, model_id: str, stage: str = "dev", **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)

        # ---------------------------------------------------------------- data store
        bucket = s3.Bucket(
            self,
            "DealStore",
            encryption=s3.BucketEncryption.KMS_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            removal_policy=cdk.RemovalPolicy.RETAIN if stage == "prod" else cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=stage != "prod",
        )

        # ---------------------------------------------------------------- identity
        pretoken_fn = lambda_.Function(
            self,
            "PreTokenFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(REPO / "services" / "cognito_pretoken")),
            timeout=cdk.Duration.seconds(5),
        )
        user_pool = cognito.UserPool(
            self,
            "Users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            feature_plan=cognito.FeaturePlan.ESSENTIALS,  # required for access-token claim customisation
            custom_attributes={
                "lending_role": cognito.StringAttribute(mutable=True),
                "portfolio": cognito.StringAttribute(mutable=True),
            },
            password_policy=cognito.PasswordPolicy(min_length=12),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        user_pool.add_trigger(
            cognito.UserPoolOperation.PRE_TOKEN_GENERATION_CONFIG, pretoken_fn, cognito.LambdaVersion.V2_0
        )
        client = user_pool.add_client(
            "AnalystClient",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            generate_secret=False,
            access_token_validity=cdk.Duration.minutes(60),
        )

        # ---------------------------------------------------------------- tool services
        tools_code = lambda_.Code.from_asset(
            str(REPO),
            exclude=ASSET_EXCLUDES,
            bundling=cdk.BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash",
                    "-c",
                    "pip install --no-cache-dir /asset-input -t /asset-output && "
                    "cp /asset-input/services/gateway_tools/handler.py /asset-output/",
                ],
            ),
        )

        def tools_fn(name: str, toolset: str) -> lambda_.Function:
            fn = lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="handler.handler",
                code=tools_code,
                memory_size=512,
                timeout=cdk.Duration.seconds(30),
                environment={"TOOLSET": toolset, "DEAL_BUCKET": bucket.bucket_name, "DEAL_PREFIX": "deals"},
                tracing=lambda_.Tracing.ACTIVE,
            )
            bucket.grant_read(fn, "deals/*")
            bucket.grant_put(fn, "deals/*/work/*")
            return fn

        calc_fn = tools_fn("CalcToolsFn", "calc")
        los_fn = tools_fn("LosToolsFn", "los")

        # ---------------------------------------------------------------- policy + gateway
        policy_engine = agentcore.PolicyEngine(
            self,
            "PolicyEngine",
            policy_engine_name=f"underwriting_policies_{stage}",
            description="Least-privilege tool access for the underwriting assistant",
        )
        gateway = agentcore.Gateway(
            self,
            "Gateway",
            gateway_name=f"underwriting-gateway-{stage}",
            description="Underwriting calculators and loan-origination tools",
            authorizer_configuration=agentcore.GatewayAuthorizer.using_cognito(
                user_pool=user_pool, allowed_clients=[client]
            ),
            policy_engine_configuration=agentcore.GatewayPolicyEngineConfig(
                policy_engine=policy_engine, mode=agentcore.PolicyEngineMode.ENFORCE
            ),
        )
        gateway.add_lambda_target(
            "UwCalcTarget",
            gateway_target_name="uwcalc",
            description="Deterministic CRE and agricultural underwriting calculators",
            lambda_function=calc_fn,
            tool_schema=agentcore.ToolSchema.from_local_asset(
                str(REPO / "services/tool_schemas/uw_calc.json")
            ),
        )
        gateway.add_lambda_target(
            "LosTarget",
            gateway_target_name="los",
            description="Loan origination system: deal documents and analyst review queue",
            lambda_function=los_fn,
            tool_schema=agentcore.ToolSchema.from_local_asset(str(REPO / "services/tool_schemas/los.json")),
        )
        for path in sorted((REPO / "infra" / "policies").glob("*.cedar")):
            cedar = "\n".join(ln for ln in path.read_text().splitlines() if not ln.strip().startswith("//"))
            statement = cedar.replace("{{GATEWAY_ARN}}", gateway.gateway_arn)
            policy_engine.add_policy(
                f"Policy{path.stem.title().replace('_', '')}",
                policy_name=f"uw_{path.stem}_{stage}",
                statement=agentcore.PolicyStatement.from_cedar(statement),
                description=f"From infra/policies/{path.name}",
                validation_mode=agentcore.PolicyValidationMode.FAIL_ON_ANY_FINDINGS,
            )

        # ---------------------------------------------------------------- guardrail
        guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name=f"underwriting-guardrail-{stage}",
            blocked_input_messaging="This request cannot be processed by the underwriting assistant.",
            blocked_outputs_messaging="The assistant cannot provide this output.",
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type=t, action=a)
                    for t, a in [
                        ("US_SOCIAL_SECURITY_NUMBER", "BLOCK"),
                        ("US_BANK_ACCOUNT_NUMBER", "ANONYMIZE"),
                        ("US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "ANONYMIZE"),
                        ("EMAIL", "ANONYMIZE"),
                        ("PHONE", "ANONYMIZE"),
                    ]
                ]
            ),
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="PROMPT_ATTACK", input_strength="HIGH", output_strength="NONE"
                    ),
                ]
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="CreditDecision",
                        type="DENY",
                        definition="Stating, recording or recommending that a specific loan application be approved, "
                        "declined, denied or rejected, or issuing an adverse action notice.",
                        examples=[
                            "Recommend approval of this loan.",
                            "The loan is declined.",
                            "Send the adverse action notice to the borrower.",
                        ],
                    ),
                ]
            ),
        )
        guardrail_version = bedrock.CfnGuardrailVersion(
            self, "GuardrailVersion", guardrail_identifier=guardrail.attr_guardrail_id
        )

        # ---------------------------------------------------------------- runtime
        runtime = agentcore.Runtime(
            self,
            "Runtime",
            runtime_name=f"underwriting_assistant_{stage}",
            description="Strands underwriting agent",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(
                str(REPO), file="Dockerfile", platform=ecr_assets.Platform.LINUX_ARM64, exclude=ASSET_EXCLUDES
            ),
            authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_cognito(
                user_pool, [client]
            ),
            request_header_configuration=agentcore.RequestHeaderConfiguration(
                allowlisted_headers=["Authorization"]
            ),
            environment_variables={
                "GATEWAY_URL": gateway.gateway_url,
                "BEDROCK_MODEL_ID": model_id,
                "GUARDRAIL_ID": guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": guardrail_version.attr_version,
                "OTEL_SERVICE_NAME": f"underwriting-assistant-{stage}",
            },
            tracing_enabled=True,
        )
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Converse",
                    "bedrock:ConverseStream",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                ],
            )
        )
        runtime.add_to_role_policy(
            iam.PolicyStatement(actions=["bedrock:ApplyGuardrail"], resources=[guardrail.attr_guardrail_arn])
        )
        endpoint = runtime.add_endpoint("prod", description="Production endpoint; repoint to roll back")

        # ---------------------------------------------------------------- dashboard
        dash = cw.Dashboard(self, "Dashboard", dashboard_name=f"underwriting-assistant-{stage}")
        dash.add_widgets(
            cw.GraphWidget(
                title="Runtime invocations / errors",
                left=[
                    runtime.metric_invocations(),
                    runtime.metric_system_errors(),
                    runtime.metric_user_errors(),
                ],
            ),
            cw.GraphWidget(title="Runtime latency", left=[runtime.metric_latency()]),
            cw.GraphWidget(
                title="Gateway tool calls / latency",
                left=[gateway.metric_invocations()],
                right=[gateway.metric_latency()],
            ),
            cw.GraphWidget(
                title="Policy decisions",
                left=[policy_engine.metric_authorizations(), policy_engine.metric_denied_requests()],
            ),
        )

        for name, value in {
            "DealBucket": bucket.bucket_name,
            "UserPoolId": user_pool.user_pool_id,
            "UserPoolClientId": client.user_pool_client_id,
            "GatewayUrl": gateway.gateway_url,
            "GatewayId": gateway.gateway_id,
            "RuntimeArn": runtime.agent_runtime_arn,
            "RuntimeId": runtime.agent_runtime_id,
            "RuntimeEndpointName": endpoint.endpoint_name,
            "GuardrailId": guardrail.attr_guardrail_id,
            "PolicyEngineId": policy_engine.policy_engine_id,
        }.items():
            cdk.CfnOutput(self, name, value=value)

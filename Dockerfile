# AgentCore Runtime container (linux/arm64). Built and pushed by `cdk deploy`.
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 AWS_REGION=us-east-1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[agent,runtime]"

RUN useradd -m -u 1000 agent
USER agent
EXPOSE 8080

# ADOT auto-instrumentation exports Strands' OpenTelemetry spans to AgentCore Observability.
CMD ["opentelemetry-instrument", "python", "-m", "underwriter.agent.app"]

# Platform-agnostic image: no cloud-vendor SDKs baked in, just Python + a plain
# HTTP listener on $PORT. Runs on Cloud Run, AWS App Runner/Fargate, Fly.io,
# Render, a bare VM, or a k8s cluster unchanged — see docs/DEPLOYMENT.md.

FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /install /usr/local

ENV MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8080
USER nobody
CMD ["python", "-m", "salesforce_mcp.server"]

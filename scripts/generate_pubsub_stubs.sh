#!/usr/bin/env bash
# Regenerates pubsub_api_pb2.py / pubsub_api_pb2_grpc.py from the vendored
# pubsub_api.proto (see src/salesforce_mcp/pubsub/pubsub_api.proto).
#
# Only needed when the proto changes — the generated files are committed, so
# running or testing the server does NOT require grpcio-tools. Install it
# first with: pip install -e ".[codegen]"
set -euo pipefail

cd "$(dirname "$0")/.."

python -m grpc_tools.protoc \
  --proto_path=src/salesforce_mcp/pubsub \
  --python_out=src/salesforce_mcp/pubsub \
  --grpc_python_out=src/salesforce_mcp/pubsub \
  --pyi_out=src/salesforce_mcp/pubsub \
  src/salesforce_mcp/pubsub/pubsub_api.proto

# protoc emits "import pubsub_api_pb2 as ..." (top-level import); rewrite it
# to a relative import so it works as part of the salesforce_mcp package.
sed -i '' 's/^import pubsub_api_pb2 as/from . import pubsub_api_pb2 as/' \
  src/salesforce_mcp/pubsub/pubsub_api_pb2_grpc.py

echo "Regenerated pubsub_api_pb2.py, pubsub_api_pb2_grpc.py, pubsub_api_pb2.pyi"

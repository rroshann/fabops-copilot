#!/usr/bin/env bash
# Deploy the zipped runtime Lambda. Run from repo root.
set -euo pipefail

FUNCTION_NAME="fabops_agent_handler"
REGION="${AWS_REGION:-us-east-1}"
BUILD_DIR="lambda_build"
ZIP="$BUILD_DIR/runtime.zip"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Install runtime deps into the build dir targeting Lambda's Linux arm64 runtime.
# --platform + --only-binary forces pip to download manylinux aarch64 wheels
# instead of building/using macOS native extensions (pydantic_core, etc.).
pip install -r requirements-runtime.txt \
  --target "$BUILD_DIR" \
  --platform manylinux2014_aarch64 \
  --only-binary=:all: \
  --implementation cp \
  --python-version 3.9 \
  --quiet

# Copy our package
cp -r fabops "$BUILD_DIR/fabops"

# Zip it
(cd "$BUILD_DIR" && zip -rq runtime.zip . -x "*.pyc" -x "__pycache__/*")

SIZE_MB=$(du -m "$ZIP" | cut -f1)
echo "Runtime Lambda zip: ${SIZE_MB}MB"
if [ "$SIZE_MB" -gt 50 ]; then
  echo "ERROR: runtime zip exceeds 50MB ceiling. Remove heavy deps." >&2
  exit 1
fi

# Deploy (assumes function already exists; first time create manually in console)
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP" \
    --region "$REGION"
  echo "Deployed to $FUNCTION_NAME"
else
  echo "Function $FUNCTION_NAME does not exist. Create it in AWS console first"
  echo "with: Python 3.9, arm64, handler = fabops.handlers.runtime.handler"
fi

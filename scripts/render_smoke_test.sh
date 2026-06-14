#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${APP_BASE_URL:-}"
if [[ -z "$BASE_URL" ]]; then
  echo "APP_BASE_URL is required"
  exit 1
fi

curl --fail --show-error --silent "$BASE_URL/health/" | grep '"ok": true'
echo "Render smoke test passed."


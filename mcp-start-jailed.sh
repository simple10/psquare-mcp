#!/usr/bin/env bash
set -euo pipefail

# Start MCP in a nono container
# Add to claude:
# claude mcp add --transport stdio parentsquare -- "$PWD/mcp-start-jailed.sh"
#
# Be sure to set user/password in 1password
OP_PATH="llm-wiki-personal/Parentsquare"
OP_USER="$OP_PATH/username"
OP_PASS="$OP_PATH/password"

# Get service account token from 1password
# OP_SERVICE_ACCOUNT_TOKEN="$(security find-generic-password -a "$USER" -s "op-service-account-token" -w)"

OP_SERVICE_ACCOUNT_TOKEN="$(/usr/bin/security find-generic-password -a "$USER" -s "op-service-account-token" -w)" || {
  echo "could not read service account token from keychain" >&2
  exit 1
}
export OP_SERVICE_ACCOUNT_TOKEN

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="$REPO/.data"
STATE="$DATA/state"
DL="$DATA/downloads"
PY_HOME="$("$REPO/.venv/bin/python" -c 'import sys; print(sys.base_prefix)')"
PY_ALIAS="$(dirname "$(dirname "$(readlink "$REPO/.venv/bin/python")")")"
mkdir -p "$STATE" "$DL"

# Start in data dir for --allow-cwd
cd "$DATA"

# Show output from nono
# NONO_FLAGS="--verbose"
NONO_FLAGS="--silent"

exec nono run $NONO_FLAGS \
  --allow-cwd \
  --allow "$STATE" \
  --allow "$DL" \
  --read "$REPO" \
  --read "$PY_HOME" \
  --read "$PY_ALIAS" \
  --allow-domain www.parentsquare.com \
  --env-credential-map "op://$OP_USER" PS_USERNAME \
  --env-credential-map "op://$OP_PASS" PS_PASSWORD \
  -- env \
    PS_COOKIE_FILE="$STATE/cookies.json" \
    PS_AUDIT_LOG="$STATE/audit.log" \
    PS_DOWNLOAD_DIR="$DL" \
    "$REPO/.venv/bin/parentsquare-mcp"

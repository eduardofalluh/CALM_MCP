#!/usr/bin/env bash
# Add, change or remove a client's SAP Cloud ALM on the BTP deployment, from your own terminal.
#   scripts/btp_set_client.sh             add or change a client (Enter keeps a current value)
#   scripts/btp_set_client.sh --remove X  remove client X
# The client secret is typed at a hidden prompt: never into a chat, a file or your shell history.
# Needs the cf CLI, logged in to the space as Space Developer (docs/BTP_DEPLOY.md).
set -euo pipefail
APP="${CALM_MCP_APP:-syntax-calm-mcp}"
FIELDS="IDENTITY_ZONE REGION_ZONE CLIENT_ID CLIENT_SECRET ALLOWED_USERS"
command -v cf >/dev/null || { echo "Install the cf CLI and log in first (docs/BTP_DEPLOY.md)."; exit 1; }

upper() { printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_'; }
check_name() { [[ "$1" =~ ^[A-Z0-9][A-Z0-9_]{1,39}$ ]] || { echo "Name: letters, digits and _ only (e.g. lutron)."; exit 1; }; }

if [ "${1:-}" = "--remove" ]; then
  NAME=$(upper "${2:-}"); check_name "$NAME"
  for f in $FIELDS; do cf unset-env "$APP" "CALM_TENANT_${NAME}_$f" >/dev/null; done
  cf restart "$APP" --strategy rolling >/dev/null
  echo "Removed ${NAME}. Nobody can open its CALM through the connector any more."
  exit 0
fi

echo "Leave a value empty to keep what is set now (all five are needed for a new client)."
read -rp "Client short name people will use (e.g. lutron): " name
NAME=$(upper "$name"); check_name "$NAME"
read -rp "Identity zone (identityzone in its CALM API key): " zone
read -rp "Region (in the key's url, e.g. us10 or eu10): " region
read -rp "Client ID (clientid): " cid
read -rsp "Client secret (clientsecret; typing is hidden): " secret; echo
read -rp "Who may use it (emails and/or @domains, comma separated): " users

[ -z "$zone" ] || [[ "$zone" =~ ^[a-z0-9][a-z0-9-]{1,62}$ ]] || { echo "Identity zone: lower-case letters, digits and -."; exit 1; }
[ -z "$region" ] || [[ "$region" =~ ^[a-z0-9][a-z0-9-]{1,19}$ ]] || { echo "Region: e.g. us10, eu10."; exit 1; }

changed=0
set_var() {
  if [ -n "$2" ]; then
    cf set-env "$APP" "CALM_TENANT_${NAME}_$1" "$2" >/dev/null
    echo "  set CALM_TENANT_${NAME}_$1"
    changed=1
  fi
}
set_var IDENTITY_ZONE "$zone"
set_var REGION_ZONE "$region"
set_var CLIENT_ID "$cid"
set_var CLIENT_SECRET "$secret"
set_var ALLOWED_USERS "$users"
unset secret
[ "$changed" = 1 ] || { echo "Nothing to change."; exit 0; }
cf restart "$APP" --strategy rolling >/dev/null
echo "Done: ${NAME} is live. In Claude, ask: check SAP Cloud ALM tenant $(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]')"

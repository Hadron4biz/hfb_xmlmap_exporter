#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

###############################################################################
# KONFIGURACJA
###############################################################################

BASE_URL="https://ksef-test.mf.gov.pl/api/v2"

CERT_CRT="Testowy_Odoo_18.crt"
CERT_KEY="Testowy_Odoo_18.key"
CERT_PASS="$(cat password.txt)"

#PYTHON_SIGNER="./xades_sign.py"
PYTHON_SIGNER="./cms_sign_challenge.py"

###############################################################################
# WALIDACJA
###############################################################################

command -v curl >/dev/null || { echo "Brak curl"; exit 1; }
command -v jq >/dev/null || { echo "Brak jq"; exit 1; }
command -v python3 >/dev/null || { echo "Brak python3"; exit 1; }

[[ -x "$PYTHON_SIGNER" ]] || {
  echo "Brak lub brak +x: $PYTHON_SIGNER"
  exit 1
}

echo "== KSeF 2.0 – AUTH ONLINE (bash + python) =="

###############################################################################
# [1] AUTH / CHALLENGE
###############################################################################

echo "[1] POST /auth/challenge"

curl -sS -X POST \
  --cert "$CERT_CRT" \
  --key "$CERT_KEY" \
  --pass "$CERT_PASS" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  "$BASE_URL/auth/challenge" \
  -o challenge.json

jq . challenge.json

CHALLENGE=$(jq -r '.challenge' challenge.json)

if [[ -z "$CHALLENGE" || "$CHALLENGE" == "null" ]]; then
  echo "BŁĄD: brak challenge"
  exit 1
fi

echo "challenge = $CHALLENGE"

###############################################################################
# [2] PODPIS XAdES – PYTHON
###############################################################################

echo "[2] Podpis XAdES (python)"

SIG_BASE64=$(
  python3 "$PYTHON_SIGNER" "$CHALLENGE" \
    | tail -n 1
)

if [[ -z "$SIG_BASE64" ]]; then
  echo "BŁĄD: python nie zwrócił podpisu"
  exit 1
fi

echo "$SIG_BASE64" > signature.base64

###############################################################################
# [3] AUTH / TOKEN / REDEEM
###############################################################################

echo "[3] POST /auth/token/redeem"

jq -n \
  --arg c "$CHALLENGE" \
  --arg s "$SIG_BASE64" \
  '{challenge:$c, signature:$s}' > redeem.json

curl -sS -X POST \
  --cert "$CERT_CRT" \
  --key "$CERT_KEY" \
  --pass "$CERT_PASS" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  --data @redeem.json \
  "$BASE_URL/auth/token/redeem" \
  -o token.json

jq . token.json

ACCESS_TOKEN=$(jq -r '.accessToken' token.json)

if [[ -z "$ACCESS_TOKEN" || "$ACCESS_TOKEN" == "null" ]]; then
  echo "BŁĄD: brak accessToken"
  exit 1
fi

###############################################################################
# [4] SESSION INIT
###############################################################################

echo "[4] POST /online/Session/Init"

curl -sS -X POST \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  "$BASE_URL/online/Session/Init" \
  -o session.json

jq . session.json

SESSION_ID=$(jq -r '.sessionId' session.json)

if [[ -z "$SESSION_ID" || "$SESSION_ID" == "null" ]]; then
  echo "BŁĄD: brak sessionId"
  exit 1
fi

echo "== SUKCES =="
echo "sessionId = $SESSION_ID"


#!/usr/bin/env bash
set -euo pipefail

echo "== KSeF 2.0 – AUTH ONLINE :: TEST B (OpenSSL CMS) =="

# -------------------------------------------------------------------
# KONFIGURACJA (jawna, bez magii)
# -------------------------------------------------------------------
CERT_CRT="Testowy_Odoo_18.crt"
CERT_KEY="Testowy_Odoo_18.key"
CERT_PASS_FILE="password.txt"

API_BASE="https://ksef-test.mf.gov.pl/api/v2"

# -------------------------------------------------------------------
# KROK 1: auth/challenge
# -------------------------------------------------------------------
echo "[1] POST /auth/challenge"

CHALLENGE_JSON=$(curl -s \
  --cert "$CERT_CRT" \
  --key "$CERT_KEY" \
  --pass "$(cat "$CERT_PASS_FILE")" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -X POST \
  "$API_BASE/auth/challenge"
)

echo "$CHALLENGE_JSON"

CHALLENGE=$(echo "$CHALLENGE_JSON" | sed -n 's/.*"challenge"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')

if [ -z "$CHALLENGE" ]; then
  echo "BŁĄD: nie udało się odczytać challenge"
  exit 1
fi

echo "challenge = $CHALLENGE"

# -------------------------------------------------------------------
# KROK 2: zapis challenge jako SUROWE BAJTY (bez newline!)
# -------------------------------------------------------------------
echo "[2] Zapis challenge.bin"
printf "%s" "$CHALLENGE" > challenge.bin
wc -c challenge.bin

# -------------------------------------------------------------------
# KROK 3: podpis CMS (OpenSSL, ECDSA, SignedData)
# -------------------------------------------------------------------
echo "[3] Podpis CMS (OpenSSL)"

openssl cms -sign \
  -binary \
  -in challenge.bin \
  -signer "$CERT_CRT" \
  -inkey "$CERT_KEY" \
  -passin file:"$CERT_PASS_FILE" \
  -outform DER \
  -out signature.der \
  -nosmimecap \
  -nodetach

wc -c signature.der

# -------------------------------------------------------------------
# KROK 4: DER -> base64 (jedna linia)
# -------------------------------------------------------------------
echo "[4] DER -> base64"

base64 -w 0 signature.der > signature.base64
wc -c signature.base64

# -------------------------------------------------------------------
# KROK 5: redeem.json
# -------------------------------------------------------------------
echo "[5] Budowa redeem.json"

cat > redeem.json <<EOF
{
  "challenge": "$CHALLENGE",
  "signature": "$(cat signature.base64)"
}
EOF

wc -c redeem.json

# -------------------------------------------------------------------
# KROK 6: auth/token/redeem
# -------------------------------------------------------------------
echo "[6] POST /auth/token/redeem"

curl -s -D headers.txt -o token.json \
  --cert "$CERT_CRT" \
  --key "$CERT_KEY" \
  --pass "$(cat "$CERT_PASS_FILE")" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -X POST \
  "$API_BASE/auth/token/redeem" \
  --data @redeem.json

echo
echo "== headers.txt =="
cat headers.txt
echo
echo "== token.json =="
cat token.json
echo
echo "== EOF =="


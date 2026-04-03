#!/bin/sh
set -e

###############################################################################
# STAŁE – ZGODNIE Z TWOIM WYMAGANIEM
###############################################################################
CERT_CRT="Testowy_Odoo_18.crt"
CERT_KEY="Testowy_Odoo_18.key"
CERT_PASS="$(cat password.txt)"

KSEF_BASE="https://ksef-test.mf.gov.pl/api/v2"

AUTH_XML="AuthTokenRequest.xml"
SIGNED_XML="AuthTokenRequest.signed.xml"

###############################################################################
# 1. ODCZYT NIP Z CERTYFIKATU
###############################################################################
echo "==> Odczyt NIP z certyfikatu"

SUBJECT="$(openssl x509 -in "$CERT_CRT" -noout -subject)"

# Preferowany wariant: VATPL-XXXXXXXXXX
NIP="$(echo "$SUBJECT" | sed -n 's/.*VATPL-\([0-9]\{10\}\).*/\1/p')"

# Fallback: organizationIdentifier
if [ -z "$NIP" ]; then
  NIP="$(openssl x509 -in "$CERT_CRT" -noout -text \
        | sed -n 's/.*organizationIdentifier: *VATPL-\([0-9]\{10\}\).*/\1/p')"
fi

if [ -z "$NIP" ]; then
  echo "BŁĄD: nie udało się odczytać NIP z certyfikatu"
  exit 1
fi

echo "NIP: $NIP"

###############################################################################
# 2. CHALLENGE
###############################################################################
echo "==> POST /auth/challenge"

CHALLENGE_JSON="$(curl -s -X POST "$KSEF_BASE/auth/challenge")"
CHALLENGE="$(echo "$CHALLENGE_JSON" | jq -r '.challenge')"

if [ -z "$CHALLENGE" ] || [ "$CHALLENGE" = "null" ]; then
  echo "BŁĄD: brak challenge"
  echo "$CHALLENGE_JSON"
  exit 1
fi

###############################################################################
# 3. BUDOWA AuthTokenRequest (XML)
###############################################################################
echo "==> Buduję AuthTokenRequest"

cat > "$AUTH_XML" <<EOF
<AuthTokenRequest xmlns="urn:ksef:auth:request">
  <Challenge>${CHALLENGE}</Challenge>
  <ContextIdentifier>
    <Type>nip</Type>
    <Value>${NIP}</Value>
  </ContextIdentifier>
  <SubjectIdentifierType>certificateSubject</SubjectIdentifierType>
</AuthTokenRequest>
EOF

###############################################################################
# 4. PODPIS XAdES (XMLDSig + XAdES-BES)
###############################################################################
echo "==> Podpis XAdES"

xmlsec1 \
  --sign \
  --privkey-pem "$CERT_KEY","$CERT_CRT" \
  --pwd "$CERT_PASS" \
  --output "$SIGNED_XML" \
  --node-xpath "/*" \
  "$AUTH_XML"

###############################################################################
# 5. WYSYŁKA /auth/xades-signature
###############################################################################
echo "==> POST /auth/xades-signature"

RESP_JSON="$(curl -s -X POST "$KSEF_BASE/auth/xades-signature" \
  -H "Content-Type: application/xml" \
  --data-binary @"$SIGNED_XML")"

REFERENCE_NUMBER="$(echo "$RESP_JSON" | jq -r '.referenceNumber')"
AUTH_TOKEN="$(echo "$RESP_JSON" | jq -r '.authenticationToken.token')"

if [ -z "$REFERENCE_NUMBER" ] || [ "$REFERENCE_NUMBER" = "null" ]; then
  echo "BŁĄD: brak referenceNumber"
  echo "$RESP_JSON"
  exit 1
fi

echo "referenceNumber: $REFERENCE_NUMBER"

###############################################################################
# 6. POLLING STATUSU
###############################################################################
echo "==> Polling statusu"

while true; do
  STATUS_JSON="$(curl -s -X GET "$KSEF_BASE/auth/$REFERENCE_NUMBER" \
    -H "Authorization: Bearer $AUTH_TOKEN")"

  STATUS_CODE="$(echo "$STATUS_JSON" | jq -r '.status.code')"

  echo "status: $STATUS_CODE"

  if [ "$STATUS_CODE" = "FINISHED_SUCCESS" ]; then
    break
  fi

  if [ "$STATUS_CODE" != "IN_PROGRESS" ]; then
    echo "BŁĄD uwierzytelnienia:"
    echo "$STATUS_JSON"
    exit 1
  fi

  sleep 2
done

###############################################################################
# 7. TOKEN REDEEM
###############################################################################
echo "==> POST /auth/token/redeem"

TOKENS_JSON="$(curl -s -X POST "$KSEF_BASE/auth/token/redeem" \
  -H "Authorization: Bearer $AUTH_TOKEN")"

ACCESS_TOKEN="$(echo "$TOKENS_JSON" | jq -r '.accessToken.token')"
REFRESH_TOKEN="$(echo "$TOKENS_JSON" | jq -r '.refreshToken.token')"

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
  echo "BŁĄD redeem"
  echo "$TOKENS_JSON"
  exit 1
fi

echo "==> SUKCES"
echo "accessToken: OK"
echo "refreshToken: OK"


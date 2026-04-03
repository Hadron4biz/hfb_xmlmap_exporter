#!/usr/bin/env python3
import sys
import base64
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    Encoding,
)
from cryptography.hazmat.primitives.serialization import pkcs7


CERT_CRT = "Testowy_Odoo_18.crt"
CERT_KEY = "Testowy_Odoo_18.key"
CERT_PASS = open("password.txt", "rb").read().strip()


def main():
    if len(sys.argv) != 2:
        print("Usage: cms_sign_challenge.py <challenge>", file=sys.stderr)
        sys.exit(1)

    challenge = sys.argv[1]
    data = challenge.encode("utf-8")

    # Wczytanie klucza EC
    with open(CERT_KEY, "rb") as f:
        key = load_pem_private_key(f.read(), password=CERT_PASS)

    # Wczytanie certyfikatu
    with open(CERT_CRT, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())

    # Budowa CMS / PKCS#7
    builder = pkcs7.PKCS7SignatureBuilder().set_data(data)
    builder = builder.add_signer(
        cert,
        key,
        hashes.SHA256(),
    )

    cms_der = builder.sign(
        encoding=Encoding.DER,
        options=[
            pkcs7.PKCS7Options.Binary,
        ],
    )

    # artefakty (do audytu)
    with open("signature.der", "wb") as f:
        f.write(cms_der)

    sig_b64 = base64.b64encode(cms_der).decode("ascii")

    with open("signature.base64", "w") as f:
        f.write(sig_b64)

    # stdout – tylko podpis
    print(sig_b64)


if __name__ == "__main__":
    main()


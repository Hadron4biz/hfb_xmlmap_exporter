import requests
import tempfile
import os
import base64
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.backends import default_backend


BASE_URL = "https://ksef-test.mf.gov.pl/api/v2"


def _tmp_file(content: bytes, suffix: str) -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content)
    f.close()
    return f.name


def _unencrypt_private_key(key_pem: str, password: str) -> str:
    key = serialization.load_pem_private_key(
        key_pem.encode(),
        password=password.encode(),
        backend=default_backend(),
    )
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return _tmp_file(pem, ".key")


def _encrypt_aes_key(mf_public_key_pem: str, aes_key: bytes) -> str:
    mf_key = load_pem_public_key(mf_public_key_pem.encode(), backend=default_backend())
    encrypted = mf_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode()


def open_ksef_session(
    cert_pem: str,
    key_pem: str,
    key_password: str,
    mf_public_key_pem: str,
    sign_challenge,  # funkcja: challenge -> signedChallenge (XAdES)
):
    # --- cert + key (bez hasła) ---
    cert_file = _tmp_file(cert_pem.encode(), ".crt")
    key_file = _unencrypt_private_key(key_pem, key_password)

    # --- A1: challenge ---
    r = requests.post(f"{BASE_URL}/auth/challenge", cert=(cert_file, key_file))
    r.raise_for_status()
    challenge = r.json()["challenge"]

    # --- A2: podpis ---
    signed = sign_challenge(challenge)

    # --- A3: redeem ---
    r = requests.post(
        f"{BASE_URL}/auth/token/redeem",
        json={"signedChallenge": signed},
    )
    r.raise_for_status()
    bearer = r.json()["accessToken"]

    # --- A4: open session ---
    aes_key = os.urandom(32)
    iv = os.urandom(16)

    payload = {
        "formCode": {
            "systemCode": "FA (3)",
            "schemaVersion": "1-0E",
            "value": "FA",
        },
        "encryption": {
            "encryptedSymmetricKey": _encrypt_aes_key(mf_public_key_pem, aes_key),
            "initializationVector": base64.b64encode(iv).decode(),
        },
    }

    r = requests.post(
        f"{BASE_URL}/sessions/online",
        headers={"Authorization": f"Bearer {bearer}"},
        json=payload,
    )
    r.raise_for_status()
    ref = r.json()["referenceNumber"]

    # --- A5: close ---
    requests.post(
        f"{BASE_URL}/sessions/online/{ref}/close",
        headers={"Authorization": f"Bearer {bearer}"},
    )

    return ref


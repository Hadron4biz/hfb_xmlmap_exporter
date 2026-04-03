import requests
import time
from typing import Tuple
from lxml import etree


# certyfikat do PODPISU (XAdES)
SIGN_CERT_CRT = "Hadro_Odoo_18_podpisy.crt"
SIGN_CERT_KEY = "Hadro_Odoo_18_podpisy.key"
SIGN_CERT_PASS_FILE = "password.txt"

# certyfikat do UWIERZYTELNIENIA / mTLS
TLS_CERT_CRT = "Testowy_Odoo_18.crt"
TLS_CERT_KEY = "Testowy_Odoo_18.key"

KSEF_BASE_URL = "https://ksef-test.mf.gov.pl/api/v2"


class KSeFAuthClient:
    def __init__(self):
        self.session = requests.Session()
        # mTLS – WYMAGANE, zgodnie z dokumentacją i klientem Java
        self.session.cert = (TLS_CERT_CRT, TLS_CERT_KEY)

    # ------------------------------------------------------------------
    # 1. Pobierz challenge
    # ------------------------------------------------------------------
    def get_challenge(self) -> Tuple[str, int]:
        url = f"{KSEF_BASE_URL}/auth/challenge"
        resp = self.session.post(url)
        resp.raise_for_status()

        data = resp.json()
        return data["challenge"], data["timestamp"]

    # ------------------------------------------------------------------
    # 2. Zbuduj AuthTokenRequest (XML)
    # ------------------------------------------------------------------
    def build_auth_token_request(
        self,
        challenge: str,
        nip: str,
        subject_identifier_type: str = "certificateSubject",
    ) -> etree._Element:
        NS = "http://ksef.mf.gov.pl/auth/token/2.0"

        root = etree.Element(
            "{%s}AuthTokenRequest" % NS,
            nsmap={None: NS},
        )

        etree.SubElement(root, "Challenge").text = challenge

        ctx = etree.SubElement(root, "ContextIdentifier")
        etree.SubElement(ctx, "Type").text = "nip"
        etree.SubElement(ctx, "Value").text = nip

        etree.SubElement(root, "SubjectIdentifierType").text = (
            subject_identifier_type
        )

        return root

    # ------------------------------------------------------------------
    # 3. Podpisz XML w XAdES
    # ------------------------------------------------------------------
    def sign_auth_token_request_xades(
        self,
        xml_root: etree._Element,
    ) -> bytes:
        """
        TU JEST JEDYNY NIEBANALNY KROK.

        Ta metoda MUSI:
        - dodać ds:Signature
        - dodać XAdES SignedProperties
        - podpisać CAŁY dokument
        - użyć:
            SIGN_CERT_CRT
            SIGN_CERT_KEY
            hasła z password.txt

        Implementacja = odpowiednik kodu Java.
        """
        raise NotImplementedError(
            "XAdES signing must be implemented here (no PKCS#7!)"
        )

    # ------------------------------------------------------------------
    # 4. Wyślij podpisany XML do /auth/xades-signature
    # ------------------------------------------------------------------
    def submit_xades_signature(
        self,
        signed_xml: bytes,
    ) -> Tuple[str, str]:
        url = f"{KSEF_BASE_URL}/auth/xades-signature"

        headers = {"Content-Type": "application/xml"}
        resp = self.session.post(url, data=signed_xml, headers=headers)
        resp.raise_for_status()

        data = resp.json()
        return data["referenceNumber"], data["authenticationToken"]["token"]

    # ------------------------------------------------------------------
    # 5. Polling statusu
    # ------------------------------------------------------------------
    def wait_for_auth_status(
        self,
        reference_number: str,
        authentication_token: str,
        poll_interval: int = 2,
    ) -> None:
        url = f"{KSEF_BASE_URL}/auth/{reference_number}"
        headers = {"Authorization": f"Bearer {authentication_token}"}

        while True:
            resp = self.session.get(url, headers=headers)
            resp.raise_for_status()

            status = resp.json()["status"]["code"]

            if status == "FINISHED_SUCCESS":
                return

            if status != "IN_PROGRESS":
                raise RuntimeError(f"Authentication failed: {resp.json()}")

            time.sleep(poll_interval)

    # ------------------------------------------------------------------
    # 6. Redeem tokenów
    # ------------------------------------------------------------------
    def redeem_tokens(
        self,
        authentication_token: str,
    ) -> Tuple[str, str]:
        url = f"{KSEF_BASE_URL}/auth/token/redeem"
        headers = {"Authorization": f"Bearer {authentication_token}"}

        resp = self.session.post(url, headers=headers)
        resp.raise_for_status()

        data = resp.json()
        return data["accessToken"]["token"], data["refreshToken"]["token"]


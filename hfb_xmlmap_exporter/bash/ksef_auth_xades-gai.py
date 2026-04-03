import requests
import time
from typing import Tuple
from lxml import etree
# Zmień importy na poprawne dla najnowszej wersji signxml:
from signxml import methods
from signxml.xades import XAdESSigner

# Zakładamy, że te zmienne globalne są zdefiniowane gdzie indziej
KSEF_BASE_URL = "ksef-test.mf.gov.pl" # Przykład URL testowego
TLS_CERT_CRT = "/path/to/your/tls_cert.pem"
TLS_CERT_KEY = "/path/to/your/tls_key.pem"
SIGN_CERT_CRT = open("/path/to/your/sign_cert.pem", "rb").read() # Wczytane bajty certyfikatu
SIGN_CERT_KEY = open("/path/to/your/sign_key.pem", "rb").read() # Wczytane bajty klucza prywatnego


class KSeFAuthClient:
    def __init__(self):
        self.session = requests.Session()
        # mTLS – WYMAGANE, zgodnie z dokumentacją i klientem Java
        self.session.cert = (TLS_CERT_CRT, TLS_CERT_KEY)

    # ... (metody 1 i 2 bez zmian) ...
    def get_challenge(self) -> Tuple[str, int]:
        url = f"{KSEF_BASE_URL}/auth/challenge"
        resp = self.session.post(url)
        resp.raise_for_status()
        data = resp.json()
        return data["challenge"], data["timestamp"]

    def build_auth_token_request(
        self,
        challenge: str,
        nip: str,
        subject_identifier_type: str = "certificateSubject",
    ) -> etree._Element:
        NS = "ksef.mf.gov.pl"
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
    # 3. Podpisz XML w XAdES (Implementacja)
    # ------------------------------------------------------------------
    def sign_auth_token_request_xades(
        self,
        xml_root: etree._Element,
    ) -> bytes:
        """
        Implementacja podpisu XAdES-BES przy użyciu signxml.xades.XAdESSigner
        """
        
        # Używamy XAdESSigner bezpośrednio. 
        # KSeF wymaga konkretnych algorytmów (SHA-256 dla digestu i podpisu RSA)
        signer = XAdESSigner(
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
            # XAdES_BES to domyślny poziom, ale można go jawnie określić
            # policy=XAdESSignaturePolicy(...) <-- opcjonalnie, jeśli KSeF wymaga konkretnej polityki podpisu
        )

        # Wymagane jest dodanie certyfikatu do sekcji KeyInfo
        signer.signing_cert = SIGN_CERT_CRT 
        
        # Podpisanie dokumentu XML
        signed_root = signer.sign(
            xml_root,
            key=SIGN_CERT_KEY,
            # KSeF zazwyczaj wymaga podpisu "enveloped" (owiniętego wewnątrz dokumentu)
            # Lub "detached" jeśli podpis jest w osobnym pliku, 
            # ale w tym workflow jest on częścią POST payloadu XML.
            method=methods.enveloped 
        )

        # Serializacja do bajtów (string XML)
        # Upewnij się, że kodowanie to utf-8
        return etree.tostring(signed_root, pretty_print=True, encoding='utf-8')

    # ... (metody 4, 5 i 6 bez zmian) ...
    def submit_xades_signature(self, signed_xml: bytes) -> Tuple[str, str]:
        url = f"{KSEF_BASE_URL}/auth/xades-signature"
        headers = {"Content-Type": "application/xml"}
        resp = self.session.post(url, data=signed_xml, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["referenceNumber"], data["authenticationToken"]["token"]
    
    def wait_for_auth_status(self, reference_number: str, authentication_token: str, poll_interval: int = 2) -> None:
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

    def redeem_tokens(self, authentication_token: str) -> Tuple[str, str]:
        url = f"{KSEF_BASE_URL}/auth/token/redeem"
        headers = {"Authorization": f"Bearer {authentication_token}"}
        resp = self.session.post(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["accessToken"]["token"], data["refreshToken"]["token"]


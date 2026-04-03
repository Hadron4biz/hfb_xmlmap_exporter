"""
KSeF API Client v2.0 - Python implementation
Kompatybilny z istniejącymi Java JAR (ksef-*.jar)

UŻYCIE:
    input_json = json.dumps({
        "operation": "open_session",
        "config": {...},
        "context": {...},
        "params": {...}
    })
    
    # Tak samo jak Java JAR!
    output_json = KSeFClient.process_input(input_json)
"""

import json
import requests
import base64
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

_logger = logging.getLogger(__name__)


@dataclass
class KSeFConfig:
    """Konfiguracja z Odoo - identyczna z Java input"""
    environment: str  # 'test' | 'production'
    auth_type: str    # 'jet_token' | 'certificate'
    company_nip: str
    mf_certificate_pem: Optional[str] = None
    jar_directory: Optional[str] = None
    # ... inne pola z OdooConfig w Main.java


class KSeFResponse:
    """Response format IDENTYCZNY z Java output"""
    
    def __init__(self, success: bool = True):
        self.success = success
        self.error: Optional[str] = None
        self.data: Dict[str, Any] = {}
        self.context: Dict[str, Any] = {}
        self.duration_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "error": self.error,
            "data": self.data,
            "context": self.context,
            "duration_ms": self.duration_ms,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class KSeFClient:
    """Główna klasa - odpowiednik Java JAR"""
    
    @staticmethod
    def process_input(input_json: str) -> str:
        """
        Główna metoda - odpowiednik Java main().
        Przyjmuje JSON, zwraca JSON - TAK SAMO JAK JAR.
        """
        import time
        start_time = time.time()
        response = KSeFResponse()
        
        try:
            # 1. Parsuj input (identycznie jak Java)
            input_data = json.loads(input_json)
            operation = input_data.get("operation")
            config_data = input_data.get("config", {})
            context = input_data.get("context", {})
            params = input_data.get("params", {})
            
            _logger.info(f"Processing operation: {operation}")
            
            # 2. Przygotuj konfigurację
            config = KSeFConfig(**config_data)
            
            # 3. Wywołaj odpowiednią operację
            if operation == "auth":
                result = KSeFClient._handle_auth(config, context)
            elif operation == "open_session":
                result = KSeFClient._handle_open_session(config, context)
            elif operation == "send_invoice":
                result = KSeFClient._handle_send_invoice(config, context, params)
            elif operation == "check_status":
                result = KSeFClient._handle_check_status(config, context, params)
            elif operation == "download_upo":
                result = KSeFClient._handle_download_upo(config, context, params)
            elif operation == "close_session":
                result = KSeFClient._handle_close_session(config, context)
            elif operation == "import_invoices":
                result = KSeFClient._handle_import_invoices(config, context, params)
            else:
                raise ValueError(f"Unknown operation: {operation}")
            
            # 4. Uzupełnij response
            response.data = result.get("data", {})
            response.context = result.get("context", {})
            response.success = result.get("success", True)
            
        except Exception as e:
            response.success = False
            response.error = str(e)
            _logger.error(f"Error processing KSeF operation: {e}")
        
        # 5. Oblicz czas wykonania
        response.duration_ms = int((time.time() - start_time) * 1000)
        
        return response.to_json()
    
    # ============ TU WYPEŁNISZ ENDPOINTY v2.0 ============
    
    @staticmethod
    def _handle_auth(config: KSeFConfig, context: Dict) -> Dict[str, Any]:
        """
        AUTORYZACJA - TYLKO Java (XAdES signing)
        Ta metoda NIE powinna być wywoływana w Pythonie.
        """
        raise NotImplementedError(
            "Auth operation must be handled by Java (ksef-auth.jar) "
            "because of XAdES signing requirements."
        )
    
    @staticmethod
    def _handle_open_session(config: KSeFConfig, context: Dict) -> Dict[str, Any]:
        """
        OPEN SESSION - v2.0 endpoint
        TODO: Wypełnij właściwym endpointem KSeF v2.0
        """
        # PRZYKŁAD - DO POPRAWY:
        # Masz token z poprzedniej autoryzacji (z Java)
        auth_token = context.get("tokens", {}).get("accessToken")
        
        if not auth_token:
            raise ValueError("Missing auth token for open_session")
        
        # TU WPISZ WŁAŚCIWY ENDPOINT v2.0
        base_url = KSeFClient._get_base_url(config.environment)
        url = f"{base_url}/v2/online/Session/Init"  # ❌ TO JEST PRZYKŁAD
        
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {auth_token}"},
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        
        return {
            "success": True,
            "data": {
                "sessionToken": data.get("sessionToken"),
                "referenceNumber": data.get("referenceNumber"),
                "sessionId": data.get("sessionId"),
            },
            "context": {
                "session": data,
                "runtime": {
                    "baseUrl": base_url,
                    "integrationMode": config.environment.upper(),
                }
            }
        }
    
    @staticmethod
    def _handle_send_invoice(config: KSeFConfig, context: Dict, params: Dict) -> Dict[str, Any]:
        """
        SEND INVOICE - v2.0 endpoint
        TODO: Wypełnij właściwym endpointem
        """
        session_token = context.get("session", {}).get("sessionToken")
        if not session_token:
            raise ValueError("Missing session token")
        
        invoice_xml = params.get("invoice_xml")
        if not invoice_xml:
            raise ValueError("Missing invoice XML")
        
        # TU WPISZ WŁAŚCIWY ENDPOINT v2.0
        base_url = KSeFClient._get_base_url(config.environment)
        url = f"{base_url}/v2/online/Invoice/Send"  # ❌ TO JEST PRZYKŁAD
        
        # TU WPISZ WŁAŚCIWE HEADERY v2.0
        headers = {
            "SessionToken": session_token,
            "Accept": "application/json",
        }
        
        # Multipart upload
        files = {"file": ("invoice.xml", invoice_xml, "application/xml")}
        
        response = requests.post(url, headers=headers, files=files, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        
        return {
            "success": True,
            "data": {
                "referenceNumber": data.get("elementReferenceNumber"),
                "invoiceNumber": data.get("invoiceNumber"),
                "processingCode": data.get("processingCode"),
                "processingDescription": data.get("processingDescription"),
            }
        }
    
    @staticmethod
    def _handle_check_status(config: KSeFConfig, context: Dict, params: Dict) -> Dict[str, Any]:
        """
        CHECK STATUS - v2.0 endpoint
        TODO: Wypełnij właściwym endpointem
        """
        # ... podobna struktura
        pass
    
    @staticmethod
    def _handle_download_upo(config: KSeFConfig, context: Dict, params: Dict) -> Dict[str, Any]:
        """
        DOWNLOAD UPO - v2.0 endpoint  
        TODO: Wypełnij właściwym endpointem
        """
        pass
    
    @staticmethod
    def _handle_close_session(config: KSeFConfig, context: Dict) -> Dict[str, Any]:
        """
        CLOSE SESSION - v2.0 endpoint
        TODO: Wypełnij właściwym endpointem
        """
        pass
    
    @staticmethod
    def _handle_import_invoices(config: KSeFConfig, context: Dict, params: Dict) -> Dict[str, Any]:
        """
        IMPORT INVOICES - v2.0 endpoint
        TODO: Wypełnij właściwym endpointem
        """
        pass
    
    # ============ POMOCNICZE ============
    
    @staticmethod
    def _get_base_url(environment: str) -> str:
        """Zwraca base URL dla środowiska"""
        if environment == "test":
            return "https://ksef-test.mf.gov.pl/api"
        return "https://ksef.mf.gov.pl/api"
    
    @staticmethod
    def _make_ksef_request(method: str, url: str, **kwargs) -> requests.Response:
        """
        Unified request handler dla KSeF API.
        Możesz dodać retry logic, error handling, etc.
        """
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            _logger.error(f"KSeF API request failed: {e}")
            raise


# ============ INTERFEJS KOMENDY ============

if __name__ == "__main__":
    """
    Uruchomienie jako standalone (tak jak Java JAR).
    Czyta JSON z stdin, zwraca JSON na stdout.
    """
    import sys
    
    # Wczytaj cały stdin
    input_json = sys.stdin.read()
    
    if not input_json:
        print(json.dumps({
            "success": False,
            "error": "No input provided",
            "duration_ms": 0
        }))
        sys.exit(1)
    
    try:
        # Przetwórz
        output_json = KSeFClient.process_input(input_json)
        
        # Wyślij na stdout
        print(output_json)
        
        # Exit code based on success
        result = json.loads(output_json)
        if result.get("success"):
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"Fatal error: {str(e)}",
            "duration_ms": 0
        }))
        sys.exit(1)

#EoF

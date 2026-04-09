# -*- coding: utf-8 -*-
"""
KSeF API v2.0 HTTP Client
Czysty Python client dla KSeF API v2.0 - bez zależności od Odoo/Java
"""

import json
import requests
import base64
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import time

_logger = logging.getLogger(__name__)


# ============ DATA MODELS ============

@dataclass
class KSeFSession:
	"""Model sesji KSeF"""
	reference_number: str  # np. "20251231-SO-1CBDD93000-2F1E8C4A4B-42"
	valid_until: str	  # ISO timestamp
	# Uwaga: W v2.0 NIE MA sessionToken w response! Tylko referenceNumber


@dataclass
class KSeFTokens:
	"""Tokeny autoryzacyjne"""
	access_token: str
	access_token_valid_until: str
	refresh_token: str
	refresh_token_valid_until: str


@dataclass
class KSeFInvoiceResponse:
	"""Odpowiedź po wysłaniu faktury"""
	reference_number: str	  # np. "20251231-EE-1CC28D6000-61752794B9-AB"
	http_status: int		   # 202 Accepted
	timestamp: str = ""


@dataclass
class KSeFSessionStatus:
	"""Status sesji"""
	code: int				  # 200 = sukces, 445 = błąd
	description: str
	date_created: str
	date_updated: str
	valid_until: str
	invoice_count: int = 0
	successful_invoice_count: int = 0
	failed_invoice_count: int = 0


@dataclass
class KSeFUPOPage:
	"""Strona UPO"""
	reference_number: str	  # np. "20251231-EU-1CCCC0B000-617EE08514-6C"
	download_url: str		  # signed URL
	download_url_expiration_date: str


@dataclass
class KSeFUPOResponse:
	"""Pełna odpowiedź UPO"""
	pages: list[KSeFUPOPage]
	session_reference: str
	status_code: int
	status_description: str


@dataclass
class KSeFDownloadedUPO:
	"""Pobrane UPO"""
	content: bytes
	filename: str
	reference_number: str
	session_reference: str
	file_size: int
	sha256_hash: str = ""
	content_type: str = "application/xml"


# ============ MAIN CLIENT ============

class KSeFV2Client:
	"""
	Czysty HTTP client dla KSeF API v2.0.
	Niezależny od Odoo/Java - można używać standalone.
	"""
	
	def __init__(
		self,
		environment: str = "test",
		timeout: int = 30,
		verify_ssl: bool = True
	):
		"""
		Initialize KSeF v2.0 client.
		
		Args:
			environment: 'test' lub 'production'
			timeout: Timeout w sekundach
			verify_ssl: Weryfikuj certyfikaty SSL
		"""
		self.environment = environment
		self.timeout = timeout
		self.verify_ssl = verify_ssl
		self.base_url = self._get_base_url()
		
		# Session dla connection pooling
		self.session = requests.Session()
		self.session.headers.update({
			"Accept": "application/json",
			"User-Agent": f"KSeFV2PythonClient/1.0 ({environment})",
		})
		
		# Debug mode
		self.debug = False
	
	def _get_base_url(self) -> str:
		"""Get base URL for environment."""
		if self.environment == "test":
			return "https://ksef-test.mf.gov.pl/api/v2"
		return "https://ksef.mf.gov.pl/api/v2"
	
	def _log_request(self, method: str, url: str, headers: dict, data: Any = None):
		"""Log request for debugging."""
		if self.debug:
			_logger.debug(f"[KSeF] {method} {url}")
			_logger.debug(f"Headers: {json.dumps(headers, indent=2)}")
			if data and isinstance(data, dict):
				_logger.debug(f"Data: {json.dumps(data, indent=2)}")
	
	def _log_response(self, response: requests.Response):
		"""Log response for debugging."""
		if self.debug:
			_logger.debug(f"[KSeF] Response: {response.status_code}")
			if response.text:
				try:
					_logger.debug(f"Body: {json.dumps(response.json(), indent=2)}")
				except:
					_logger.debug(f"Body: {response.text[:500]}...")
	
	def _make_request(
		self,
		method: str,
		endpoint: str,
		headers: Optional[Dict[str, str]] = None,
		data: Any = None,
		files: Optional[Dict] = None,
		params: Optional[Dict] = None
	) -> requests.Response:
		"""
		Unified request handler with error handling.
		
		Returns:
			requests.Response
			
		Raises:
			KSeFAPIError: For API errors
			requests.RequestException: For network errors
		"""
		url = f"{self.base_url}{endpoint}"
		
		# Merge headers
		request_headers = self.session.headers.copy()
		if headers:
			request_headers.update(headers)
		
		# Log request
		self._log_request(method, url, request_headers, data)
		
		try:
			start_time = time.time()
			
			response = self.session.request(
				method=method,
				url=url,
				headers=request_headers,
				json=data if method in ["POST", "PUT", "PATCH"] and not files else None,
				data=data if method in ["POST", "PUT", "PATCH"] and files else None,
				files=files,
				params=params,
				timeout=self.timeout,
				verify=self.verify_ssl
			)
			
			duration_ms = int((time.time() - start_time) * 1000)
			
			# Log response
			self._log_response(response)
			_logger.info(f"[KSeF] {method} {endpoint} -> {response.status_code} ({duration_ms}ms)")
			
			# Check for HTTP errors
			if response.status_code >= 400:
				error_msg = self._extract_error_message(response)
				raise KSeFAPIError(
					f"HTTP {response.status_code}: {error_msg}",
					status_code=response.status_code,
					response=response
				)
			
			return response
			
		except requests.exceptions.Timeout:
			_logger.error(f"[KSeF] Timeout after {self.timeout}s: {method} {endpoint}")
			raise KSeFAPIError(f"Timeout after {self.timeout} seconds")
		except requests.exceptions.RequestException as e:
			_logger.error(f"[KSeF] Request failed: {e}")
			raise KSeFAPIError(f"Network error: {str(e)}")
	
	def _extract_error_message(self, response: requests.Response) -> str:
		"""Extract error message from response."""
		try:
			error_data = response.json()
			if isinstance(error_data, dict):
				# Try common error fields
				for field in ["error", "message", "description", "details"]:
					if field in error_data:
						return str(error_data[field])
				# Return entire JSON if no specific field
				return json.dumps(error_data)
		except:
			pass
		
		# Fallback to status text or raw text
		return response.reason or response.text[:200] or "Unknown error"
	
	# ============ PUBLIC API METHODS ============
	
	def open_session(self, auth_token: str) -> Tuple[KSeFSession, Dict[str, Any]]:
		"""
		Otwórz sesję w KSeF.
		
		Args:
			auth_token: Token JWT z autoryzacji (XAdES) - BEARER token
			
		Returns:
			Tuple[KSeFSession, full_response_dict]
			
		Note:
			Używa Authorization: Bearer {auth_token}
			Zwraca session_reference które jest jednocześnie SessionToken
		"""
		endpoint = "/online/Session/Init"
		
		headers = {
			"Authorization": f"Bearer {auth_token}",  # BEARER dla otwarcia
			"Content-Type": "application/json",
		}
		
		response = self._make_request("POST", endpoint, headers=headers)
		
		response_data = response.json()
		
		# W v2.0: session_reference JEST SessionToken!
		session = KSeFSession(
			reference_number=response_data.get("referenceNumber"),
			valid_until=response_data.get("validUntil")
		)
		
		return session, response_data

	def send_invoice(
		self,
		session_reference: str,  # TO JEST SessionToken!
		invoice_xml: str,
		invoice_number: Optional[str] = None
	) -> Tuple[KSeFInvoiceResponse, Dict[str, Any]]:
		"""
		Wyślij fakturę do KSeF.
		
		Args:
			session_reference: Numer referencyjny sesji = SessionToken
			invoice_xml: XML faktury
			invoice_number: Opcjonalny numer faktury
			
		Returns:
			Tuple[KSeFInvoiceResponse, full_response_dict]
		"""
		endpoint = "/online/Invoice/Send"
		
		headers = {
			"SessionToken": session_reference,  # SessionToken header!
			"Accept": "application/json",
		}
		
		if invoice_number:
			headers["InvoiceNumber"] = invoice_number
		
		files = {"file": ("invoice.xml", invoice_xml, "application/xml")}
		
		response = self._make_request("POST", endpoint, headers=headers, files=files)
		
		response_data = response.json() if response.text else {}
		
		invoice_response = KSeFInvoiceResponse(
			reference_number=response_data.get("referenceNumber"),
			http_status=response.status_code,
			timestamp=datetime.now().isoformat()
		)
		
		return invoice_response, response_data
	
	
	def check_session_status(self, session_reference: str) -> Tuple[KSeFSessionStatus, Dict[str, Any]]:
		"""
		Sprawdź status sesji.
		
		Args:
			session_reference: Numer sesji = SessionToken
			
		Returns:
			Tuple[KSeFSessionStatus, full_response_dict]
		"""
		endpoint = f"/sessions/{session_reference}"  # session_reference w URL!
		
		headers = {
			"SessionToken": session_reference,  # I w headerze!
			"Accept": "application/json",
		}
		
		response = self._make_request("GET", endpoint, headers=headers)
		
		response_data = response.json()
		
		# Extract status
		status_data = response_data.get("status", {})
		
		status = KSeFSessionStatus(
			code=status_data.get("code"),
			description=status_data.get("description"),
			date_created=response_data.get("dateCreated"),
			date_updated=response_data.get("dateUpdated"),
			valid_until=response_data.get("validUntil"),
			invoice_count=response_data.get("invoiceCount", 0),
			successful_invoice_count=response_data.get("successfulInvoiceCount", 0),
			failed_invoice_count=response_data.get("failedInvoiceCount", 0),
		)
		
		return status, response_data
	
	def download_upo(
		self,
		download_url: str,
		session_reference: str,
		upo_reference: str
	) -> KSeFDownloadedUPO:
		"""
		Pobierz UPO z signed URL.
		
		Args:
			download_url: Signed URL z check_session_status
			session_reference: Numer sesji (dla nazwy pliku)
			upo_reference: Numer referencyjny UPO
			
		Returns:
			KSeFDownloadedUPO
		"""
		_logger.info(f"[KSeF] Downloading UPO: {upo_reference}")
		
		# Używamy bezpośrednio signed URL (nie API endpoint)
		response = requests.get(
			download_url,
			timeout=self.timeout,
			verify=self.verify_ssl
		)
		
		if response.status_code != 200:
			raise KSeFAPIError(f"Failed to download UPO: HTTP {response.status_code}")
		
		content = response.content
		content_type = response.headers.get("Content-Type", "application/xml")
		
		# Generate filename
		filename = f"UPO_{session_reference}.xml"
		
		# Calculate SHA256 hash
		import hashlib
		sha256_hash = base64.b64encode(
			hashlib.sha256(content).digest()
		).decode("ascii")
		
		return KSeFDownloadedUPO(
			content=content,
			filename=filename,
			reference_number=upo_reference,
			session_reference=session_reference,
			file_size=len(content),
			sha256_hash=sha256_hash,
			content_type=content_type
		)
	

	def close_session(self, session_reference: str) -> Tuple[bool, Dict[str, Any]]:
		"""
		Zamknij sesję.
		
		Args:
			session_reference: Numer sesji = SessionToken
			
		Returns:
			Tuple[success, full_response_dict]
		"""
		endpoint = f"/sessions/{session_reference}"
		
		headers = {
			"SessionToken": session_reference,
			"Accept": "application/json",
		}
		
		response = self._make_request("DELETE", endpoint, headers=headers)
		
		# 204 No Content oznacza sukces
		success = response.status_code == 204
		
		response_data = {}
		if response.text:
			response_data = response.json()
		
		return success, response_data
	
	# ============ HELPER METHODS ============
	
	def validate_session_reference(self, session_ref: str) -> bool:
		"""Validate session reference format."""
		# Format: YYYYMMDD-SO-XXXXXXXXXX-XXXXXXXXXX-XX
		import re
		pattern = r'^\d{8}-SO-[A-Z0-9]{10}-[A-Z0-9]{10}-[A-Z0-9]{2}$'
		return bool(re.match(pattern, session_ref))
	
	def is_token_expired(self, valid_until: str) -> bool:
		"""Check if token is expired."""
		try:
			expiry = datetime.fromisoformat(valid_until.replace('Z', '+00:00'))
			return datetime.now(expiry.tzinfo) >= expiry - timedelta(minutes=5)
		except:
			return True  # Jeśli nie można parsować, uznaj jako expired
	
	def get_upo_pages(self, session_status_response: Dict[str, Any]) -> list[KSeFUPOPage]:
		"""Extract UPO pages from session status response."""
		pages = []
		upo_data = session_status_response.get("upo", {})
		
		for page_data in upo_data.get("pages", []):
			page = KSeFUPOPage(
				reference_number=page_data.get("referenceNumber"),
				download_url=page_data.get("downloadUrl"),
				download_url_expiration_date=page_data.get("downloadUrlExpirationDate")
			)
			pages.append(page)
		
		return pages
	
	def is_upo_available(self, session_status: KSeFSessionStatus) -> bool:
		"""Check if UPO is available for download."""
		return session_status.code == 200 and session_status.successful_invoice_count > 0


# ============ EXCEPTIONS ============

class KSeFAPIError(Exception):
	"""Base exception for KSeF API errors."""
	
	def __init__(
		self,
		message: str,
		status_code: Optional[int] = None,
		response: Optional[requests.Response] = None
	):
		super().__init__(message)
		self.status_code = status_code
		self.response = response
		self.message = message
	
	def __str__(self):
		if self.status_code:
			return f"KSeFAPIError({self.status_code}): {self.message}"
		return f"KSeFAPIError: {self.message}"


class KSeFSessionError(KSeFAPIError):
	"""Session-related errors."""
	pass


class KSeFInvoiceError(KSeFAPIError):
	"""Invoice-related errors."""
	pass


class KSeFUPOError(KSeFAPIError):
	"""UPO-related errors."""
	pass


# ============ USAGE EXAMPLE ============

if __name__ == "__main__":
	"""Example usage - standalone testing."""
	import sys
	
	# Configure logging
	logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
	)
	
	# Example: Check session status
	if len(sys.argv) > 1 and sys.argv[1] == "test":
		client = KSeFV2Client(environment="test", debug=True)
		
		try:
			# Example session reference
			session_ref = "20251231-SO-1CBDD93000-2F1E8C4A4B-42"
			
			print(f"Checking session: {session_ref}")
			status, full_response = client.check_session_status(session_ref)
			
			print(f"Status: {status.code} - {status.description}")
			print(f"Invoice count: {status.invoice_count}")
			print(f"Successful: {status.successful_invoice_count}")
			
			if client.is_upo_available(status):
				print("UPO is available!")
				pages = client.get_upo_pages(full_response)
				for page in pages:
					print(f"  UPO Page: {page.reference_number}")
					print(f"  URL expires: {page.download_url_expiration_date}")
			
		except KSeFAPIError as e:
			print(f"Error: {e}")
			sys.exit(1)

#EoF

# -*- coding: utf-8 -*-
# vim: tabstop=4 softtabstop=0 shiftwidth=4 smarttab expandtab fileformat=unix
#################################################################################
#
# Odoo, Open ERP Source Management Solution
# Copyright (C) 2017-2026 Hadron for Business sp. z o.o. (http://hadronforbusiness.com)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#################################################################################
# UWAGA / NOTICE:
# "XET" oraz nazwa "Hadron for Business" są zastrzeżonymi znakami towarowymi
# "XET" and "Hadron for Business" are trademarks of Hadron for Business sp. z o.o.
#
# Sam kod jest objęty licencją AGPLv3, ale koncepcje, pomysły i rozwiązania
# biznesowe w nim zawarte nie są objęte tą licencją i pozostają własnością
# autora.
# The code is licensed under AGPLv3, but the concepts, ideas and business
# solutions contained herein are not covered by this license and remain the
# property of the author.
#################################################################################
"""@version 18.1.3
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
# ============================================================
# Standard library
# ============================================================

import base64
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
import json, ast
# ============================================================
# Third-party
# ============================================================

import requests
from lxml import etree

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.asymmetric import padding, ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import pkcs12

# Tymczasowe obejście komunikatów 
import warnings
from cryptography.utils import CryptographyDeprecationWarning
warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

# ============================================================
# Odoo
# ============================================================

from odoo import fields
from odoo.exceptions import UserError

# ============================================================
# Module globals
# ============================================================

class TokenExpiredException(Exception):
	"""Wyrzucany gdy token wygasł ale refresh token jest ważny"""
	pass

_logger = logging.getLogger(__name__)
TIMEOUT = 10

class ProviderKsefApiService:
	"""
	Python-native backend komunikacji z KSeF.

	Runtime:
		- communication.log
	Konfiguracja:
		- communication.provider.ksef

	Brak współdzielenia z backendem Java.
	"""

	# ============================================================
	# KONSTRUKTOR
	# ============================================================

	def __init__(self, provider, log):
		self.provider = provider  # communication.provider.ksef
		self.log = log  # communication.log
		
		# Dane z logu (nie z company!)
		self.access_token = log.ksef_access_token
		self.refresh_token = log.ksef_refresh_token
		self.session_key = log.ksef_session_key  # już Binary
		self.session_iv = log.ksef_session_iv	 # już Binary
		
		# Konfiguracja z providera
		self.api_url = self._get_config_api_url()
		self.company_nip = provider.company_nip
		self.environment = provider.environment

	# ============================================================
	# POMOCNICZE
	# ============================================================

	def _parse_ksef_date(self, date_str):
		"""
		Parsuje datę z KSeF API do formatu Odoo (datetime bez timezone).
		
		KSeF zwraca daty w formacie ISO 8601 z mikrosekundami:
		- "2026-03-03T08:46:50.7046228+00:00"
		- "2026-03-03T08:46:50.7046228Z"
		- "2026-03-03T08:46:50+00:00"
		
		Args:
			date_str (str): Data w formacie KSeF lub None
			
		Returns:
			datetime or False: Dataparsed do formatu Odoo lub False jeśli błąd
		"""
		if not date_str or not isinstance(date_str, str):
			return False
		
		original = date_str
		try:
			# Krok 1: Usuń mikrosekundy (część po kropce)
			if '.' in date_str:
				date_str = date_str.split('.')[0]
			
			# Krok 2: Usuń strefę czasową (+00:00, +01:00, Z)
			if '+' in date_str:
				date_str = date_str.split('+')[0]
			elif 'Z' in date_str:
				date_str = date_str.replace('Z', '')
			
			# Krok 3: Zamień 'T' na spację (format Odoo)
			date_str = date_str.replace('T', ' ')
			
			# Krok 4: Sprawdź czy mamy poprawny format
			# Odoo oczekuje '%Y-%m-%d %H:%M:%S'
			if len(date_str.split()) == 2:
				date_part, time_part = date_str.split()
				# Upewnij się że czas ma sekundy
				if len(time_part.split(':')) == 2:
					time_part += ':00'
				date_str = f"{date_part} {time_part}"
			
			# Krok 5: Parsuj
			result = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
			
			_logger.debug(f"[KSeF] Parsed date: '{original}' -> '{result}'")
			return result
			
		except Exception as e:
			_logger.error(f"[KSeF] Failed to parse date '{original}': {e}")
			return False

	# ============================================================
	# =====================  PUBLIC FLOW  ========================
	# ============================================================

	# --------------------- AUTH ---------------------

	def auth(self):
		"""
		Pełna autoryzacja - pobiera nowe tokeny i ZAPISUJE JE W LOGU.
		Zgodnie z oficjalną implementacją KSeF.
		"""
		_logger.info(f"[KSeF][Python] Starting full authentication for log {self.log.id}")
		
		try:
			# 1. Pobierz challenge
			challenge_data = self._get_challenge()
			challenge = challenge_data.get('challenge')
			if not challenge:
				raise UserError("No challenge received from KSeF")
			
			# 2. Podpisz challenge (używa certyfikatów z providera)
			signer = ProviderXadesSigner(self.provider)
			signed_xml = signer.sign_authentication_challenge(
				challenge,
				self.provider.company_nip
			)
			
			# 3. Wyślij podpisany challenge
			endpoint = f"{self.api_url}/auth/xades-signature"
			headers = {
				'Content-Type': 'application/xml',
				'Accept': 'application/json'
			}
			
			response = requests.post(
				endpoint,
				data=signed_xml.encode('utf-8'),
				headers=headers,
				timeout=TIMEOUT
			)
			response.raise_for_status()
			
			# 4. Otrzymujemy referenceNumber i authenticationToken
			temp_data = response.json()
			_logger.info(f"[KSeF][Python] Auth step 1 response: {temp_data}")
			
			# Pobierz reference number (ID autoryzacji) i token tymczasowy
			reference_number = temp_data.get('referenceNumber')
			auth_token = temp_data.get('authenticationToken', {}).get('token')
			
			if not reference_number:
				raise UserError("No referenceNumber in KSeF response")
			if not auth_token:
				raise UserError("No authenticationToken in KSeF response")
			
			# 5. Sprawdź status autoryzacji (używając referenceNumber w URL i auth_token w nagłówku)
			auth_status = self._check_auth_status(reference_number, auth_token)
			
			# 6. Wymień tymczasowy token na stałe tokeny (redeem)
			tokens = self._redeem_token(auth_token)
			_logger.info(f"[KSeF][Python] Redeem response keys: {list(tokens.keys())}")
			
			# 7. BEZPIECZNIE zapisz tokeny
			update_vals = {
				'ksef_last_auth_datetime': fields.Datetime.now(),
				# Czyść stare dane sesji przy nowej autoryzacji
				'ksef_session_token': False,
				'ksef_session_key': False,
				'ksef_session_iv': False,
				'ksef_session_valid_until': False,
			}
			
			# Funkcja pomocnicza do konwersji daty z ISO na format Odoo
			def convert_ksef_date(date_str):
				"""Konwertuje datę z KSeF (ISO z mikrosekundami) na format Odoo"""
				if not date_str:
					return False
				try:
					# Usuń mikrosekundy (część po kropce) i strefę czasową
					if '.' in date_str:
						date_str = date_str.split('.')[0]
					if '+' in date_str:
						date_str = date_str.split('+')[0]
					if 'Z' in date_str:
						date_str = date_str.replace('Z', '')
					
					# Konwertuj na datetime i zwróć w formacie Odoo
					dt = datetime.fromisoformat(date_str)
					return dt.strftime('%Y-%m-%d %H:%M:%S')
				except Exception as e:
					_logger.warning(f"[KSeF][Python] Date conversion failed for {date_str}: {e}")
					return False


			# Obsługa access token z odpowiedzi redeem
			if 'accessToken' in tokens:
				access_token_obj = tokens['accessToken']
				if isinstance(access_token_obj, dict):
					update_vals['ksef_access_token'] = access_token_obj.get('token')
					# Konwertuj datę
					valid_until = access_token_obj.get('validUntil')
					if valid_until:
						update_vals['ksef_access_token_valid_until'] = convert_ksef_date(valid_until)
				else:
					update_vals['ksef_access_token'] = access_token_obj
					
			# Obsługa refresh token
			if 'refreshToken' in tokens:
				refresh_token_obj = tokens['refreshToken']
				if isinstance(refresh_token_obj, dict):
					update_vals['ksef_refresh_token'] = refresh_token_obj.get('token')
					# Konwertuj datę
					valid_until = refresh_token_obj.get('validUntil')
					if valid_until:
						update_vals['ksef_refresh_token_valid_until'] = convert_ksef_date(valid_until)
				else:
					update_vals['ksef_refresh_token'] = refresh_token_obj
			
			# Sprawdź czy mamy cokolwiek
			if not update_vals.get('ksef_access_token'):
				_logger.error(f"[KSeF][Python] No access token found in response: {tokens}")
				return {
					"success": False,
					"error": "No access token in KSeF response",
					"response": tokens
				}
			
			self.log.write(update_vals)
			
			_logger.info(f"[KSeF][Python] Auth successful, tokens saved to log {self.log.id}\n👉 update_vals = {update_vals}")
			
			return {
				"success": True,
				"data": tokens,
				"message": "New tokens obtained and saved to log"
			}
		
		except Exception as e:
			_logger.error(f"[KSeF][Python] Auth failed: {e}", exc_info=True)
			return {
				"success": False,
				"error": str(e)
			}

	def _check_auth_status(self, reference_number, auth_token, max_attempts=5):
		"""
		Sprawdza status autoryzacji z mechanizmem retry.
		
		Args:
			reference_number: ID autoryzacji (do URL)
			auth_token: Tymczasowy token autoryzacji (do nagłówka)
		"""
		endpoint = f"{self.api_url}/auth/{reference_number}"
		headers = {
			'Authorization': f'Bearer {auth_token}',
			'Accept': 'application/json'
		}
		
		for attempt in range(max_attempts):
			try:
				response = requests.get(
					endpoint,
					headers=headers,
					timeout=TIMEOUT
				)
				response.raise_for_status()
				data = response.json()
				
				status_code = data.get('status', {}).get('code')
				status_desc = data.get('status', {}).get('description')
				
				_logger.info(f"[KSeF][Python] Auth status check: code={status_code}, desc={status_desc}")
				
				if status_code == 200:
					return data
				elif status_code == 100:  # W trakcie przetwarzania
					time.sleep(2)  # Poczekaj 2 sekundy przed kolejną próbą
					continue
				else:
					raise UserError(f"Authentication failed with status {status_code}: {status_desc}")
					
			except requests.exceptions.RequestException as e:
				if attempt == max_attempts - 1:
					raise UserError(f"Failed to check auth status: {e}")
				time.sleep(2)
		
		raise UserError("Authentication timeout - still processing after multiple attempts")

	def _redeem_token(self, auth_token):
		"""
		Wymienia tymczasowy token na stałe access/refresh tokeny.
		
		Args:
			auth_token: Tymczasowy token autoryzacji
		"""
		endpoint = f"{self.api_url}/auth/token/redeem"
		headers = {
			'Authorization': f'Bearer {auth_token}',
			'Accept': 'application/json'
		}
		
		try:
			response = requests.post(endpoint, headers=headers, timeout=TIMEOUT)
			response.raise_for_status()
			return response.json()
		except requests.exceptions.RequestException as e:
			error_text = e.response.text if e.response else str(e)
			raise UserError(f"Failed to redeem token: {error_text}")


	# --------------------- REFRESH ---------------------

	def refresh_tokens(self):
		"""
		Uses refresh token from log to obtain new access token.
		Updates the log record with new tokens.
		"""
		if not self.log.ksef_refresh_token:
			_logger.warning(f"[KSeF][Python] No refresh token in log {self.log.id}")
			return {
				"success": False,
				"error": "No refresh token found",
				"requires_auth": True
			}

		endpoint = f"{self.api_url}/auth/token/refresh"
		headers = self._make_headers(self.log.ksef_refresh_token)

		try:
			response = requests.post(endpoint, headers=headers, timeout=30)
			response.raise_for_status()
			response_data = response.json()

			# Extract access token
			new_access_token = response_data.get('accessToken', {}).get('token')
			if not new_access_token:
				return {
					"success": False,
					"error": "Failed to retrieve new access token from KSeF response",
					"response": response_data
				}

			# Prepare update values
			update_vals = {
				'ksef_access_token': new_access_token,
				'ksef_access_token_valid_until':  self._parse_ksef_date( response_data.get('accessToken', {}).get('validUntil') ),
				'ksef_last_refresh_datetime': fields.Datetime.now(),
			}

			# Handle optional new refresh token
			if response_data.get('refreshToken'):
				_logger.info("[KSeF][Python] New refresh token received")
				update_vals.update({
					'ksef_refresh_token': response_data['refreshToken'].get('token'),
					'ksef_refresh_token_valid_until': self._parse_ksef_date( response_data['refreshToken'].get('validUntil') ),
				})

			# Update the log record
			self.log.write(update_vals)
			
			_logger.info(f"[KSeF][Python] Tokens refreshed successfully for log {self.log.id}")
			
			return {
				"success": True,
				"data": response_data,
				"message": "Access token refreshed"
			}

		except requests.exceptions.RequestException as e:
			error_text = e.response.text if e.response else str(e)
			_logger.exception(f"[KSeF][Python] Failed to refresh tokens for log {self.log.id}: {error_text}")
			
			if e.response and e.response.status_code == 401:
				return {
					"success": False,
					"error": "Refresh token expired or invalid",
					"requires_auth": True
				}
			
			return {
				"success": False,
				"error": f"Failed to refresh tokens: {error_text}"
			}


	# --------------------- VALIDATE TOKENS ---------------------

	def validate_tokens(self):
		"""
		Sprawdza ważność tokenów ZAPISANYCH W LOGU i wykonuje odpowiednie akcje.
		Wszystkie dane autoryzacyjne pochodzą WYŁĄCZNIE z communication.log.
		"""
		_logger.info(f"[KSeF][Python] Validating tokens from log {self.log.id}")
		
		# 1. Sprawdź czy mamy access token w logu
		if not self.log.ksef_access_token:
			_logger.info("[KSeF][Python] No access token in log, performing full auth")
			return self.auth()  # auth() zapisze tokeny DO LOGU
		
		# 2. Sprawdź ważność access token (z buforem 5 minut)
		access_valid, access_msg = self._is_token_valid(
			self.log.ksef_access_token_valid_until,
			buffer_minutes=5
		)
		
		if access_valid:
			_logger.info(f"[KSeF][Python] Access token from log is valid: {access_msg}")
			return {
				"success": True, 
				"action": "valid",
				"message": access_msg,
				"token_source": "log"  # explicit info
			}
		
		# 3. Access token nieważny - sprawdź refresh token w logu
		if not self.log.ksef_refresh_token:
			_logger.info("[KSeF][Python] No refresh token in log, performing full auth")
			return self.auth()
		
		refresh_valid, refresh_msg = self._is_token_valid(
			self.log.ksef_refresh_token_valid_until,
			buffer_minutes=60  # Większy bufor dla refresh token
		)
		
		if not refresh_valid:
			_logger.info(f"[KSeF][Python] Refresh token in log also invalid: {refresh_msg}")
			return self.auth()
		
		# 4. Refresh token ważny - próba odświeżenia
		_logger.info("[KSeF][Python] Access token expired, attempting refresh using refresh token from log")
		refresh_result = self.refresh_tokens()  # refresh_tokens() użyje refresh token Z LOGU
		
		if refresh_result.get('success'):
			return {
				"success": True, 
				"action": "refreshed",
				"data": refresh_result.get('data'),
				"message": "Access token refreshed successfully"
			}
		else:
			# 5. Refresh się nie udał - pełna autoryzacja
			_logger.warning(f"[KSeF][Python] Refresh failed: {refresh_result.get('error')}")
			return self.auth()

	def _is_token_valid(self, valid_until, buffer_minutes=5):
		"""
		Sprawdza czy token jest ważny.
		"""
		if not valid_until:
			return False, "No expiry date"
		
		now = fields.Datetime.now()
		buffer = timedelta(minutes=buffer_minutes)
		
		# Konwersja jeśli valid_until to string
		if isinstance(valid_until, str):
			try:
				# Obsługa formatu ISO
				if valid_until.endswith('Z'):
					valid_until = valid_until.replace('Z', '+00:00')
				if '.' in valid_until:
					valid_until = valid_until.split('.')[0]
				if '+' in valid_until:
					valid_until = valid_until.split('+')[0]
				expiry = datetime.fromisoformat(valid_until)
			except ValueError as e:
				return False, f"Invalid date format: {e}"
		else:
			expiry = valid_until
		
		if now > expiry:
			return False, f"Token expired"
		
		if now > (expiry - buffer):
			return True, f"Token valid but expires soon"
		
		return True, f"Token valid"
	# --------------------- OPEN SESSION ---------------------

	def open_session(self):
		"""
		Otwiera sesję - używa access token Z LOGU, zapisuje klucze sesji W LOGU.
		"""
		# Upewnij się, że mamy ważny access token W LOGU
		token_validation = self.validate_tokens()
		if not token_validation.get('success'):
			return token_validation
		
		try:
			# Generuj klucze (tymczasowe, nie w logu)
			raw_key = os.urandom(32)
			raw_iv = os.urandom(16)
			
			# Pobierz klucz publiczny MF
			public_keys = self._get_public_keys()
			public_key = serialization.load_pem_public_key(
				public_keys['symmetric'].encode('utf-8')
			)
			
			# Zaszyfruj klucz
			encrypted_key = public_key.encrypt(
				raw_key,
				padding.OAEP(
					mgf=padding.MGF1(algorithm=hashes.SHA256()),
					algorithm=hashes.SHA256(),
					label=None
				)
			)
			
			# Wyślij request
			response = self._make_request(
				'POST', 
				'/sessions/online',
				json={
					"formCode": {
						"systemCode": "FA (3)", 
						"schemaVersion": "1-0E", 
						"value": "FA"
					},
					"encryption": {
						"encryptedSymmetricKey": base64.b64encode(encrypted_key).decode(),
						"initializationVector": base64.b64encode(raw_iv).decode(),
					}
				}
			)
			
			data = response.json()
			_logger.info(f"[KSeF][Python] Open session response: {data}")
			
			# Funkcja pomocnicza do konwersji daty
			def convert_ksef_date(date_str):
				"""Konwertuje datę z KSeF (ISO z mikrosekundami) na format Odoo"""
				if not date_str:
					return False
				try:
					# Usuń mikrosekundy (część po kropce) i strefę czasową
					if '.' in date_str:
						date_str = date_str.split('.')[0]
					if '+' in date_str:
						date_str = date_str.split('+')[0]
					if 'Z' in date_str:
						date_str = date_str.replace('Z', '')
					
					# Konwertuj na datetime Odoo
					dt = datetime.fromisoformat(date_str)
					return fields.Datetime.to_string(dt)
				except Exception as e:
					_logger.warning(f"[KSeF][Python] Date conversion failed for {date_str}: {e}")
					return date_str  # Zwróć oryginał jeśli się nie uda
			
			# ZAPISZ DANE SESJI W LOGU z konwersją daty!
			update_vals = {
				'ksef_session_token': data.get('referenceNumber'), ###data.get('sessionId') or data.get('referenceNumber'),	XXX
				'ksef_session_valid_until': convert_ksef_date(data.get('validUntil')),
				'ksef_session_key': base64.b64encode(raw_key),  # Binary!
				'ksef_session_iv': base64.b64encode(raw_iv),	 # Binary!
				###'ksef_reference_number': data.get('referenceNumber'),	XXX
			}
			
			self.log.write(update_vals)
			
			_logger.info(f"[KSeF][Python] Session opened, saved to log {self.log.id}")
			_logger.info(f"[KSeF][Python] Session valid until: {update_vals['ksef_session_valid_until']}")
			
			return {
				"success": True,
				"data": data,
				"message": "Session opened and saved to log"
			}
			
		except Exception as e:
			_logger.error(f"[KSeF][Python] Open session failed: {e}", exc_info=True)
			return {
				"success": False,
				"error": str(e)
			}

	# ---------------------- PAYLOAD INVOICE MODE -------------

	def _extend_send_invoice_payload(self, payload):
		"""
		Rozszerza payload send_invoice o pola sterujące trybem fakturowania.

		Obsługiwane przypadki:
			- ONLINE
			- OFFLINE_MF
			- OFFLINE_TAXPAYER
			- OFFLINE_BUSINESS
			- korekta techniczna
		"""
		log = self.log
		move = log.env[log.document_model].browse(log.document_id).exists()
		if not move:
			return payload

		# ---------------------------
		# 1. OFFLINE MODE
		# ---------------------------

		offline_mode = move.ksef_offline_mode

		OFFLINE_MAP = {
			"mf": "OFFLINE_MF",
			"taxpayer": "OFFLINE_TAXPAYER",
			"business": "OFFLINE_BUSINESS",
		}

		if offline_mode and offline_mode not in OFFLINE_MAP:
			raise UserError(f"Invalid KSeF offline mode: {offline_mode}")

		invoicing_mode = OFFLINE_MAP.get(offline_mode, "ONLINE")

		payload["invoicingMode"] = invoicing_mode

		if offline_mode:
			payload["offlineMode"] = True

		# ---------------------------
		# TECHNICAL CORRECTION			ToDo:
		# ---------------------------
		#
		#if move.ksef_is_technical_correction:
		#	payload["isTechnicalCorrection"] = True

		return payload

	# ---------------------- SEND INVOICE ---------------------

	def send_invoice(self, xml_bytes):
		"""
		Wysyła fakturę używając DANYCH SESJI Z LOGU.
		"""
		# 1. Walidacja - czy mamy sesję W LOGU
		if not self.log.ksef_session_token:
			return {
				"success": False,
				"error": "No active session in log. Run open_session() first."
			}
		
		if not self.log.ksef_session_key or not self.log.ksef_session_iv:
			return {
				"success": False,
				"error": "Missing session keys in log. Run open_session() first."
			}
		
		_logger.info(f"[KSeF][Python] Sending invoice using session from log {self.log.id}")
		
		try:
			# 2. Pobierz klucze Z LOGU
			key = base64.b64decode(self.log.ksef_session_key)
			iv = base64.b64decode(self.log.ksef_session_iv)
			
			# 3. Oblicz hash oryginalnego XML
			xml_hash = hashlib.sha256(xml_bytes).digest()
			xml_hash_b64 = base64.b64encode(xml_hash).decode('utf-8')
			
			# 4. Szyfruj XML
			padder = sym_padding.PKCS7(128).padder()
			padded_data = padder.update(xml_bytes) + padder.finalize()
			
			cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
			encryptor = cipher.encryptor()
			encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
			
			# 5. Hash zaszyfrowanych danych
			encrypted_hash = hashlib.sha256(encrypted_data).digest()
			encrypted_hash_b64 = base64.b64encode(encrypted_hash).decode('utf-8')
			
			# 6. Payload
			payload = {
				"invoiceHash": xml_hash_b64,
				"invoiceSize": len(xml_bytes),
				"encryptedInvoiceHash": encrypted_hash_b64,
				"encryptedInvoiceSize": len(encrypted_data),
				"encryptedInvoiceContent": base64.b64encode(encrypted_data).decode('utf-8')
			}

			payload = self._extend_send_invoice_payload(payload)
			
			# 7. Wywołaj API (używa access token Z LOGU przez _make_request)
			endpoint = f"{self.api_url}/sessions/online/{self.log.ksef_session_token}/invoices"
			response = self._make_request('POST', endpoint, json=payload)
			data = response.json()
			
			# 8. ZAPISZ WYNIK W LOGU
			update_vals = {
				'ksef_invoice_number': data.get('invoiceReferenceNumber'),
				'ksef_reference_number': data.get('referenceNumber'),
				'ksef_sent_datetime': fields.Datetime.now(),
				'ksef_processing_code': data.get('processingCode'),
				'ksef_api_status_message': data.get('processingDescription'),
				'ksef_http_status': response.status_code,
				'payload_request': json.dumps(payload, ensure_ascii=False),
				'payload_response': json.dumps(data, ensure_ascii=False),
				"ksef_invoice_hash": xml_hash_b64,
			}
			
			#if data.get('invoiceHash'):
			#	update_vals['ksef_invoice_hash'] = data['invoiceHash']

			###_logger.info(f"[KSeF][Python] Finale: update_vals {update_vals}")
			self.log.write(update_vals)
			
			return {
				"success": True,
				"data": data,
				"context_updates": update_vals
			}

		except TokenExpiredException:
			# Token wygasł ale mamy refresh token - próbuj odświeżyć
			_logger.info("[KSeF][Python] Token expired, attempting refresh for send_invoice")
			
			refresh_result = self.refresh_tokens()  # to NIE używa _make_request!
			
			if refresh_result.get('success'):
				# Ponów operację
				return self.send_invoice(xml_bytes)
			else:
				# Refresh nie zadziałał - potrzebna autoryzacja
				self.log.write({
					'ksef_operation': 'auth',
					'ksef_next_execution': fields.Datetime.now(),
					'provider_message': 'Token refresh failed - reauthentication required',
					'ksef_status': 'pending',
				})
				return {
					'success': False,
					'error': 'Token refresh failed - reauthentication required',
					'requires_auth': True,
				}
			
		except Exception as e:
			_logger.error(f"[KSeF][Python] Send invoice failed: {e}", exc_info=True)
			return {
				"success": False,
				"error": str(e)
			}
	# --------------------- CHECK STATUS ---------------------

	def check_status(self):
		reference = self.log.ksef_reference_number

		response = self._call_status_api(reference)

		return {"success": True, "data": response}

	def check_invoice_status(self):
		"""
		Sprawdza status faktury używając reference number Z LOGU.
		"""
		if not self.log.ksef_reference_number:
			return {
				"success": False,
				"error": "No reference number in log"
			}
		
		try:
			endpoint = f"{self.api_url}/sessions/{self.log.ksef_session_token}/invoices/{self.log.ksef_reference_number}"
			response = self._make_request('GET', endpoint)
			data = response.json()
			
			# Zapisz status w logu
			self.log.write({
				'ksef_api_status_code': data.get('statusCode'),
				'ksef_api_status_message': data.get('statusDescription'),
				'ksef_processing_code': data.get('processingCode'),
				'payload_response': json.dumps(data, ensure_ascii=False)
			})
			
			return {
				"success": True,
				"data": data
			}
			
		except Exception as e:
			return {
				"success": False,
				"error": str(e)
			}

	# --------------------- DOWNLOAD UPO ---------------------

	def download_upo(self):
		"""
		Pobiera UPO dla faktury z LOGU.
		"""
		if not self.log.ksef_reference_number:
			return {
				"success": False,
				"error": "No reference number in log"
			}
		
		try:

			endpoint = f"{self.api_url}/sessions/{self.log.ksef_session_token}/invoices/{self.log.ksef_reference_number}/upo"

			#_logger.info( 
			#	f"\n📢 self.log.ksef_invoice_number = {self.log.ksef_invoice_number}"
			#	f"\n📢 endpoint = {endpoint}"
			#)
			response = self._make_request('GET', endpoint)
			
			# response.content to binarny XML UPO
			upo_content = response.content
			
			# Zapisz jako załącznik (metoda w logu)
			if upo_content:
				self._attach_upo(upo_content)

			return {
				"success": True,
				"data": {
					"content_size": len(upo_content),
					"content_type": response.headers.get('Content-Type')
				},
				"upo_binary": upo_content  # dla _process_python_flow
			}
			
		except Exception as e:
			return {
				"success": False,
				"error": str(e)
			}

	# --------------------- CLOSE SESSION ---------------------

	def close_session(self):
		"""
		Zamyka sesję i CZYŚCI DANE SESJI Z LOGU.
		"""
		if not self.log.ksef_session_token:
			return {
				"success": False,
				"error": "No active session in log"
			}
		
		try:
			endpoint = f"{self.api_url}/sessions/online/{self.log.ksef_session_token}/close"
			response = self._make_request('POST', endpoint)
			
			# Wyczyść dane sesji Z LOGU (ale zostaw tokeny!)
			self.log.write({
				'ksef_session_token': False,
				'ksef_session_key': False,
				'ksef_session_iv': False,
				'ksef_session_valid_until': False,
			})
			
			return {
				"success": True,
				"data": response.json() if response.content else {}
			}
			
		except Exception as e:
			# Nawet przy błędzie API - sesja i tak może być zamknięta
			# Wyczyść dane sesji z logu
			self.log.write({
				'ksef_session_token': False,
				'ksef_session_key': False,
				'ksef_session_iv': False,
				'ksef_session_valid_until': False,
			})
			return {
				"success": False,
				"error": str(e)
			}


	# --------------------- IMPORT INVOICE LIST  --------------

	def get_invoice_list(self):
		pass

	# --------------------- IMPORT INVOICE --------------------

	def get_received_invoices(self, date_from, date_to, page_size=100):
		"""
		Pobiera listę faktur otrzymanych (SUBJECT2) z KSeF.
		Używa POST /invoices/query/metadata (zgodnie z Javą)
		"""
		endpoint = f"{self.api_url}/invoices/query/metadata"
		
		# Request body (tak jak w Javie)
		payload = {
			"subjectType": "SUBJECT2",
			"dateRange": {
				"dateType": "INVOICING",
				"from": date_from + "T00:00:00+01:00",
				"to": date_to + "T23:59:59+01:00",
			}
		}
		
		params = {
			"pageSize": page_size,
		}
		
		try:
			response = self._make_request('POST', endpoint, json=payload, params=params)
			return {
				"success": True,
				"data": response.json(),
				"status_code": response.status_code,
			}
		except Exception as e:
			return {
				"success": False,
				"error": str(e),
			}

	def get_invoice_by_number(self, ksef_number):
		"""
		Pobiera pojedynczą fakturę XML z KSeF.
		Używa GET /invoices/ksef/{ksefNumber} (zgodnie z Javą)
		"""
		endpoint = f"{self.api_url}/invoices/ksef/{ksef_number}"

		try:
			response = self._make_request('GET', endpoint, headers={'Accept': 'application/xml'})
			
			xml_bytes = response.content  # Surowe bajty XML
			xml_base64 = base64.b64encode(xml_bytes).decode('utf-8')
			
			# Oblicz hash z surowego XML (zgodnie z KSeF)
			xml_hash = hashlib.sha256(xml_bytes).digest()
			xml_hash_b64 = base64.b64encode(xml_hash).decode('utf-8')
			_logger.info(f"\n🍀🍀🍀 xml_hash {xml_hash} xml_hash_b64 {xml_hash_b64}")
			return {
				"success": True,
				"data": {
					"ksef_number": ksef_number,
					"xml_base64": xml_base64,
					"file_size": len(xml_bytes),
					"ksef_invoice_hash": xml_hash_b64,  # ← hash zgodny z KSeF
				},
				"status_code": response.status_code,
			}
		except Exception as e:
			_logger.info(f"\n💥💥💥 ERROR {e}")
			return {
				"success": False,
				"error": str(e),
			}

	# ============================================================
	# =====================  TOKEN LOGIC  ========================
	# ============================================================

	def _store_tokens(self, tokens):
		"""
		Zapis tokenów w communication.log.
		"""
		self.log.write({
			"ksef_access_token": tokens.get("accessToken"),
			"ksef_access_token_valid_until": tokens.get("accessTokenValidUntil"),
			"ksef_refresh_token": tokens.get("refreshToken"),
			"ksef_refresh_token_valid_until": tokens.get("refreshTokenValidUntil"),
		})

	def _is_access_token_expired(self):
		expiry = self.log.ksef_access_token_valid_until
		if not expiry:
			return True

		now = fields.Datetime.now()
		buffer = timedelta(minutes=5)

		return now >= (expiry - buffer)

	# ============================================================
	# =====================  SESSION LOGIC  ======================
	# ============================================================

	def session_is_active(self):
		"""
		Sprawdza na podstawie LOGU czy sesja jest aktywna.
		"""
		if not self.log.ksef_session_token:
			return False
		
		if not self.log.ksef_session_valid_until:
			return False
		
		now = fields.Datetime.now()
		buffer = timedelta(minutes=5)
		
		# Valid until może być stringiem z API
		valid_until = self.log.ksef_session_valid_until
		if isinstance(valid_until, str):
			try:
				if valid_until.endswith('Z'):
					valid_until = valid_until.replace('Z', '+00:00')
				valid_until = datetime.fromisoformat(valid_until)
				if valid_until.tzinfo is not None:
					valid_until = valid_until.replace(tzinfo=None)
			except:
				return False
		
		return now < (valid_until - buffer)

	def _store_session(self, response, aes_key, iv):
		self.log.write({
			"ksef_session_token": response.get("sessionId"),
			"ksef_session_valid_until": response.get("validUntil"),
			"ksef_session_key": aes_key,
			"ksef_session_iv": iv,
		})

	def _clear_session(self):
		self.log.write({
			"ksef_session_token": False,
			"ksef_session_valid_until": False,
			"ksef_session_key": False,
			"ksef_session_iv": False,
		})

	# ============================================================
	# METODY POMOCNICZE (niezmienione, ale używają self.log)
	# ============================================================

	def _get_config_api_url(self):
		"""
		Zwraca URL API KSeF z konfiguracji providera.
		"""
		if not self.provider.base_url:
			raise UserError("Brak skonfigurowanego base_url w providerze KSeF")
		
		# Usuń końcowy slash jeśli istnieje
		base_url = self.provider.base_url.rstrip('/')
		return base_url	
	
	def _make_headers(self, token=None):
		"""Tworzy nagłówki z tokenem Z LOGU jeśli nie podano innego"""
		token = token or self.log.ksef_access_token
		result = {
			'Authorization': f'Bearer {token}',
			'Content-Type': 'application/json',
		}
		#if self.log.headers:
		#	result.extend( self.log.headers )
		return result
	
	def _make_request(self, method, endpoint, operation_context=None, **kwargs):
		"""
		Wykonuje zapytanie HTTP z obsługą tokenów.
		
		:param method: metoda HTTP (GET, POST, etc.)
		:param endpoint: endpoint API
		:param operation_context: kontekst operacji (np. 'send_invoice') do logowania
		:param kwargs: dodatkowe argumenty dla requests
		:return: response object
		:raises: UserError gdy autoryzacja jest niemożliwa
		"""
		kwargs.setdefault('headers', {})
		kwargs.setdefault('timeout', TIMEOUT)
		
		# Dodaj token do nagłówka
		if self.log.ksef_access_token:
			kwargs['headers']['Authorization'] = f'Bearer {self.log.ksef_access_token}'
		
		full_url = endpoint if endpoint.startswith('http') else f"{self.api_url}{endpoint}"
		
		try:
			response = requests.request(method, full_url, **kwargs)
			
			# Jeśli 401 - token wygasł
			if response.status_code == 401:
				_logger.warning(f"[KSeF][Python] Token expired for {operation_context or 'unknown operation'}")
				
				# Sprawdź czy refresh token istnieje i jest ważny
				refresh_token = self.log.ksef_refresh_token
				refresh_valid_until = self.log.ksef_refresh_token_valid_until
				
				refresh_valid = False
				if refresh_token and refresh_valid_until:
					now = fields.Datetime.now()
					if now < refresh_valid_until:
						refresh_valid = True
				
				if refresh_valid:
					# Mamy ważny refresh token - próbujemy odświeżyć
					_logger.info("[KSeF][Python] Refresh token valid, attempting refresh")
					
					# Wykonaj refresh poza tą metodą (bez rekurencji!)
					# Metoda refresh_tokens() powinna być wywołana przez caller
					raise TokenExpiredException("Token expired, refresh possible")
				else:
					# Refresh token też nieważny - koniec, potrzebna nowa autoryzacja
					_logger.error("[KSeF][Python] Refresh token also invalid - reauthentication required")
					
					# Aktualizuj log - ustaw operację na auth
					self.log.write({
						'ksef_operation': 'auth',
						'ksef_next_execution': fields.Datetime.now(),
						'provider_message': 'Token expired and refresh token invalid - reauthentication required',
						'ksef_status': 'pending',
					})
					
					raise UserError("Token expired - reauthentication scheduled")
			
			# Inne błędy HTTP
			response.raise_for_status()
			return response
			
		except requests.exceptions.RequestException as e:
			error_text = e.response.text if e.response is not None else str(e)
			_logger.exception(f"[KSeF][Python] Request failed: {error_text}")
			raise UserError(f"KSeF API Error: {error_text}")


	def _get_public_keys(self):
		"""
		Pobiera klucze publiczne MF (niezmienione, ale używa providera)
		"""
		endpoint = f"{self.api_url}/security/public-key-certificates"
		headers = {'Accept': 'application/json'}
		
		try:
			response = requests.get(endpoint, headers=headers, timeout=TIMEOUT)
			response.raise_for_status()
			certs_data = response.json()
			
			public_keys = {'symmetric': None, 'token': None}
			
			for cert_info in certs_data:
				usage = cert_info.get('usage', [])
				
				if not set(usage) & {'SymmetricKeyEncryption', 'KsefTokenEncryption'}:
					continue
				
				cert_b64 = cert_info['certificate']
				cert_der = base64.b64decode(cert_b64)
				cert = x509.load_der_x509_certificate(cert_der)
				public_key = cert.public_key()
				public_key_pem = public_key.public_bytes(
					encoding=serialization.Encoding.PEM,
					format=serialization.PublicFormat.SubjectPublicKeyInfo
				).decode('utf-8')
				
				if 'SymmetricKeyEncryption' in usage:
					public_keys['symmetric'] = public_key_pem
				if 'KsefTokenEncryption' in usage:
					public_keys['token'] = public_key_pem
			
			if not public_keys['symmetric'] or not public_keys['token']:
				raise UserError("Could not find all required KSeF public keys")
			
			return public_keys
			
		except Exception as e:
			raise UserError(f"Could not fetch KSeF public keys: {e}")
	
	def _get_challenge(self):
		"""Pobiera challenge (niezmienione)"""
		endpoint = f"{self.api_url}/auth/challenge"
		try:
			response = requests.post(endpoint, timeout=TIMEOUT)
			response.raise_for_status()
			return response.json()
		except Exception as e:
			raise UserError(f"Failed to get challenge: {e}")

	# ============================================================
	# =====================  CRYPTO  =============================
	# ============================================================

	def _generate_session_keys(self):
		"""
		Generuje AES-256 key i IV.
		"""
		raise NotImplementedError("AES key generation not implemented")

	def _encrypt_session_key(self, aes_key):
		"""
		Szyfruje AES key kluczem publicznym MF.
		"""
		raise NotImplementedError("Session key encryption not implemented")

	def _encrypt_invoice(self, xml_content):
		"""
		Szyfruje XML kluczem sesji.
		"""
		raise NotImplementedError("Invoice encryption not implemented")

	def _sign_challenge(self, challenge):
		"""
		Podpisuje challenge przy użyciu certyfikatu AUTH.
		"""
		raise NotImplementedError("Challenge signing not implemented")

	# ============================================================
	# =====================  HTTP CALLS  =========================
	# ============================================================

	def _fetch_challenge(self):
		raise NotImplementedError("Challenge fetch not implemented")

	def _exchange_signed_challenge(self, signed):
		raise NotImplementedError("Signed challenge exchange not implemented")

	def _redeem_refresh_token(self, refresh_token):
		raise NotImplementedError("Refresh token exchange not implemented")

	def _call_open_session_api(self, encrypted_key):
		raise NotImplementedError("Open session API not implemented")

	def _call_send_invoice_api(self, encrypted_xml):
		raise NotImplementedError("Send invoice API not implemented")

	def _call_status_api(self, reference):
		raise NotImplementedError("Status API not implemented")

	def _call_download_upo_api(self, reference):
		raise NotImplementedError("Download UPO API not implemented")

	def _call_close_session_api(self, session_id):
		raise NotImplementedError("Close session API not implemented")

	# ============================================================
	# =====================  ATTACHMENTS  ========================
	# ============================================================

	def _attach_upo(self, upo_binary):
		"""
		Zapisuje UPO jako załącznik do communication.log.
		"""

		filename = f"ksef-upo-{self.log.ksef_reference_number}.xml"

		model = self.log.document_model
		rekord = self.log.document_id

		attachment = self.log.env['ir.attachment'].create({
			'company_id': rekord.company_id.id,
			'name': filename,
			'type': 'binary',
			'datas': base64.b64encode(upo_binary),
			'res_model': model,
			'res_id': rekord,
			'mimetype': 'application/xml',
		})

		return attachment
"""
	ProviderXadesSigner
"""
class ProviderXadesSigner:
	"""
	Tworzy podpisy XAdES-BES dla autoryzacji KSeF.
	Używa certyfikatów AUTH z konfiguracji providera.
	"""
	
	def __init__(self, provider):
		"""
		Inicjalizuje signer z certyfikatami z providera KSeF.
		
		Args:
			provider: communication.provider.ksef record
		"""
		self.provider = provider
		self._load_auth_certificate()
	
	def _load_auth_certificate(self):
		"""Ładuje certyfikat AUTH z keystore p12"""
		if not self.provider.auth_keystore_p12:
			raise UserError("Brak keystore AUTH w konfiguracji providera KSeF")
		
		# Pobierz dane p12 z załącznika
		p12_data = self.provider.auth_keystore_p12.datas
		
		# Konwersja - dane mogą być już base64 lub surowe
		if isinstance(p12_data, bytes):
			try:
				# Sprawdź czy to base64
				p12_bytes = base64.b64decode(p12_data)
			except:
				# To już surowe dane p12
				p12_bytes = p12_data
		else:
			# String - musi być base64
			p12_bytes = base64.b64decode(p12_data)
		
		# Wczytaj p12
		password = self.provider.auth_keystore_password or ''
		if isinstance(password, str):
			password = password.encode('utf-8')
		
		try:
			private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
				p12_bytes,
				password
			)
		except Exception as e:
			raise UserError(f"Nie można wczytać keystore AUTH: {e}")
		
		if not private_key or not certificate:
			raise UserError("Keystore AUTH nie zawiera klucza prywatnego lub certyfikatu")
		
		self.private_key = private_key
		self.cert = certificate
		self.additional_certs = additional_certs
		
		_logger.info(f"[KSeF][XAdES] Loaded AUTH certificate: {certificate.subject.rfc4514_string()}")
	
	@staticmethod
	def _calculate_digest(node):
		"""Oblicza digest SHA-256 dla znormalizowanego węzła XML"""
		c14n_node = etree.tostring(node, method="c14n", exclusive=True, with_comments=False, strip_text=False)
		digest = hashes.Hash(hashes.SHA256())
		digest.update(c14n_node)
		return base64.b64encode(digest.finalize()).decode('utf-8')
	
	def _der_to_raw_ecdsa(self, signature):
		"""Konwertuje podpis ECDSA z DER do raw"""
		r, s = decode_dss_signature(signature)
		key_size = (self.private_key.curve.key_size + 7) // 8
		return r.to_bytes(key_size, 'big') + s.to_bytes(key_size, 'big')
	
	def _build_qualifying_properties(self, signature_node, sig_id, props_id):
		"""Buduje węzeł QualifyingProperties dla XAdES-BES"""
		NS_DS = "http://www.w3.org/2000/09/xmldsig#"
		NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
		
		object_node = etree.SubElement(signature_node, etree.QName(NS_DS, "Object"))
		qualifying_props_node = etree.SubElement(object_node, etree.QName(NS_XADES, "QualifyingProperties"), Target=f"#{sig_id}")
		signed_props_node = etree.SubElement(qualifying_props_node, etree.QName(NS_XADES, "SignedProperties"), Id=props_id)
		signed_sig_props_node = etree.SubElement(signed_props_node, etree.QName(NS_XADES, "SignedSignatureProperties"))
		
		# SigningTime
		now = datetime.now(timezone.utc)
		etree.SubElement(signed_sig_props_node, etree.QName(NS_XADES, "SigningTime")).text = now.strftime('%Y-%m-%dT%H:%M:%SZ')
		
		# SigningCertificate
		signing_cert_node = etree.SubElement(signed_sig_props_node, etree.QName(NS_XADES, "SigningCertificate"))
		cert_node = etree.SubElement(signing_cert_node, etree.QName(NS_XADES, "Cert"))
		cert_digest_node = etree.SubElement(cert_node, etree.QName(NS_XADES, "CertDigest"))
		etree.SubElement(cert_digest_node, etree.QName(NS_DS, "DigestMethod"), Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
		
		# DigestValue certyfikatu
		cert_digest = hashes.Hash(hashes.SHA256())
		cert_digest.update(self.cert.public_bytes(serialization.Encoding.DER))
		etree.SubElement(cert_digest_node, etree.QName(NS_DS, "DigestValue")).text = base64.b64encode(cert_digest.finalize()).decode('utf-8')
		
		# IssuerSerial
		issuer_serial_node = etree.SubElement(cert_node, etree.QName(NS_XADES, "IssuerSerial"))
		etree.SubElement(issuer_serial_node, etree.QName(NS_DS, "X509IssuerName")).text = self.cert.issuer.rfc4514_string()
		etree.SubElement(issuer_serial_node, etree.QName(NS_DS, "X509SerialNumber")).text = str(self.cert.serial_number)
		
		return self._calculate_digest(signed_props_node)
	
	def sign_authentication_challenge(self, challenge_code, nip):
		"""
		Tworzy podpisany XML dla autoryzacji XAdES.
		
		Args:
			challenge_code (str): Kod challenge z KSeF
			nip (str): NIP firmy (z konfiguracji providera)
		
		Returns:
			str: Podpisany XML jako string
		"""
		# 1. Stwórz bazowy XML
		xml_to_sign_str = f'<AuthTokenRequest xmlns="http://ksef.mf.gov.pl/auth/token/2.0"><Challenge>{challenge_code}</Challenge><ContextIdentifier><Nip>{nip}</Nip></ContextIdentifier><SubjectIdentifierType>certificateSubject</SubjectIdentifierType></AuthTokenRequest>'
		root = etree.fromstring(xml_to_sign_str)
		
		# 2. Określ algorytm podpisu
		is_rsa = isinstance(self.private_key, rsa.RSAPrivateKey)
		sig_alg_uri = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256" if is_rsa else "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
		
		# 3. Namespaces
		NS_DS = "http://www.w3.org/2000/09/xmldsig#"
		
		# 4. Generuj ID
		sig_id = f"signature-{uuid.uuid4()}"
		props_id = f"signedprops-{uuid.uuid4()}"
		
		# 5. Stwórz węzeł Signature
		signature_node = etree.SubElement(
			root, 
			etree.QName(NS_DS, "Signature"), 
			Id=sig_id, 
			nsmap={'ds': NS_DS, 'xades': "http://uri.etsi.org/01903/v1.3.2#"}
		)
		
		# 6. SignedInfo
		signed_info_node = etree.SubElement(signature_node, etree.QName(NS_DS, "SignedInfo"))
		etree.SubElement(signed_info_node, etree.QName(NS_DS, "CanonicalizationMethod"), Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
		etree.SubElement(signed_info_node, etree.QName(NS_DS, "SignatureMethod"), Algorithm=sig_alg_uri)
		
		# 7. Reference do dokumentu
		ref1 = etree.SubElement(signed_info_node, etree.QName(NS_DS, "Reference"), Id=f"reference-{uuid.uuid4()}", URI="")
		transforms = etree.SubElement(ref1, etree.QName(NS_DS, "Transforms"))
		etree.SubElement(transforms, etree.QName(NS_DS, "Transform"), Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
		etree.SubElement(ref1, etree.QName(NS_DS, "DigestMethod"), Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
		digest1_node = etree.SubElement(ref1, etree.QName(NS_DS, "DigestValue"))
		
		# 8. Reference do SignedProperties
		ref2 = etree.SubElement(signed_info_node, etree.QName(NS_DS, "Reference"), Type="http://uri.etsi.org/01903#SignedProperties", URI=f"#{props_id}")
		transforms2 = etree.SubElement(ref2, etree.QName(NS_DS, "Transforms"))
		etree.SubElement(transforms2, etree.QName(NS_DS, "Transform"), Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
		etree.SubElement(ref2, etree.QName(NS_DS, "DigestMethod"), Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
		digest2_node = etree.SubElement(ref2, etree.QName(NS_DS, "DigestValue"))
		
		# 9. Oblicz digesty
		temp_root = etree.fromstring(etree.tostring(root))
		temp_root.xpath("./ds:Signature", namespaces={'ds': NS_DS})[0].getparent().remove(
			temp_root.xpath("./ds:Signature", namespaces={'ds': NS_DS})[0]
		)
		digest1_node.text = self._calculate_digest(temp_root)
		digest2_node.text = self._build_qualifying_properties(signature_node, sig_id, props_id)
		
		# 10. Podpisz SignedInfo
		signed_info_c14n = etree.tostring(signed_info_node, method="c14n", exclusive=True, with_comments=False)
		
		if is_rsa:
			signature_val = self.private_key.sign(signed_info_c14n, padding.PKCS1v15(), hashes.SHA256())
		else:
			der_sig = self.private_key.sign(signed_info_c14n, ec.ECDSA(hashes.SHA256()))
			signature_val = self._der_to_raw_ecdsa(der_sig)
		
		# 11. Dodaj SignatureValue
		etree.SubElement(signature_node, etree.QName(NS_DS, "SignatureValue")).text = base64.b64encode(signature_val).decode('utf-8')
		
		# 12. Dodaj KeyInfo z certyfikatem
		key_info_node = etree.SubElement(signature_node, etree.QName(NS_DS, "KeyInfo"))
		x509_data = etree.SubElement(key_info_node, etree.QName(NS_DS, "X509Data"))
		
		# Certyfikat w formacie PEM (bez nagłówków)
		cert_pem = self.cert.public_bytes(serialization.Encoding.PEM)
		cert_lines = cert_pem.decode('utf-8').splitlines()
		cert_content = "".join(cert_lines[1:-1])  # usuń BEGIN/END
		etree.SubElement(x509_data, etree.QName(NS_DS, "X509Certificate")).text = cert_content
		
		# 13. Przenieś Object na koniec (wymagane przez XAdES)
		object_node = signature_node.xpath("./ds:Object", namespaces={'ds': NS_DS})[0]
		signature_node.append(object_node)
		
		# 14. Zwróć jako string
		return etree.tostring(root, xml_declaration=True, encoding="utf-8", standalone="no").decode('utf-8')

#EoF

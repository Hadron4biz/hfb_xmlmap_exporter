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
"""@version 17.1.7
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
#################################################################################
#   Provider KSeF – dodatek do pobierania aktualnego certyfikatu klucza Pub MF
#################################################################################

from odoo import api, fields, models
from odoo.exceptions import UserError
import requests
import base64
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
import logging

_logger = logging.getLogger(__name__)
TIMEOUT = 10

class CommunicationProviderKsef(models.Model):
	_inherit = "communication.provider.ksef"
	
	mf_certificate_pem = fields.Text(
		string="Klucz publiczny MF (PEM)",
		help="Publiczny klucz RSA Ministerstwa Finansów",
		tracking=True,  # śledzenie zmian dla audytu
	)
	
	last_key_fetch_date = fields.Datetime(
		string="Data ostatniego pobrania kluczy",
		readonly=True,
		tracking=True,
	)
	
	key_fetch_status = fields.Char(
		string="Status ostatniego pobrania",
		readonly=True,
	)
	
	def action_fetch_public_keys(self):
		"""
		Metoda wywoływana z przycisku w formularzu
		Pobiera klucze publiczne MF i zapisuje je w polu mf_certificate_pem
		"""
		self.ensure_one()
		
		if not self.base_url:
			raise UserError("Najpierw należy ustawić URL API KSeF")
		
		try:
			# Pobierz klucze publiczne
			public_keys = self._fetch_public_keys_from_api()
			
			# Zapisz klucz (możesz wybrać który: 'symmetric' lub 'token')
			# Zazwyczaj używa się klucza do szyfrowania symetrycznego
			self.mf_certificate_pem = public_keys.get('symmetric')
			
			# Dodatkowo możesz zapisać oba klucze w oddzielnych polach
			self.last_key_fetch_date = fields.Datetime.now()
			self.key_fetch_status = f"Sukces: pobrano klucze dla {self.base_url}"
		
			return True
	
			# Opcjonalnie: pokaż komunikat sukcesu
			return {
				'type': 'ir.actions.client',
				'tag': 'display_notification',
				'params': {
					'title': 'Sukces',
					'message': f'Pomyślnie pobrano klucze publiczne z {self.base_url}',
					'type': 'success',
					'sticky': False,
				}
			}
			
		except Exception as e:
			self.key_fetch_status = f"Błąd: {str(e)}"
			raise UserError(f"Nie udało się pobrać kluczy publicznych: {str(e)}")
	
	def _fetch_public_keys_from_api(self):
		"""
		Wewnętrzna metoda do pobierania kluczy z API
		Używa base_url z bieżącego rekordu
		"""
		endpoint = f"{self.base_url}/security/public-key-certificates"
		headers = {'Accept': 'application/json'}
		
		_logger.info(f"Pobieranie kluczy z endpointu: {endpoint}")
		
		try:
			response = requests.get(endpoint, headers=headers, timeout=TIMEOUT)
			response.raise_for_status()
			certs_data = response.json()
			
			public_keys = {'symmetric': None, 'token': None}
			
			for cert_info in certs_data:
				usage = cert_info.get('usage', [])
				
				# Sprawdź czy certyfikat pasuje do wymaganych typów
				if not set(usage) & {'SymmetricKeyEncryption', 'KsefTokenEncryption'}:
					continue
				
				cert_b64 = cert_info['certificate']
				cert_der = base64.b64decode(cert_b64)
				cert = x509.load_der_x509_certificate(cert_der, default_backend())
				public_key = cert.public_key()
				public_key_pem = public_key.public_bytes(
					encoding=serialization.Encoding.PEM,
					format=serialization.PublicFormat.SubjectPublicKeyInfo
				).decode('utf-8')
				
				if 'SymmetricKeyEncryption' in usage:
					public_keys['symmetric'] = public_key_pem
					_logger.info("Pobrano klucz SymmetricKeyEncryption")
				if 'KsefTokenEncryption' in usage:
					public_keys['token'] = public_key_pem
					_logger.info("Pobrano klucz KsefTokenEncryption")
			
			if not public_keys['symmetric'] or not public_keys['token']:
				raise UserError("Nie znaleziono wszystkich wymaganych kluczy publicznych KSeF")
			
			return public_keys
			
		except requests.exceptions.RequestException as e:
			_logger.error(f"Błąd sieci podczas pobierania kluczy: {e}")
			raise UserError(f"Błąd sieci: {e}")
		except Exception as e:
			_logger.error(f"Błąd podczas przetwarzania kluczy: {e}")
			raise UserError(f"Błąd przetwarzania: {e}")
	
	@api.onchange('environment')
	def _onchange_environment(self):
		"""
		Automatycznie aktualizuj base_url przy zmianie środowiska
		"""
		if self.environment == 'test':
			self.base_url = "https://api-test.ksef.mf.gov.pl/api/v2"
		elif self.environment == 'production':
			self.base_url = "https://api.ksef.mf.gov.pl/api/v2"
		
		# Opcjonalnie: wyczyść stary klucz przy zmianie środowiska
		if self.mf_certificate_pem:
			self.mf_certificate_pem = False
			self.key_fetch_status = False

#EoF

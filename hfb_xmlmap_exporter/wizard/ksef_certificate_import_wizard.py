# -*- coding: utf-8 -*-
#################################################################################
#
# Odoo, Open ERP Source Management Solution
# Copyright (C) 17-25 Hadron for business sp. z o.o. (http://www.hadron.eu.com)
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
""" @version 17.1.7
    @owner  Hadron for Business
    @author andrzej wiśniewski warp3r
    @date   2026.03.12
"""
#################################################################################
# Wizard importu certyfikatów KSeF - wersja rozszerzona
# Obsługuje zarówno Python backend (1 certyfikat) jak i Java backend (2 certyfikaty)
#################################################################################
import base64
import logging
import subprocess
import tempfile
import os
import re
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class KsefCertificateImportWizard(models.TransientModel):
	"""
	Wizard uproszczonego importu certyfikatów KSeF.
	
	W zależności od wybranego backendu:
	- Python: wymaga tylko certyfikatu AUTH
	- Java: wymaga AUTH + SIGN (dwa certyfikaty)
	
	Użytkownik wgrywa pliki, system automatycznie:
	1. Sprawdza algorytm (wymagany RSA)
	2. Konwertuje na .p12
	3. Weryfikuje poprawność
	4. Zapisuje .p12 jako załączniki i hasła w konfiguracji
	"""
	
	_name = 'ksef.certificate.import.wizard'
	_description = 'KSeF Certificate Import Wizard'
	
	# =========================================================================
	# POLA WIZARDA
	# =========================================================================
	
	config_id = fields.Many2one(
		'communication.provider.ksef',
		string='Konfiguracja KSeF',
		required=True,
		domain=[('auth_type', '=', 'certificate')],
		help='Wybierz konfigurację KSeF, do której chcesz zaimportować certyfikaty'
	)
	
	# =========================================================================
	# WYBÓR BACKENDU (KLUCZOWE!)
	# =========================================================================
	
	api_backend = fields.Selection(
		[
			('python', 'Python HTTP Client (zalecany dla Odoo)'),
			('java', 'Java Client (z zewnętrznym JAR)'),
		],
		string='Backend komunikacji',
		required=True,
		default='python',
		help='''
			Python HTTP Client: Wymaga tylko jednego certyfikatu (AUTH).
			System samodzielnie realizuje podpis cyfrowy.
			
			Java Client: Wymaga dwóch certyfikatów (AUTH + SIGN).
			Zewnętrzny JAR realizuje podpis i komunikację.
		'''
	)
	
	# =========================================================================
	# WSPÓLNE POLA DLA OBU BACKENDÓW
	# =========================================================================
	
	p12_password = fields.Char(
		string='Hasło dla plików .p12',
		required=True,
		help='Hasło zabezpieczające pliki .p12 (będzie używane w konfiguracji)'
	)
	
	p12_password_confirm = fields.Char(
		string='Potwierdź hasło',
		required=True,
		help='Powtórz hasło dla plików .p12'
	)
	
	overwrite_existing = fields.Boolean(
		string='Nadpisz istniejące certyfikaty',
		default=True,
		help='Jeśli zaznaczone, istniejące certyfikaty zostaną nadpisane'
	)
	
	# =========================================================================
	# POLA DLA AUTH (wspólne dla obu backendów)
	# =========================================================================
	
	auth_cert_file = fields.Binary(
		string='Certyfikat AUTH (.crt)',
		attachment=False,
		help='Plik certyfikat-api-auth.crt pobrany z aplikacji MF KSeF'
	)
	
	auth_cert_filename = fields.Char(
		string='Nazwa pliku AUTH cert',
		default='certyfikat-api-auth.crt'
	)
	
	auth_key_file = fields.Binary(
		string='Klucz prywatny AUTH (.key)',
		attachment=False,
		help='Plik certyfikat-api-auth.key pobrany z aplikacji MF KSeF'
	)
	
	auth_key_filename = fields.Char(
		string='Nazwa pliku AUTH key',
		default='certyfikat-api-auth.key'
	)
	
	auth_key_password = fields.Char(
		string='Hasło klucza AUTH',
		help='Hasło do klucza prywatnego (jeśli jest chroniony)'
	)
	
	# =========================================================================
	# POLA DLA SIGN (TYLKO DLA JAVA BACKEND)
	# =========================================================================
	
	sign_cert_file = fields.Binary(
		string='Certyfikat SIGN (.crt)',
		attachment=False,
		help='Plik certyfikat-api-sign.crt pobrany z aplikacji MF KSeF (wymagany dla Java)'
	)
	
	sign_cert_filename = fields.Char(
		string='Nazwa pliku SIGN cert',
		default='certyfikat-api-sign.crt'
	)
	
	sign_key_file = fields.Binary(
		string='Klucz prywatny SIGN (.key)',
		attachment=False,
		help='Plik certyfikat-api-sign.key pobrany z aplikacji MF KSeF (wymagany dla Java)'
	)
	
	sign_key_filename = fields.Char(
		string='Nazwa pliku SIGN key',
		default='certyfikat-api-sign.key'
	)
	
	sign_key_password = fields.Char(
		string='Hasło klucza SIGN',
		help='Hasło do klucza prywatnego (jeśli jest chroniony)'
	)
	
	# =========================================================================
	# STATUS
	# =========================================================================
	
	state = fields.Selection([
		('draft', 'W przygotowaniu'),
		('validating', 'Weryfikacja'),
		('converting', 'Konwersja'),
		('done', 'Zakończono'),
		('error', 'Błąd'),
	], default='draft', string='Status')
	
	error_message = fields.Text(string='Komunikat błędu', readonly=True)
	validation_log = fields.Text(string='Log walidacji', readonly=True)
	
	# Wyniki
	auth_p12_attachment_id = fields.Many2one('ir.attachment', string='AUTH .p12')
	sign_p12_attachment_id = fields.Many2one('ir.attachment', string='SIGN .p12')
	
	# =========================================================================
	# WALIDACJE DYNAMICZNE (w zależności od backendu)
	# =========================================================================
	
	@api.onchange('api_backend')
	def _onchange_api_backend(self):
		"""Przy zmianie backendu - czyść pola i dostosuj wymagania"""
		if self.api_backend == 'python':
			# Python wymaga tylko AUTH
			self.sign_cert_file = False
			self.sign_key_file = False
			self.sign_key_password = False
		# Dla Java pozostawiamy pola SIGN
	
	@api.constrains('p12_password', 'p12_password_confirm')
	def _check_passwords_match(self):
		for record in self:
			if record.p12_password != record.p12_password_confirm:
				raise ValidationError(_("Hasła nie są identyczne"))
			if len(record.p12_password) < 4:
				raise ValidationError(_("Hasło musi mieć co najmniej 4 znaki"))
	
	def _validate_required_files(self):
		"""Sprawdza czy wymagane pliki zostały załadowane"""
		# AUTH jest zawsze wymagany
		if not self.auth_cert_file:
			raise UserError(_("Certyfikat AUTH (.crt) jest wymagany"))
		if not self.auth_key_file:
			raise UserError(_("Klucz prywatny AUTH (.key) jest wymagany"))
		
		# Java wymaga dodatkowo SIGN
		if self.api_backend == 'java':
			if not self.sign_cert_file:
				raise UserError(_(
					"Dla backendu Java wymagany jest również certyfikat SIGN (.crt).\n"
					"Jeśli chcesz używać tylko jednego certyfikatu, wybierz backend Python."
				))
			if not self.sign_key_file:
				raise UserError(_(
					"Dla backendu Java wymagany jest również klucz prywatny SIGN (.key).\n"
					"Jeśli chcesz używać tylko jednego certyfikatu, wybierz backend Python."
				))
	
	# =========================================================================
	# METODY GŁÓWNE
	# =========================================================================
	
	def action_validate_and_convert(self):
		"""
		Główna akcja wizarda - walidacja i konwersja certyfikatów.
		"""
		self.ensure_one()
		
		# Sprawdź czy hasła są zgodne
		if self.p12_password != self.p12_password_confirm:
			raise UserError(_("Hasła nie są identyczne"))
		
		# Sprawdź wymagane pliki
		self._validate_required_files()
		
		# Zresetuj status
		self.write({
			'state': 'validating',
			'error_message': False,
			'validation_log': False,
		})
		
		log_entries = []
		temp_dir = None
		
		try:
			# ================================================================
			# KROK 1: Zapisz pliki tymczasowe
			# ================================================================
			log_entries.append("📁 [1/7] Zapisuję pliki tymczasowe...")
			self._update_log('\n'.join(log_entries))
			
			temp_dir = tempfile.mkdtemp(prefix='ksef_certs_')
			files = self._save_temp_files(temp_dir)
			
			log_entries.append(f"   → Katalog: {temp_dir}")
			log_entries.append(f"   → AUTH cert: {os.path.basename(files['auth_cert_path'])}")
			log_entries.append(f"   → AUTH key: {os.path.basename(files['auth_key_path'])}")
			
			if self.api_backend == 'java':
				log_entries.append(f"   → SIGN cert: {os.path.basename(files['sign_cert_path'])}")
				log_entries.append(f"   → SIGN key: {os.path.basename(files['sign_key_path'])}")
			
			self._update_log('\n'.join(log_entries))
			
			# ================================================================
			# KROK 2: Sprawdź algorytm certyfikatów (wymagany RSA)
			# ================================================================
			log_entries.append("\n🔍 [2/7] Sprawdzam algorytm certyfikatów...")
			self._update_log('\n'.join(log_entries))
			
			auth_algorithm = self._check_certificate_algorithm(files['auth_cert_path'])
			log_entries.append(f"   → AUTH algorytm: {auth_algorithm}")
			
			if auth_algorithm not in ['rsaEncryption', 'id-ecPublicKey']:
				raise UserError(_(
					"Certyfikat AUTH ma algorytm '%s'. "
					"KSeF wymaga algorytmu RSA (rsaEncryption). "
					"Wygeneruj nowy certyfikat RSA w aplikacji MF KSeF."
				) % auth_algorithm)
			
			if self.api_backend == 'java':
				sign_algorithm = self._check_certificate_algorithm(files['sign_cert_path'])
				log_entries.append(f"   → SIGN algorytm: {sign_algorithm}")
				
				if sign_algorithm not in ['rsaEncryption', 'id-ecPublicKey']:
					raise UserError(_(
						"Certyfikat SIGN ma algorytm '%s'. "
						"KSeF wymaga algorytmu RSA (rsaEncryption). "
						"Wygeneruj nowy certyfikat RSA w aplikacji MF KSeF."
					) % sign_algorithm)
			
			log_entries.append("   ✅ Algorytmy poprawne (RSA)")
			self._update_log('\n'.join(log_entries))
			
			# ================================================================
			# KROK 3: Konwertuj AUTH na .p12 (zawsze)
			# ================================================================
			log_entries.append("\n🔄 [3/7] Konwertuję AUTH na .p12...")
			self._update_log('\n'.join(log_entries))
			
			auth_p12_path = os.path.join(temp_dir, 'ksef-auth.p12')
			self._convert_to_p12(
				cert_path=files['auth_cert_path'],
				key_path=files['auth_key_path'],
				key_password=self.auth_key_password,
				p12_path=auth_p12_path,
				p12_password=self.p12_password,
				alias='ksef-auth'
			)
			log_entries.append("   ✅ AUTH .p12 utworzony")
			self._update_log('\n'.join(log_entries))
			
			# ================================================================
			# KROK 4: Konwertuj SIGN na .p12 (tylko dla Java)
			# ================================================================
			sign_p12_path = None
			
			if self.api_backend == 'java':
				log_entries.append("\n🔄 [4/7] Konwertuję SIGN na .p12...")
				self._update_log('\n'.join(log_entries))
				
				sign_p12_path = os.path.join(temp_dir, 'ksef-sign.p12')
				self._convert_to_p12(
					cert_path=files['sign_cert_path'],
					key_path=files['sign_key_path'],
					key_password=self.sign_key_password,
					p12_path=sign_p12_path,
					p12_password=self.p12_password,
					alias='ksef-sign'
				)
				log_entries.append("   ✅ SIGN .p12 utworzony")
				self._update_log('\n'.join(log_entries))
			
			# ================================================================
			# KROK 5: Weryfikuj pliki .p12
			# ================================================================
			log_entries.append("\n✅ [5/7] Weryfikuję pliki .p12...")
			self._update_log('\n'.join(log_entries))
			
			self._verify_p12(auth_p12_path, self.p12_password, 'ksef-auth')
			log_entries.append("   ✅ AUTH .p12 poprawny")
			
			if self.api_backend == 'java' and sign_p12_path:
				self._verify_p12(sign_p12_path, self.p12_password, 'ksef-sign')
				log_entries.append("   ✅ SIGN .p12 poprawny")
			
			self._update_log('\n'.join(log_entries))
			
			# ================================================================
			# KROK 6: Zapisz jako załączniki i zaktualizuj konfigurację
			# ================================================================
			log_entries.append("\n💾 [6/7] Zapisuję w systemie...")
			self._update_log('\n'.join(log_entries))
			
			# Usuń stare załączniki jeśli nadpisujemy
			if self.overwrite_existing:
				if self.config_id.auth_keystore_p12:
					self.config_id.auth_keystore_p12.unlink()
				if self.config_id.sign_keystore_p12:
					self.config_id.sign_keystore_p12.unlink()
			
			# Zapisz AUTH .p12
			auth_attachment = self._save_p12_as_attachment(
				p12_path=auth_p12_path,
				name='ksef_auth_certificate.p12',
				config=self.config_id
			)
			
			# Przygotuj wartości do aktualizacji konfiguracji
			update_vals = {
				'auth_keystore_p12': auth_attachment.id,
				'auth_keystore_password': self.p12_password,
				'api_backend': self.api_backend,  # ← KLUCZOWE: ustaw backend
			}
			
			# Dla Java dodaj również SIGN
			if self.api_backend == 'java' and sign_p12_path:
				sign_attachment = self._save_p12_as_attachment(
					p12_path=sign_p12_path,
					name='ksef_sign_certificate.p12',
					config=self.config_id
				)
				update_vals.update({
					'sign_keystore_p12': sign_attachment.id,
					'sign_keystore_password': self.p12_password,
				})
				self.write({'sign_p12_attachment_id': sign_attachment.id})
			else:
				# Dla Python - wyczyść pola SIGN jeśli istnieją
				update_vals.update({
					'sign_keystore_p12': False,
					'sign_keystore_password': False,
				})
			
			self.config_id.write(update_vals)
			
			log_entries.append("   ✅ Konfiguracja zaktualizowana")
			log_entries.append(f"   → Backend: {self.api_backend.upper()}")
			
			# ================================================================
			# KROK 7: Aktualizacja providera (jeśli istnieje)
			# ================================================================
			log_entries.append("\n🔧 [7/7] Aktualizuję providera komunikacji...")
			self._update_communication_provider()
			log_entries.append("   ✅ Provider zaktualizowany")
			
			log_entries.append("\n" + "="*50)
			log_entries.append(f"🎉 IMPORT ZAKOŃCZONY SUKCESEM! (Backend: {self.api_backend.upper()})")
			log_entries.append("="*50)
			self._update_log('\n'.join(log_entries))
			
			# Zapisz wyniki
			self.write({
				'state': 'done',
				'auth_p12_attachment_id': auth_attachment.id,
			})
			
			# Wyczyść pliki tymczasowe
			self._cleanup_temp_files(temp_dir)
			
			# Wyświetl komunikat sukcesu
			return self._show_success_message()
			
		except UserError as e:
			self.write({
				'state': 'error',
				'error_message': str(e),
				'validation_log': '\n'.join(log_entries) if log_entries else str(e),
			})
			if temp_dir:
				self._cleanup_temp_files(temp_dir)
			raise
			
		except Exception as e:
			_logger.error(f"KSeF Certificate import error: {e}", exc_info=True)
			self.write({
				'state': 'error',
				'error_message': str(e),
				'validation_log': '\n'.join(log_entries) if log_entries else str(e),
			})
			if temp_dir:
				self._cleanup_temp_files(temp_dir)
			raise UserError(_(
				"Wystąpił błąd podczas importu certyfikatów:\n\n%s\n\n"
				"Sprawdź log powyżej i upewnij się, że pliki są poprawne."
			) % str(e))
	
	def _update_communication_provider(self):
		"""
		Aktualizuje lub tworzy rekord communication.provider
		z odpowiednimi ustawieniami backendu.
		"""
		# Szukaj istniejącego providera
		provider = self.env['communication.provider'].search([
			('company_id', '=', self.config_id.company_id.id),
			('provider_type', '=', 'ksef'),
			('provider_config_id', '=', self.config_id.id),
		], limit=1)
		
		provider_vals = {
			'provider_type': 'ksef',
			'provider_config_id': self.config_id.id,
			'provider_model': 'communication.provider.ksef',
			'active': self.config_id.active,
		}
		
		if provider:
			provider.write(provider_vals)
		else:
			provider = self.env['communication.provider'].create({
				'name': f"KSeF Provider: {self.config_id.name}",
				'code': f"KSEF_{self.config_id.code}",
				**provider_vals
			})
		
		return provider
	
	# =========================================================================
	# METODY POMOCNICZE
	# =========================================================================
	
	def _save_temp_files(self, temp_dir):
		"""
		Zapisuje załączone pliki w katalogu tymczasowym.
		"""
		files = {}
		
		# AUTH cert
		if self.auth_cert_file:
			auth_cert_data = base64.b64decode(self.auth_cert_file)
			auth_cert_path = os.path.join(temp_dir, self.auth_cert_filename or 'auth.crt')
			with open(auth_cert_path, 'wb') as f:
				f.write(auth_cert_data)
			files['auth_cert_path'] = auth_cert_path
		
		# AUTH key
		if self.auth_key_file:
			auth_key_data = base64.b64decode(self.auth_key_file)
			auth_key_path = os.path.join(temp_dir, self.auth_key_filename or 'auth.key')
			with open(auth_key_path, 'wb') as f:
				f.write(auth_key_data)
			files['auth_key_path'] = auth_key_path
		
		# SIGN cert (tylko dla Java)
		if self.api_backend == 'java' and self.sign_cert_file:
			sign_cert_data = base64.b64decode(self.sign_cert_file)
			sign_cert_path = os.path.join(temp_dir, self.sign_cert_filename or 'sign.crt')
			with open(sign_cert_path, 'wb') as f:
				f.write(sign_cert_data)
			files['sign_cert_path'] = sign_cert_path
		
		# SIGN key (tylko dla Java)
		if self.api_backend == 'java' and self.sign_key_file:
			sign_key_data = base64.b64decode(self.sign_key_file)
			sign_key_path = os.path.join(temp_dir, self.sign_key_filename or 'sign.key')
			with open(sign_key_path, 'wb') as f:
				f.write(sign_key_data)
			files['sign_key_path'] = sign_key_path
		
		return files
	
	def _check_certificate_algorithm(self, cert_path):
		"""
		Sprawdza algorytm certyfikatu za pomocą openssl.
		
		Returns:
			str: 'rsaEncryption', 'id-ecPublicKey' lub inny
		"""
		try:
			cmd = [
				'openssl', 'x509', '-in', cert_path,
				'-text', '-noout'
			]
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=10
			)
			
			if result.returncode != 0:
				raise Exception(f"OpenSSL error: {result.stderr}")
			
			output = result.stdout
			
			# Szukaj "Public Key Algorithm:"
			match = re.search(r'Public Key Algorithm:\s*(\S+)', output)
			if match:
				return match.group(1)
			
			# Fallback: sprawdź czy to PEM
			with open(cert_path, 'r') as f:
				content = f.read()
				if 'BEGIN CERTIFICATE' not in content:
					raise Exception("Nieprawidłowy format certyfikatu")
			
			return 'unknown'
			
		except subprocess.TimeoutExpired:
			raise Exception("Timeout podczas sprawdzania certyfikatu")
		except Exception as e:
			raise Exception(f"Błąd sprawdzania algorytmu: {e}")
	
	def _convert_to_p12(self, cert_path, key_path, key_password, p12_path, p12_password, alias):
		"""
		Konwertuje certyfikat i klucz na plik .p12.
		"""
		# Sprawdź czy pliki istnieją
		if not os.path.exists(cert_path):
			raise Exception(f"Plik certyfikatu nie istnieje: {cert_path}")
		if not os.path.exists(key_path):
			raise Exception(f"Plik klucza nie istnieje: {key_path}")
		
		# Buduj polecenie openssl
		cmd = [
			'openssl', 'pkcs12', '-export',
			'-inkey', key_path,
			'-in', cert_path,
			'-name', alias,
			'-out', p12_path,
			'-passout', f'pass:{p12_password}'
		]
		
		# Dodaj hasło klucza jeśli podane
		if key_password:
			cmd.extend(['-passin', f'pass:{key_password}'])
		else:
			cmd.extend(['-passin', 'pass:'])
		
		try:
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=30
			)
			
			if result.returncode != 0:
				error_msg = result.stderr
				if 'Mac verify error' in error_msg or 'bad decrypt' in error_msg:
					raise Exception("Nieprawidłowe hasło klucza prywatnego")
				raise Exception(f"OpenSSL error: {error_msg}")
			
			if not os.path.exists(p12_path) or os.path.getsize(p12_path) == 0:
				raise Exception("Plik .p12 nie został utworzony lub jest pusty")
				
		except subprocess.TimeoutExpired:
			raise Exception("Timeout podczas konwersji na .p12")
		except Exception as e:
			raise Exception(f"Błąd konwersji na .p12: {e}")
	
	def _verify_p12(self, p12_path, password, expected_alias):
		"""
		Weryfikuje plik .p12 za pomocą keytool lub openssl.
		"""
		# Metoda 1: keytool (preferowana)
		try:
			cmd = [
				'keytool', '-list', '-v',
				'-storetype', 'PKCS12',
				'-keystore', p12_path,
				'-storepass', password
			]
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=15
			)
			
			if result.returncode != 0:
				return self._verify_p12_openssl(p12_path, password, expected_alias)
			
			output = result.stdout
			
			# Sprawdź alias
			if expected_alias not in output:
				raise Exception(f"Alias '{expected_alias}' nie znaleziony w .p12")
			
			# Sprawdź PrivateKeyEntry
			if 'PrivateKeyEntry' not in output:
				raise Exception("Plik .p12 nie zawiera klucza prywatnego")
			
			return True
			
		except subprocess.TimeoutExpired:
			return self._verify_p12_openssl(p12_path, password, expected_alias)
		except Exception as e:
			return self._verify_p12_openssl(p12_path, password, expected_alias)
	
	def _verify_p12_openssl(self, p12_path, password, expected_alias):
		"""
		Weryfikuje plik .p12 za pomocą openssl (fallback).
		"""
		try:
			# Sprawdź czy możemy odczytać certyfikat
			cmd = [
				'openssl', 'pkcs12', '-in', p12_path,
				'-nokeys', '-passin', f'pass:{password}'
			]
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=15
			)
			
			if result.returncode != 0:
				raise Exception(f"Nie można odczytać .p12: {result.stderr}")
			
			if 'BEGIN CERTIFICATE' not in result.stdout:
				raise Exception("Plik .p12 nie zawiera certyfikatu")
			
			# Sprawdź czy klucz jest obecny
			cmd_key = [
				'openssl', 'pkcs12', '-in', p12_path,
				'-nocerts', '-nodes', '-passin', f'pass:{password}'
			]
			result_key = subprocess.run(
				cmd_key,
				capture_output=True,
				text=True,
				timeout=15
			)
			
			if result_key.returncode != 0:
				raise Exception("Nie można odczytać klucza z .p12")
			
			if 'BEGIN PRIVATE KEY' not in result_key.stdout and 'BEGIN RSA PRIVATE KEY' not in result_key.stdout:
				raise Exception("Plik .p12 nie zawiera klucza prywatnego")
			
			return True
			
		except subprocess.TimeoutExpired:
			raise Exception("Timeout podczas weryfikacji .p12")
		except Exception as e:
			raise Exception(f"Weryfikacja .p12 nie powiodła się: {e}")
	
	def _save_p12_as_attachment(self, p12_path, name, config):
		"""
		Zapisuje plik .p12 jako załącznik.
		"""
		with open(p12_path, 'rb') as f:
			p12_data = f.read()
		
		# Utwórz nowy załącznik
		attachment = self.env['ir.attachment'].create({
			'name': name,
			'datas': base64.b64encode(p12_data),
			'res_model': 'communication.provider.ksef',
			'res_id': config.id,
			'type': 'binary',
			'mimetype': 'application/x-pkcs12',
		})
		
		return attachment
	
	def _cleanup_temp_files(self, temp_dir):
		"""
		Usuwa katalog tymczasowy i jego zawartość.
		"""
		try:
			import shutil
			if os.path.exists(temp_dir):
				shutil.rmtree(temp_dir)
				_logger.info(f"Cleaned up temp directory: {temp_dir}")
		except Exception as e:
			_logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")
	
	def _update_log(self, log_text):
		"""
		Aktualizuje pole validation_log.
		"""
		self.write({'validation_log': log_text})
		self.env.cr.commit()
	
	def _show_success_message(self):
		"""
		Wyświetla komunikat sukcesu.
		"""
		if self.api_backend == 'python':
			message = _(
				'✅ Import zakończony sukcesem! (Backend: Python)\n\n'
				'Utworzono:\n'
				'• AUTH .p12: %s\n\n'
				'Hasło dla .p12: [zachowane]\n'
				'Alias: ksef-auth\n\n'
				'⚠️ Uwaga: Dla backendu Python wystarczy jeden certyfikat.\n'
				'System będzie samodzielnie podpisywał dokumenty.'
			) % (self.auth_p12_attachment_id.name if self.auth_p12_attachment_id else 'N/A')
		else:
			message = _(
				'✅ Import zakończony sukcesem! (Backend: Java)\n\n'
				'Utworzono:\n'
				'• AUTH .p12: %s\n'
				'• SIGN .p12: %s\n\n'
				'Hasło dla obu plików: [zachowane]\n'
				'Alias AUTH: ksef-auth\n'
				'Alias SIGN: ksef-sign\n\n'
				'⚠️ Uwaga: Dla backendu Java wymagane są oba certyfikaty.\n'
				'Java JAR będzie używał SIGN do podpisywania dokumentów.'
			) % (
				self.auth_p12_attachment_id.name if self.auth_p12_attachment_id else 'N/A',
				self.sign_p12_attachment_id.name if self.sign_p12_attachment_id else 'N/A'
			)
		
		return {
			'type': 'ir.actions.client',
			'tag': 'display_notification',
			'params': {
				'title': _('Import certyfikatów zakończony sukcesem'),
				'message': message,
				'type': 'success',
				'sticky': False,
			}
		}
	
	# =========================================================================
	# AKCJE
	# =========================================================================
	
	def action_cancel(self):
		"""Anuluj wizard."""
		return {'type': 'ir.actions.act_window_close'}
	
	def action_open_config(self):
		"""Otwórz konfigurację KSeF po zakończeniu."""
		return {
			'type': 'ir.actions.act_window',
			'res_model': 'communication.provider.ksef',
			'res_id': self.config_id.id,
			'view_mode': 'form',
			'target': 'current',
		}

#EoF

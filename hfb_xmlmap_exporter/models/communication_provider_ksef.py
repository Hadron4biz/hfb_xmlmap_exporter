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
"""@version 18.1.0
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
#################################################################################
#   Provider KSeF – kompletna obsługa Java JAR z cron i ścieżką konfiguracyjną
#################################################################################
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
import re
import os
import json
from lxml import etree
import base64
import subprocess
import tempfile
import logging
import uuid
import psycopg2
from pathlib import Path
import time
import signal
import requests

from .communication_provider_ksef_apiservice import ProviderKsefApiService
from .communication_provider_ksef_apiservice import ProviderXadesSigner

_logger = logging.getLogger(__name__)

# =============================================================================
# Rozszerzenie CommunicationLog dla KSeF
# =============================================================================
class CommunicationLog(models.Model):
	_inherit = "communication.log"

	# ---------------------------------------------------------------
	# Dane kryptograficzne sesji (wymagane dla Python full flow)
	# ---------------------------------------------------------------
	ksef_session_key = fields.Binary(
		string="KSeF Session AES Key",
		readonly=True
	)

	ksef_session_iv = fields.Binary(
		string="KSeF Session IV",
		readonly=True
	)

	# ---------------------------------------------------------------
	# Techniczny status API
	# ---------------------------------------------------------------
	ksef_http_status = fields.Integer(
		string="HTTP Status",
		readonly=True
	)

	ksef_api_status_code = fields.Integer(
		string="KSeF API Status Code",
		readonly=True
	)

	ksef_api_status_message = fields.Text(
		string="KSeF API Status Message",
		readonly=True
	)

	# ---------------------------------------------------------------
	# Metadane odpowiedzi
	# ---------------------------------------------------------------
	ksef_sent_datetime = fields.Datetime(
		string="KSeF Sent Datetime",
		readonly=True
	)

	ksef_processing_code = fields.Char(
		string="KSeF Processing Code",
		readonly=True
	)

	# ------------------------------------------------------------------------
	# ============================================================
	# 1. TOKENY OAUTH (PYTHON BACKEND)
	# ============================================================
	ksef_access_token = fields.Char(
		string="KSeF Access Token",
		groups="base.group_system",
		copy=False,
		help="Access token używany do autoryzacji żądań API KSeF (Python backend)."
	)

	ksef_access_token_valid_until = fields.Datetime(
		string="Access Token Valid Until",
		groups="base.group_system",
		copy=False,
		help="Data i czas wygaśnięcia access token."
	)

	ksef_refresh_token = fields.Char(
		string="KSeF Refresh Token",
		groups="base.group_system",
		copy=False,
		help="Refresh token używany do odświeżania access token."
	)

	ksef_refresh_token_valid_until = fields.Datetime(
		string="Refresh Token Valid Until",
		groups="base.group_system",
		copy=False,
		help="Data i czas wygaśnięcia refresh token."
	)

	ksef_last_auth_datetime = fields.Datetime(
		string="Last Authentication",
		groups="base.group_system",
		copy=False,
		help="Data ostatniej pełnej autoryzacji (auth)."
	)

	ksef_last_refresh_datetime = fields.Datetime(
		string="Last Token Refresh",
		groups="base.group_system",
		copy=False,
		help="Data ostatniego odświeżenia tokena (refresh)."
	)

	# ============================================================
	# 2. SESJA KSeF (JEŚLI OBSŁUGIWANA W PYTHON)
	# ============================================================
	ksef_session_token = fields.Char(
		string="KSeF Session ID",
		groups="base.group_system",
		copy=False,
		help="Identyfikator bieżącej sesji KSeF."
	)

	ksef_session_valid_until = fields.Datetime(
		string="Session Valid Until",
		groups="base.group_system",
		copy=False,
		help="Data wygaśnięcia sesji KSeF."
	)

	ksef_session_key = fields.Binary(
		string="Session AES Key",
		groups="base.group_system",
		copy=False,
		help="Klucz symetryczny AES używany do szyfrowania faktur w sesji."
	)

	ksef_session_iv = fields.Binary(
		string="Session IV",
		groups="base.group_system",
		copy=False,
		help="Wektor inicjujący AES dla sesji KSeF."
	)

	# =========================================================================
	# IMPORT XML DO ODOO w pliku _addons
	# =========================================================================
	def map_invoice_type(rodzaj):
		mapping = {
			"VAT": "in_invoice",
			"ZAL": "in_invoice",  # ale z adnotacją zaliczki
			"ROZ": "in_invoice",  # ale z adnotacją rozliczeniowa
			"UPR": "in_invoice",  # ale state=draft
			"KOR": "in_refund",
			"KOR_ZAL": "in_refund",
			"KOR_ROZ": "in_refund"
		}
		return mapping.get(rodzaj, "in_invoice")

	# ✅ invoiceHash 
	ksef_invoice_hash = fields.Char(
		string='KSeF Invoice Hash (SHA-256 Base64)',
		help='SHA-256 hash oryginalnego XML użyty przy wysyłce do KSeF (Base64)',
		tracking=True
	)

	invoice_hash = fields.Char(related='ksef_invoice_hash')

	# ============================================
	# Pełna tabela zgodna z dokumentacją KSeF 
	#	-> 💡 do uzupełnienia
	# ============================================
	KSEF_STATUS_MAPPING = {
		# Sesja interaktywna
		100: {'state': 'sent', 'method': 'mark_status_checked', 'desc': 'Sesja OTWARTA - przyjmuje faktury'},
		110: {'state': 'sent', 'method': 'mark_status_checked', 'desc': 'Sesja ZAMKNIĘTA - generowanie UPO w toku'},
		120: {'state': 'sent', 'method': 'mark_status_checked', 'desc': 'UPO gotowe do pobrania'},
		130: {'state': 'error', 'method': 'mark_error', 'desc': 'Sesja ODRZUCONA - błąd'},
		140: {'state': 'error', 'method': 'mark_error', 'desc': 'Sesja ANULOWANA'},
		200: {'state': 'sent', 'method': 'mark_status_checked', 'desc': 'Sesja przetworzona'},
		# Statusy faktur (jeśli będziemy je sprawdzać)
		300: {'state': 'sent', 'method': 'mark_status_checked', 'desc': 'Faktura przyjęta do przetwarzania'},
		310: {'state': 'sent', 'method': 'mark_status_checked', 'desc': 'Faktura przetwarzana'},
		320: {'state': 'received', 'method': 'mark_received', 'desc': 'Faktura przetworzona pomyślnie'},
		330: {'state': 'error', 'method': 'mark_error', 'desc': 'Faktura odrzucona'},
		# Kody błędu weryfikacji faktur (440-459)
		440: {'state': 'error', 'method': 'mark_error', 'desc': 'Sesja bez faktur'},
		441: {'state': 'error', 'method': 'mark_error', 'desc': 'Przekroczono limit faktur w sesji'},
		442: {'state': 'error', 'method': 'mark_error', 'desc': 'Nieprawidłowy format faktury'},
		443: {'state': 'error', 'method': 'mark_error', 'desc': 'Błąd walidacji XML'},
		444: {'state': 'error', 'method': 'mark_error', 'desc': 'Błąd podpisu cyfrowego'},
		445: {'state': 'error', 'method': 'mark_error', 'desc': 'Błąd weryfikacji, brak poprawnych faktur'},
		446: {'state': 'error', 'method': 'mark_error', 'desc': 'Niezgodność danych faktury'},
	}
		
	# ============================================
	# POLA DO STEROWANIA SEKWENCJĄ KSeF
	# ============================================
	
	ksef_operation = fields.Selection([
		('auth', 'Autoryzacja'),
		('open_session', 'Otwarcie sesji'),
		('send_invoice', 'Wysłanie faktury'),
		('check_status', 'Sprawdzenie statusu'),
		('download_upo', 'Pobranie UPO'),
		('close_session', 'Zamknięcie sesji'),
		('import_list', 'Import listy faktur'),
		('import_invoice', 'Import faktury'),
		('import_invoices', 'Import faktur'),
		('restore_invoice','Odtwarzanie Faktury'),
		('completed', 'Zakończono'),
		('failed', 'Niepowodzenie'),
		], 
		string="Bieżąca operacja", 
		tracking=True,
		default='auth')
	
	ksef_next_operation = fields.Selection([
		('auth', 'Autoryzacja'),
		('open_session', 'Otwarcie sesji'),
		('send_invoice', 'Wysłanie faktury'),
		('check_status', 'Sprawdzenie statusu'),
		('download_upo', 'Pobranie UPO'),
		('close_session', 'Zamknięcie sesji'),
		('import_list', 'Import listy faktur'),
		('import_invoice', 'Import faktury'),
		('import_invoices', 'Import faktur'),
		('restore_invoice','Odtwarzanie Faktury'),
		('completed', 'Zakończono'),
		('failed', 'Niepowodzenie'),
		('none', 'Brak następnej'),
		], 
		string="Proces Następny", 
		tracking=True,
		default='open_session')

	ksef_invoice_list = fields.Json('Lista Metadanych')
	ksef_discovered_count = fields.Integer('ile znaleziono')
	ksef_created_jobs = fields.Integer('ile zadań utworzono')
	ksef_target_number = fields.Char('Nr KSeF do pobrania')
	ksef_source_list_id = fields.Many2one('communication.log') # link do rekordu listy
	ksef_import_params = fields.Json(
		string="Parametry importu",
		help="JSON z parametrami importu (date_range, filters, etc.)"
	)

	# ============================================
	# POLA KONFIGURACJI IMPORTU FAKTUR
	# ============================================
	
	ksef_import_days_back = fields.Integer(
		string="Importuj z ostatnich (dni)",
		default=60,
		help="Z ilu ostatnich dni pobierać faktury"
	)
	
	ksef_import_page_size = fields.Integer(
		string="Rozmiar strony paginacji",
		default=50,
		help="Ilość faktur na stronę (max 100)"
	)
	
	ksef_download_all = fields.Boolean(
		string="Pobierz wszystkie faktury",
		default=False,
		help="Pobierz pełne XML faktur razem z listą"
	)
	
	ksef_download_dir = fields.Char(
		string="Katalog pobierania",
		default="/tmp/ksef_invoices",
		help="Ścieżka do zapisu pobranych faktur XML"
	)

	ksef_import_mode = fields.Selection([
		('list_only', 'Tylko lista metadanych'),
		('single_document', 'Pojedynczy dokument'),
		('batch_download', 'Batch download'),
	], string="Tryb importu", default='list_only')
	
	# pola dla obsługi stanów:
	ksef_status = fields.Selection([
		('pending', 'Oczekuje na wykonanie'),
		('in_progress', 'W trakcie wykonywania'),
		('success', 'Sukces'),
		('failed', 'Błąd'),
		('waiting_delay', 'Oczekuje na opóźnienie MF'),
		], 
		string="Status operacji KSeF", 
		tracking=True,
		default='pending')
	
	# Historia wykonanych kroków (do debugowania)
	ksef_history = fields.Json(
		string="Historia kroków KSeF",
		default=[],
		help="Lista wykonanych operacji z timestampami i statusami"
	)

	# Relacja hierarchiczna
	parent_id = fields.Many2one(
		'communication.log', 
		string="Parent Log", 
		ondelete='cascade'
	)

	child_ids = fields.One2many(
		'communication.log', 
		'parent_id', 
		string="Child Operations"
	)

	ksef_import_date = fields.Datetime(
		string="Data importu KSeF"
	)
	
	# Link do utworzonego dokumentu
	import_move_id = fields.Many2one(
		'account.move', 
		string="Imported Invoice", 
		compute='_compute_import_move_id', 
		store=True
	)

	@api.depends('document_model', 'document_id')
	def _compute_import_move_id(self):
		for log in self:
			if log.document_model == 'account.move' and log.document_id:
				log.import_move_id = log.document_id
			else:
				log.import_move_id = False

	# ============================================
	# POLA DO STEROWANIA SEKWENCJĄ KSeF (ZACHOWUJEMY WSZYSTKIE!)
	# ============================================
	
	# 1. IDENTYFIKATORY KSeF (krytyczne)
	ksef_reference_number = fields.Char(string="Numer referencyjny KSeF", tracking=True)
	ksef_session_token = fields.Char(string="Token sesji KSeF")
	ksef_invoice_number = fields.Char(string="Numer faktury KSeF")
	
	# 4. RETRY LOGIC (już istniejące - zachowujemy)
	ksef_retry_count = fields.Integer(string="Liczba ponownych prób", default=0)
	ksef_max_retries = fields.Integer(string="Maksymalna liczba prób", default=3)
	
	# 5. SCHEDULING (już istniejące - zachowujemy)
	ksef_last_execution = fields.Datetime(string="Ostatnie wykonanie")
	ksef_next_execution = fields.Datetime(
		string="Następne wykonanie",
		default=lambda self: fields.Datetime.now()
	)
	
	# 6. LOCKING FIELDS (już istniejące - zachowujemy)
	is_processing = fields.Boolean(string="W trakcie przetwarzania", default=False)
	processing_lock_until = fields.Datetime(string="Blokada do")
	processing_pid = fields.Integer(string="PID procesu")
	
	# 7. RUNTIME DATA (już istniejące - zachowujemy)
	session_runtime = fields.Text(string="Session Runtime JSON")
	payload_context = fields.Text(string="Kontekst wykonania")


	# ============================================
	# METODY DO OBSŁUGI JAVA REQUEST/RESPONSE
	# ============================================
	
	def store_java_request(self, payload_request):
		"""
		Zapisuje surowe dane wejściowe przekazane do procesu Java.
		
		Args:
			payload_request (str): JSON lub inna serializacja danych wejściowych
		"""
		self.ensure_one()
		
		# Ogranicz długość zapisywanych danych (np. do 1MB)
		max_length = 1048576  # 1MB
		
		if payload_request and len(payload_request) > max_length:
			# Zapisz tylko początek + informację o przycięciu
			truncated = payload_request[:max_length]
			self.write({
				"payload_request": truncated + f"\n\n[TRUNCATED - original {len(payload_request)} chars]",
				"provider_message": (self.provider_message or "") + 
								   f"\nJava request truncated to {max_length} chars",
			})
		else:
			self.write({
				"payload_request": payload_request,
			})
		
		_logger.debug(f"[KSeF] Stored Java request for log {self.id}, length: {len(payload_request) if payload_request else 0}")
	
	def store_java_response(self, payload_response):
		"""
		Zapisuje surową odpowiedź zwróconą przez proces Java.
		
		Args:
			payload_response (str): Surowa odpowiedź z procesu Java
		"""
		self.ensure_one()
		
		# Ogranicz długość zapisywanych danych
		max_length = 2097152  # 2MB dla response (może być większy)
		
		if payload_response and len(payload_response) > max_length:
			# Dla response staramy się zachować więcej danych
			# Zapisujemy początek i koniec
			first_part = payload_response[:max_length//2]
			last_part = payload_response[-max_length//4:]
			truncated = first_part + f"\n\n[... TRUNCATED {len(payload_response) - len(first_part) - len(last_part)} chars ...]\n\n" + last_part
			
			self.write({
				"payload_response": truncated + f"\n\n[TRUNCATED - original {len(payload_response)} chars]",
				"provider_message": (self.provider_message or "") + 
								   f"\nJava response truncated to {len(truncated)} chars",
			})
		else:
			self.write({
				"payload_response": payload_response,
			})
		
		_logger.debug(f"[KSeF] Stored Java response for log {self.id}, length: {len(payload_response) if payload_response else 0}")

	def parse_java_response_to_context(self):
		"""
		Parsuje odpowiedź procesu Java.
		"""
		self.ensure_one()
		
		if not self.payload_response:
			return False
		
		try:
			data = json.loads(self.payload_response)
			
			# DEBUG - zawsze loguj co otrzymaliśmy
			_logger.info(f"[KSeF] Parsing response, success: {data.get('success')}")
			
			# Budujemy kontekst
			ctx = {}
			
			# Tylko aktualizuj jeśli nie jest None
			if data.get('runtime'):
				ctx['runtime'] = data['runtime']
			
			if data.get('context'):  # <--- SPRAWDŹ CZY NIE JEST None!
				ctx.update(data['context'])
			
			if data.get('tokens'):
				ctx['tokens'] = data['tokens']
			
			# Zapisz error jeśli wystąpił
			if not data.get('success') and data.get('error'):
				error_msg = data['error']
				ctx['error'] = error_msg
				_logger.error(f"[KSeF] Operation failed: {error_msg}")
			
			# Zapisz context jeśli coś znaleźliśmy
			if ctx:
				self.write({
					"payload_context": json.dumps(ctx, ensure_ascii=False, indent=2),
				})
				return True
			else:
				return False
				
		except json.JSONDecodeError as e:
			_logger.error(f"[KSeF] JSON parse error: {e}")
			return False
		except Exception as e:
			_logger.error(f"[KSeF] Parse error: {e}", exc_info=True)
			return False

	# =======================================================================================
	# METODY POMOCNIOCZE DLA CRON - Powiadomienia
	#	architektura cronów
	#
	#	cron_process_ksef_queue
	#			│
	#			└─ obsługa communication.log
	#
	#	cron_ksef_environment_check
	#			│
	#			└─ monitoring API KSeF
	#
	#	cron_ksef_daily_report
	#			│
	#			└─ raport operacyjny
	#
	# =======================================================================================

	def _get_notification_recipient(self, provider):
		"""
		Zwraca partnera do powiadomień - najpierw szuka alert_contact_id w konfiguracji KSeF,
		potem administratora systemu (z reguły user_root).
		"""
		# 1. Próba pobrania z konfiguracji KSeF
		ksef_config = provider._get_ksef_config()
		if ksef_config and ksef_config.alert_contact_id and ksef_config.alert_contact_id.email:
			return ksef_config.alert_contact_id
		
		# 2. Fallback - administrator systemu (użytkownik o ID 2 - admin, lub root)
		admin_partner = self.env.ref('base.user_root').partner_id
		if admin_partner and admin_partner.email:
			_logger.info(f"[KSeF Notify] Using system administrator as fallback for provider {provider.name}")
			return admin_partner
		
		# 3. Ostateczność - pierwszy aktywny użytkownik z uprawnieniami administratora
		admin_user = self.env['res.users'].search([
			('company_id', '=', self.company_id.id ),
			('share', '=', False),  # Nie portal
			('active', '=', True)
		], order='id', limit=1)
		
		if admin_user and admin_user.partner_id.email:
			return admin_user.partner_id
		
		return False

	def _notify_ksef_failure(self, provider, logs):
		"""
		Wysyła powiadomienie e-mail o problemach z komunikacją KSeF.
		"""
		recipient = self._get_notification_recipient(provider)
		if not recipient:
			_logger.error(f"[KSeF Notify] CANNOT SEND: No recipient found for provider {provider.name}")
			return

		body = f"""
		<h3>Wykryto problemy w komunikacji KSeF dla providera: {provider.name}</h3>
		<p>Poniższe zadania wymagają uwagi:</p>
		<table border="1" cellpadding="5" style="border-collapse: collapse;">
			<tr>
				<th>ID Logu</th>
				<th>Operacja</th>
				<th>Stan (state)</th>
				<th>Status KSeF</th>
				<th>L. prób (retry)</th>
				<th>Dokument</th>
				<th>Komunikat</th>
			</tr>
		"""

		for log in logs[:50]:  # Limit 50 logów na mail
			body += f"""
			<tr>
				<td>{log.id}</td>
				<td>{log.ksef_operation}</td>
				<td>{log.state}</td>
				<td>{log.ksef_status}</td>
				<td>{log.ksef_retry_count}/{log.ksef_max_retries}</td>
				<td>{log.document_model}:{log.document_id}</td>
				<td>{log.provider_message or ''}</td>
			</tr>
			"""

		body += "</table>"
		if len(logs) > 50:
			body += f"<p><em>... oraz {len(logs) - 50} innych wpisów.</em></p>"
		
		# Dodaj informację o fallbacku jeśli używamy administratora
		if not provider._get_ksef_config() or not provider._get_ksef_config().alert_contact_id:
			body += """
			<p style="color: orange;">
				<strong>⚠️  Uwaga:</strong> To powiadomienie zostało wysłane na adres administratora systemu, 
				ponieważ nie skonfigurowano dedykowanego kontaktu alarmowego dla tego providera. 
				Dodaj kontakt w konfiguracji KSeF, aby otrzymywać powiadomienia na właściwy adres.
			</p>
			"""

		mail = self.env['mail.mail'].with_company(self.company_id).create({
			'subject': f'🚨 KSeF – Alert komunikacji ({provider.name})',
			'body_html': body,
			'email_to': recipient.email,
			'email_from': self.env.company.email or self.env.user.email,
		})
		mail.send()
		_logger.info(f"[KSeF Notify] Alert sent to {recipient.email} for {len(logs)} logs.")


	def _send_ksef_daily_report(self, provider, stats, logs):
		"""
		Wysyła raport dzienny e-mailem.
		"""
		recipient = self._get_notification_recipient(provider)
		if not recipient:
			_logger.error(f"[KSeF Report] CANNOT SEND: No recipient found for provider {provider.name}")
			return

		body = f"""
		<h3>📊 Raport dzienny komunikacji KSeF dla providera: {provider.name}</h3>
		<p>Okres: Ostatnie 24 godziny</p>

		<h4>Podsumowanie:</h4>
		<ul>
			<li><strong>Wysłane faktury (sukces):</strong> {stats['sent']}</li>
			<li><strong>Błędy wysyłki:</strong> {stats['send_errors']}</li>
			<li><strong>Zaimportowane faktury (sukces):</strong> {stats['imported']}</li>
			<li><strong>Błędy importu:</strong> {stats['import_errors']}</li>
			<li><strong>Operacje z ponownymi próbami (retry):</strong> {stats['retry']}</li>
		</ul>

		<h4>Szczegóły (pierwsze 20 logów):</h4>
		<table border="1" cellpadding="5" style="border-collapse: collapse;">
			<tr>
				<th>ID</th>
				<th>Operacja</th>
				<th>Stan</th>
				<th>Status KSeF</th>
				<th>L. prób</th>
				<th>Dokument</th>
				<th>Utworzono</th>
			</tr>
		"""

		for log in logs[:20]:
			body += f"""
			<tr>
				<td>{log.id}</td>
				<td>{log.ksef_operation}</td>
				<td>{log.state}</td>
				<td>{log.ksef_status}</td>
				<td>{log.ksef_retry_count}</td>
				<td>{log.document_model}:{log.document_id}</td>
				<td>{log.create_date}</td>
			</tr>
			"""

		body += "</table>"
		if len(logs) > 20:
			body += f"<p><em>... oraz {len(logs) - 20} innych wpisów.</em></p>"
		
		# Dodaj informację o fallbacku jeśli potrzeba
		if not provider._get_ksef_config() or not provider._get_ksef_config().alert_contact_id:
			body += """
			<p style="color: orange;">
				<strong>⚠️  Uwaga:</strong> Raport został wysłany na adres administratora systemu, 
				ponieważ nie skonfigurowano dedykowanego kontaktu dla tego providera. 
				Aby zmienić adres odbiorcy, dodaj kontakt alarmowy w konfiguracji KSeF.
			</p>
			"""

		mail = self.env['mail.mail'].with_company(self.company_id).create({
			'subject': f'📊 KSeF – Raport dzienny ({provider.name})',
			'body_html': body,
			'email_to': recipient.email,
			'email_from': self.env.company.email or self.env.user.email,
		})
		mail.send()
		_logger.info(f"[KSeF Report] Report sent to {recipient.email}")


	def _notify_ksef_environment_alert(self, provider, message):
		"""
		Wysyła powiadomienie o problemie ze środowiskiem KSeF.
		"""
		recipient = self._get_notification_recipient(provider)
		if not recipient:
			_logger.error(f"[KSeF Env Alert] CANNOT SEND: No recipient found for provider {provider.name}")
			return

		body = f"""
		<h3>⚠️  Problem z dostępnością środowiska KSeF</h3>
		<p><strong>Provider:</strong> {provider.name}</p>
		<p><strong>URL:</strong> {provider.base_url}</p>
		<p><strong>Szczegóły błędu:</strong></p>
		<pre style="background-color: #f8f8f8; padding: 10px; border-radius: 5px;">{message}</pre>
		<p>Sprawdź konfigurację providera i połączenie sieciowe.</p>
		"""
		
		# Dodaj informację o fallbacku jeśli potrzeba
		if not provider._get_ksef_config() or not provider._get_ksef_config().alert_contact_id:
			body += """
			<p style="color: orange;">
				<strong>⚠️  Uwaga:</strong> To powiadomienie zostało wysłane na adres administratora systemu. 
				Skonfiguruj dedykowany kontakt alarmowy w ustawieniach KSeF, 
				aby otrzymywać powiadomienia na właściwy adres.
			</p>
			"""

		mail = self.env['mail.mail'].with_company(self.company_id).create({
			'subject': f'⚠️  KSeF – Problem środowiska ({provider.name})',
			'body_html': body,
			'email_to': recipient.email,
			'email_from': self.env.company.email or self.env.user.email,
		})
		mail.send()
		_logger.info(f"[KSeF Env Alert] Alert sent to {recipient.email}")
	
	# =======================================================================================
	# METODY CRON DLA KSeF - Kontrola zadań w kolejce
	# =======================================================================================

	@api.model
	def cron_ksef_monitor_failures(self):
		"""
		Monitoruje zadania KSeF, które utknęły lub wielokrotnie próbowały.
		"""
		_logger.info("[KSeF Monitor] Starting failure monitoring")
		now = fields.Datetime.now()

		# 1. Zadania zablokowane (is_processing=True) na dłużej niż 30 minut
		stuck_logs = self.search([
			('provider_id.provider_type', '=', 'ksef'),
			('is_processing', '=', True),
			('processing_lock_until', '<', now),  # Blokada wygasła
			('write_date', '<', now - timedelta(minutes=30))  # Nieaktualizowane od 30 min
		])

		# 2. Zadania w kolejce (queued), które nie zostały podjęte przez 2 godziny
		delayed_logs = self.search([
			('provider_id.provider_type', '=', 'ksef'),
			('state', '=', 'queued'),
			('ksef_next_execution', '<', now - timedelta(hours=2)),
		])

		# 3. Zadania, które przekroczyły limit ponownych prób
		#	Używamy ksef_retry_count >= ksef_max_retries i nie są w stanie 'error'/'failed'
		retry_logs = self.search([
			('provider_id.provider_type', '=', 'ksef'),
			#('ksef_retry_count', '>=', fields.fields.Float(compute=False)), 
			('state', 'not in', ['error', 'done', 'received']),
			('ksef_status', 'not in', ['failed', 'success'])
		]).filtered(lambda l: l.ksef_retry_count >= l.ksef_max_retries)

		logs_to_notify = (stuck_logs | delayed_logs | retry_logs)
		if not logs_to_notify:
			_logger.info("[KSeF Monitor] No failures found.")
			return

		# Grupuj po providerze, aby wysłać jedno powiadomienie na provider
		providers = logs_to_notify.mapped('provider_id')
		for provider in providers:
			provider_logs = logs_to_notify.filtered(lambda l: l.provider_id == provider)
			self._notify_ksef_failure(provider, provider_logs)

		_logger.info(f"[KSeF Monitor] Notifications sent for {len(providers)} providers.")


	# =======================================================================================
	# METODY CRON DLA KSeF - Raport Dzienny
	# =======================================================================================

	@api.model
	def cron_ksef_daily_report(self):
		"""
		Generuje i wysyła dzienny raport aktywności KSeF.
		"""
		_logger.info("[KSeF Report] Generating daily report")
		now = fields.Datetime.now()
		date_from = now - timedelta(hours=24)

		logs = self.search([
			('provider_id.provider_type', '=', 'ksef'),
			('create_date', '>=', date_from)
		])

		# Grupuj po providerze
		providers = logs.mapped('provider_id')
		for provider in providers:
			provider_logs = logs.filtered(lambda l: l.provider_id == provider)

			# Pobierz konfigurację KSeF i kontakt
			ksef_config = provider._get_ksef_config()
			if not ksef_config or not ksef_config.alert_contact_id:
				_logger.warning(f"[KSeF Report] No alert contact for provider {provider.name}")
				continue
	
			# Oblicz statystyki dla tego providera
			stats = {
				'sent': provider_logs.filtered(lambda l: l.ksef_operation == 'send_invoice' and l.ksef_status == 'success'),
				'send_errors': provider_logs.filtered(lambda l: l.ksef_operation == 'send_invoice' and l.ksef_status == 'failed'),
				'imported': provider_logs.filtered(lambda l: l.ksef_operation == 'import_invoice' and l.ksef_status == 'success'),
				'import_errors': provider_logs.filtered(lambda l: l.ksef_operation == 'import_invoice' and l.ksef_status == 'failed'),
				'retry': provider_logs.filtered(lambda l: l.ksef_retry_count > 0),
			}
			# Przelicz na liczby
			stats_counts = {k: len(v) for k, v in stats.items()}

			self._send_ksef_daily_report(provider, stats_counts, provider_logs)

		_logger.info(f"[KSeF Report] Reports sent for {len(providers)} providers.")


	# =======================================================================================
	# METODA CRON DLA KSeF - Obsługa zadań w kolejce
	# =======================================================================================

	@api.model
	def _cron_process_ksef_queue(self, log_ids=None):
		"""
		Główny cron do przetwarzania kolejki KSeF.
		Używa FOR UPDATE SKIP LOCKED dla bezpieczeństwa.
		
		Działanie:
		1. Znajduje rekordy gotowe do przetworzenia
		2. Blokuje każdy rekord (FOR UPDATE NOWAIT)
		3. Oznacza jako processing + HARD COMMIT
		4. Wykonuje operację Java (poza transakcją)
		5. Zapisuje wynik
		"""
		_logger.info("[KSeF Cron] Starting KSeF queue processing")
		
		if log_ids:
			ready_domain = [
				("id", "in", log_ids)
			]
		else:
			# 1. Znajdź rekordy gotowe do przetworzenia (bez blokady na początku)
			ready_domain = [
				('provider_id.provider_type', '=', 'ksef'),
				('ksef_next_execution', '<=', fields.Datetime.now()),
				('ksef_operation', 'not in', ['completed', 'failed']),
				('ksef_status', 'not in', ['success']),
				('is_processing', '=', False),
			]
		
		# 1. Sortuj priorytetowo: auth > session > send > status > upo > close
		#candidate_logs = self.search(ready_domain, order='create_date', limit=20)

		# 2. Sortuj: najpierw child records, potem parent
		# Child mają parent_id ustawione, parent mają parent_id=False
		candidate_logs = self.search(
			ready_domain, 
			order='create_date, parent_id asc, create_date asc', 
			limit=20
		)
		
		processed_count = 0
		for log in candidate_logs:
			try:
				# 2. SPRÓBUJ zablokować ten rekord (FOR UPDATE NOWAIT)
				#	Jeśli już zablokowany - przejdź do następnego
				if not log._acquire_db_lock():
					continue
				
				# 3. Mamy wyłączny dostęp - przetwórz
				success = log._process_single_ksef_step()
				
				if success:
					processed_count += 1
					
				# 4. Limit przetworzonych na jedną iterację cron
				if processed_count >= 5:
					break
					
			except Exception as e:
				_logger.error(f"[KSeF Cron] Error processing log {log.id}: {e}")
				# Odblokuj jeśli doszło do błędu
				log._release_db_lock()
				continue
		
		_logger.info(f"[KSeF Cron] Finished. Processed {processed_count} logs")
		return processed_count


	# =======================================================================================
	# CRON: ENVIRONMENT CHECK
	# =======================================================================================

	@api.model
	def cron_ksef_environment_check(self):
		"""
		Cyklicznie sprawdza dostępność środowiska KSeF dla każdego providera.
		"""
		_logger.info("[KSeF Env Check] Starting environment health check")

		providers = self.env['communication.provider'].search([
			('company_id', '=', self.company_id.id),
			('provider_type', '=', 'ksef'),
			('active', '=', True)
		])

		for provider in providers:
			try:
				# Używamy metody provider_test z return_status=True
				result = provider.provider_test(return_status=True)

				if result.get("ok"):
					_logger.debug(f"[KSeF Env Check] Provider {provider.name} is healthy.")
					continue

				message = result.get("message", "Nieznany błąd")
				_logger.warning(f"[KSeF Env Check] Provider {provider.name} environment problem: {message}")
				self._notify_ksef_environment_alert(provider, message)

			except Exception as e:
				_logger.error(f"[KSeF Env Check] Exception for provider {provider.name}: {e}", exc_info=True)
				self._notify_ksef_environment_alert(provider, str(e))

		_logger.info("[KSeF Env Check] Finished.")

	# ########################################################################################	
	def _acquire_db_lock(self):
		"""
		Blokuje rekord w DB używając FOR UPDATE NOWAIT.
		Zwraca True jeśli udało się zablokować.
		"""
		try:
			# FOR UPDATE NOWAIT - fail jeśli już zablokowany
			self.env.cr.execute("""
				SELECT id 
				FROM communication_log 
				WHERE id = %s 
				FOR UPDATE NOWAIT
			""", [self.id])
			
			# Jeśli doszliśmy tutaj - mamy blokadę
			return True
			
		except psycopg2.errors.LockNotAvailable:
			# Już zablokowany przez inny proces
			_logger.debug(f"[KSeF] Log {self.id} already locked, skipping")
			return False
		except Exception as e:
			_logger.error(f"[KSeF] DB lock error for log {self.id}: {e}")
			return False
	
	def _release_db_lock(self):
		"""
		Zwolnij blokadę poprzez commit lub rollback.
		W Odoo blokada FOR UPDATE jest zwalniana automatycznie
		na końcu transakcji.
		"""
		# Nic nie robimy - transakcja sama zwolni blokadę
		pass

	def _execute_ksef_operation(self, provider):
		"""Dispatcher - decyduje Python czy Java"""
		operation = self.ksef_operation
		
		# Operacje które migrujemy do Python
		python_operations = {}
		
		if operation in python_operations:
			return self._execute_ksef_python_operation(provider)
		else:
			return self._execute_ksef_java_operation(provider)

	#
	def _prepare_python_input(self, ksef_config):
		"""
		Przygotowuje input dla Python download_upo (analogicznie do Java).
		"""
		if self.ksef_operation not in ['download_upo','restore_invoice']:
			raise ValueError(f"_prepare_python_input only for download_upo, not {self.ksef_operation}")

		if self.ksef_operation == 'download_upo':
			# 1. Pobierz dane z payload_response (z check_status)
			if not self.payload_response:
				raise ValueError("Missing payload_response with UPO data")
			
			try:
				check_status_data = json.loads(self.payload_response)
			except json.JSONDecodeError as e:
				raise ValueError(f"Invalid JSON in payload_response: {e}")
			
			# 2. Wyciągnij URL UPO z check_status response
			upo_data = check_status_data.get('data', {}).get('response', {}).get('upo', {})
			pages = upo_data.get('pages', [])
			
			if not pages:
				raise ValueError("No UPO pages in check_status response")
			
			first_page = pages[0]
			download_url = first_page.get('downloadUrl')
			reference_number = first_page.get('referenceNumber')
			
			if not download_url:
				raise ValueError("Missing downloadUrl in UPO data")
			
			# 3. Zbuduj strukturę analogiczną do Java
			return {
				"operation": "download_upo",
				"config": {
					"environment": ksef_config.environment,
					"auth_type": ksef_config.auth_type,
					"company_nip": ksef_config.company_nip,
				},
				"context": {
					"upo": {
						"url": download_url,
						"referenceNumber": reference_number,
						"expirationDate": first_page.get('downloadUrlExpirationDate'),
					}
				}
			}
		elif self.ksef_operation == 'restore_invoice':
			"""
			Przygotowuje input dla restore_invoice.
			Potrzebuje: ksef_number, file_data (już pobrane w import_invoice)
			"""
			if not self.file_data:
				raise ValueError("Missing file_data for restore_invoice")
			
			if not self.ksef_invoice_number:
				raise ValueError("Missing ksef_invoice_number for restore_invoice")
			
			return {
				"operation": "restore_invoice",
				"config": {
					"environment": ksef_config.environment,
					"auth_type": ksef_config.auth_type,
					"company_nip": ksef_config.company_nip,
				},
				"context": {
					"ksef_number": self.ksef_invoice_number,
				},
				"params": {
					"ksef_number": self.ksef_invoice_number,
					"file_name": self.file_name or f"KSeF_{self.ksef_invoice_number}.xml",
				}
			}
		
		else:
			raise ValueError(f"_prepare_python_input not implemented for {self.ksef_operation}")



	def _should_use_python(self, provider):
		"""
		Decide whether to use Python or Java implementation.
		"""
		# 1. Check provider configuration
		ksef_config = provider._get_ksef_config()
		
		# Add this field to CommunicationProviderKsef:
		# use_python_http = fields.Boolean(string="Use Python HTTP", default=False)
		if hasattr(ksef_config, 'use_python_http'):
			if not ksef_config.use_python_http:
				return False
		
		# 2. Operations that MUST stay in Java (XAdES signing)
		java_only_operations = {
			'auth',
			'open_session',
			'send_invoice',
			'check_status',
			'close_session',
			'import_list',
			'import_invoice',
			'import_invoices',
		}
		
		if self.ksef_operation in java_only_operations:
			return False
		
		# 3. Operations that CAN be in Python (HTTP only)
		python_capable_operations = {
			'download_upo',
			'restore_invoice',
		}
		
		return self.ksef_operation in python_capable_operations

	# Helpery dla tokens
	def _is_token_valid(self, expiry_str):
		"""Sprawdza czy token jest jeszcze ważny."""
		if not expiry_str:
			return False
		
		try:
			expiry = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
			now = datetime.utcnow()
			# 30-sekundowy bufor bezpieczeństwa
			return now < (expiry - timedelta(seconds=30))
		except Exception:
			return False

	def _update_tokens_in_context(self, refresh_result):
		"""Aktualizuje tokeny w payload_context."""
		new_tokens = refresh_result.get('context', {}).get('tokens', {})
		if new_tokens:
			current_ctx = json.loads(self.payload_context) if self.payload_context else {}
			if 'tokens' not in current_ctx:
				current_ctx['tokens'] = {}
			current_ctx['tokens'].update(new_tokens)
			
			self.write({
				'payload_context': json.dumps(current_ctx, ensure_ascii=False)
			})

	# Metoda sprawdzająca tokeny
	def _check_tokens_validity(self):
		"""
		Sprawdza czy tokeny w session_runtime są nadal ważne.
		Zwraca: (is_valid, needs_refresh, error_message)
		"""
		if not self.session_runtime:
			return False, False, "No session runtime"
		
		try:
			session_ctx = json.loads(self.session_runtime)
			tokens = session_ctx.get('tokens', {})
			
			if not tokens:
				return False, False, "No tokens in session"
			
			access_token = tokens.get('accessToken')
			expiry_str = tokens.get('accessTokenValidUntil')
			refresh_token = tokens.get('refreshToken')
			
			if not access_token or not expiry_str:
				return False, False, "Missing token or expiry"
			
			# Parsuj datę ważności
			try:
				# Format: "2024-01-01T12:00:00Z"
				expiry = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
				now = datetime.utcnow()
				
				# Dodaj 5-minutowy bufor
				buffer = timedelta(minutes=5)
				
				if now > expiry:
					# Token już wygasł
					if refresh_token:
						return False, True, f"Token expired at {expiry_str}, but has refresh token"
					else:
						return False, False, f"Token expired at {expiry_str}, no refresh token"
				
				elif now > (expiry - buffer):
					# Token wygasa za mniej niż 5 minut
					if refresh_token:
						return True, True, f"Token expires soon at {expiry_str}"
					else:
						return True, False, f"Token expires soon at {expiry_str}, no refresh token"
				
				else:
					# Token aktualny
					time_left = expiry - now
					return True, False, f"Token valid for {time_left}"
					
			except ValueError as e:
				return False, False, f"Invalid expiry format: {expiry_str}, error: {e}"
				
		except Exception as e:
			return False, False, f"Error checking tokens: {e}"

	#
	def _check_and_refresh_tokens_if_needed(self, ksef_config):
		"""
		Sprawdza ważność tokenów w logu i wykonuje odpowiednie akcje.
		
		Zwraca jeden ze statusów:
			'valid' - tokeny są ważne, można kontynuować
			'refreshed' - udało się odświeżyć access token
			'refresh_failed' - refresh się nie udał, ale może następna próba
			'reauth_required' - wymagana pełna autoryzacja
		"""
		_logger.info(f"[KSeF] Checking tokens for log {self.id}")
		
		# 1. Sprawdź access token
		if self.ksef_access_token:
			access_valid, access_msg = self._is_token_valid(
				self.ksef_access_token_valid_until,
				buffer_minutes=5
			)
			
			if access_valid:
				_logger.info(f"[KSeF] Access token valid: {access_msg}")
				return 'valid'
		
		# 2. Access token nieważny lub brak - sprawdź refresh token
		if not self.ksef_refresh_token:
			_logger.info("[KSeF] No refresh token, reauth required")
			return 'reauth_required'
		
		refresh_valid, refresh_msg = self._is_token_valid(
			self.ksef_refresh_token_valid_until,
			buffer_minutes=5
		)
		
		if not refresh_valid:
			_logger.info(f"[KSeF] Refresh token invalid: {refresh_msg}")
			return 'reauth_required'
		
		# 3. Mamy ważny refresh token - próbuj odświeżyć
		_logger.info("[KSeF] Attempting token refresh")
		
		service = ProviderKsefApiService(ksef_config, self)
		refresh_result = service.refresh_tokens()
		
		if refresh_result.get('success'):
			_logger.info("[KSeF] Tokens refreshed successfully")
			return 'refreshed'
		elif refresh_result.get('requires_auth'):
			_logger.warning(f"[KSeF] Refresh failed, requires auth: {refresh_result.get('error')}")
			return 'reauth_required'
		else:
			_logger.error(f"[KSeF] Refresh failed: {refresh_result.get('error')}")
			return 'refresh_failed'
	#
	def _is_token_valid(self, valid_until, buffer_minutes=5):
		"""
		Sprawdza czy token jest ważny.
		Zwraca: (is_valid: bool, message: str)
		"""
		if not valid_until:
			return False, "No expiry date"
		
		now = fields.Datetime.now()
		buffer = timedelta(minutes=buffer_minutes)
		
		# Konwersja jeśli valid_until to string (z API KSeF)
		if isinstance(valid_until, str):
			try:
				# Obsługa formatu ISO z KSeF
				if valid_until.endswith('Z'):
					valid_until = valid_until.replace('Z', '+00:00')
				if '.' in valid_until:
					valid_until = valid_until.split('.')[0]
				expiry = datetime.fromisoformat(valid_until)
				# Usuń timezone jeśli istnieje
				if expiry.tzinfo is not None:
					expiry = expiry.replace(tzinfo=None)
			except ValueError as e:
				return False, f"Invalid date format: {e}"
		else:
			expiry = valid_until
		
		if now > expiry:
			return False, f"Token expired at {expiry}"
		
		if now > (expiry - buffer):
			return True, f"Token valid but expires soon at {expiry}"
		
		time_left = expiry - now
		return True, f"Token valid for {time_left}"

	#
	def _save_tokens_from_auth_result(self, auth_result):
		"""
		Zapisuje tokeny z wyniku auth do payload_context tego rekordu.
		"""
		try:
			# Auth JAR zwraca tokeny w data.tokens lub context.tokens
			data = auth_result.get('data', {})
			context = auth_result.get('context', {})
			
			tokens = context.get('tokens', data.get('tokens', {}))
			
			if tokens:
				# Zbuduj/zaktualizuj payload_context
				current_ctx = {}
				if self.payload_context:
					current_ctx = json.loads(self.payload_context)
				
				current_ctx['tokens'] = tokens
				
				# Zapisz
				self.write({
					'payload_context': json.dumps(current_ctx, ensure_ascii=False)
				})
				
				_logger.info(f"[KSeF] Saved new tokens to payload_context")
				return True
				
		except Exception as e:
			_logger.error(f"[KSeF] Error saving tokens: {e}")
		
		return False

	# Helper dla sesssion_close
	def _should_close_session(self):
		"""
		Decyduje czy wykonać close_session.
		Zwraca: (should_close: bool, reason: str)
		"""
		# 1. Sprawdź czy sesja już nie jest zamknięta
		if self.ksef_operation == 'completed':
			return False, "Session already completed"
		
		if self.state == 'received':
			return False, "Session already received"
		
		# 2. Sprawdź czy mamy reference_number
		if not self.ksef_reference_number and not self.external_id:
			return False, "No reference number"
		
		# 3. Sprawdź czy mamy dane sesji
		if not self.session_runtime:
			return False, "No session runtime data"
		
		# 4. Sprawdź tokeny (opcjonalne, ale zalecane)
		try:
			if self.payload_context:
				payload_ctx = json.loads(self.payload_context)
				tokens = payload_ctx.get('tokens', {})
				if not tokens.get('accessToken'):
					return False, "No access token"
		except:
			pass  # Ignore parsing errors
		
		# 5. ✅ ZAWSZE zamykaj sesję jeśli doszliśmy do tego kroku w flow
		# Sesja MUSI zostać zamknięta po wysłaniu faktury, niezależnie od tego
		# czy będziemy sprawdzać status czy nie!
		# MF wymaga zamknięcia sesji przed generowaniem UPO.
		return True, "Session must be closed after sending invoice"

	# --------------------------------------------------------------------------------
	# Nowa metoda router'a
	# --------------------------------------------------------------------------------
	def _process_single_ksef_step(self):
		"""
		Dispatcher backendu KSeF.
		"""

		self.ensure_one()

		provider = self.provider_id

		if not provider:
			return {
				"success": False,
				"error": "Missing provider configuration"
			}

		config_id = provider.provider_config_id
		config = self.env[provider.provider_model].browse([config_id])

		_logger.info(
			f"\n🚩 provider = {provider}"
			f"\n🚩 model = {provider.provider_model}"
			f"\n🚩 config_id = {config_id}"
			f"\n🚩 config = {config}"
		)

		if not config:
			return {
				"success": False,
				"error": "Missing provider configuration"
			}

		if config.api_backend == "java":
			return self._process_java_flow()

		elif config.api_backend == "python":
			return self._process_python_flow()

		return {
			"success": False,
			"error": "Unsupported KSeF API client configuration"
		}

	# =============================================================================
	# Pomocniczo dla obsługi sesji
	# =============================================================================
	def session_is_active(self):
		expiry = self.log.ksef_session_valid_until
		if not expiry:
			return False

		now = fields.Datetime.now()
		buffer = timedelta(minutes=5)
		return now < (expiry - buffer)

	# =============================================================================
	# Obsługa flow KSeF dla backendu Python - _process_python_flow
	# =============================================================================
	def _get_next_operation(self, current_operation, result):

		if current_operation == "auth":
			return "open_session"

		if current_operation == "open_session":
			return "send_invoice"

		if current_operation == "send_invoice":
			return "check_status"

		if current_operation == "check_status":
			status = result.get("payload_response", {})
			if status.get("processingCode") == "200":
				return "download_upo"
			return "check_status"

		if current_operation == "download_upo":
			return None

		return None

	def _handle_ksef_error(self, error_message):
		self.write({
			"ksef_process_state": "error",
			"ksef_process_message": error_message,
			"ksef_retry_count": self.ksef_retry_count + 1
		})

	def _handle_ksef_error(self, error_message):
		self.write({
			"ksef_process_state": "error",
			"ksef_process_message": error_message,
			"ksef_retry_count": self.ksef_retry_count + 1
		})

	def _attach_upo_to_move(self, upo_binary):
		move = self.import_move_id
		if not move:
			return

		self.env["ir.attachment"].create({
			'company_id': move.company_id.id,
			"name": "UPO.xml",
			"type": "binary",
			"datas": base64.b64encode(upo_binary),
			"res_model": "account.move",
			"res_id": move.id,
			
		})

	# =============================================================================

	def _process_import_invoice(self, service):
		"""
		Pobiera pojedynczą fakturę XML z KSeF.
		"""
		_logger.info(f"[KSeF][Python] Starting import_invoice for log {self.id}")

		# 1. Sprawdź czy mamy numer KSeF
		if not self.ksef_invoice_number:
			return {
				"success": False,
				"error": "Brak numeru KSeF faktury",
				"context_updates": {
					'provider_message': "Brak numeru KSeF faktury do pobrania"
				}
			}

		# 2. Wywołaj API
		result = service.get_invoice_by_number(self.ksef_invoice_number)

		# 3. Jeśli błąd - zapisz odpowiedź
		if not result.get('success'):
			context_updates = {
				'ksef_http_status': result.get('status_code', 0),
				'provider_message': result.get('error', 'Nieznany błąd'),
			}
			if result.get('data'):
				context_updates['payload_response'] = json.dumps(result['data'], ensure_ascii=False)
			
			return {
				"success": False,
				"error": result.get('error'),
				"context_updates": context_updates
			}

		# 4. Sukces - pobrano XML
		data = result.get('data', {})
		xml_base64 = data.get('xml_base64')
		ksef_invoice_hash = data.get('ksef_invoice_hash')  # ← pobierz hash		
		
		if not xml_base64:
			return {
				"success": False,
				"error": "Brak danych XML w odpowiedzi",
				"context_updates": {
					'ksef_http_status': result.get('status_code', 0),
					'provider_message': "Odpowiedź nie zawiera XML",
					'payload_response': json.dumps(data, ensure_ascii=False)
				}
			}

		# 5. Przygotuj aktualizację pól logu
		file_size = data.get('file_size', 0)
		
		update_vals = {
			'file_data': xml_base64,
			'file_name': f"KSeF_{self.ksef_invoice_number}.xml",
			'file_size': file_size,
			'state': 'queued',  # gotowe do restore
			'ksef_status': 'pending',
			'ksef_http_status': result.get('status_code', 200),
			'provider_message': f"Pobrano fakturę KSeF: {self.ksef_invoice_number} ({file_size} bajtów)",
			'payload_response': json.dumps(data, ensure_ascii=False),
			'ksef_invoice_hash': ksef_invoice_hash,  # ← zapisz prawidłowy hash
		}

		# ✅ Zapisz prawidłowy hash
		if ksef_invoice_hash:
			update_vals['ksef_invoice_hash'] = ksef_invoice_hash
			_logger.info(f"[KSeF] Saved invoice hash: {ksef_invoice_hash}")

		# Zapisz request (URL który był wywołany)
		update_vals['payload_request'] = json.dumps({
			'operation': 'import_invoice',
			'ksef_number': self.ksef_invoice_number
		}, ensure_ascii=False)

		_logger.info(f"[KSeF][Python] Pobrano fakturę {self.ksef_invoice_number}, {file_size} bajtów")

		return {
			"success": True,
			"data": {
				"ksef_number": self.ksef_invoice_number,
				"file_size": file_size,
			},
			"context_updates": update_vals
		}

	# =============================================================================

	def _process_import_list(self, service):
		"""
		Pobiera listę faktur z KSeF i tworzy child logi.
		"""
		_logger.info(f"[KSeF][Python] Starting import_list for log {self.id}")

		# 1. Pobierz konfigurację providera
		provider = self.provider_id
		if not provider or provider.provider_type != 'ksef':
			return {"success": False, "error": "Invalid provider"}

		ksef_config = provider._get_ksef_config()
		if not ksef_config:
			return {"success": False, "error": "No KSeF configuration"}

		# 2. Oblicz zakres dat
		date_from, date_to = self._calculate_import_date_range(ksef_config)
		page_size = self.ksef_import_page_size or getattr(ksef_config, 'import_page_size', 100)
		
		_logger.info(f"[KSeF][Python] Import range: {date_from} to {date_to}, page_size: {page_size}")

		# 3. Wywołaj API
		result = service.get_received_invoices(
			date_from.strftime('%Y-%m-%d'),
			date_to.strftime('%Y-%m-%d'),
			page_size
		)

		# 4. Jeśli błąd - zapisz odpowiedź i zakończ
		if not result.get('success'):
			# Zapisz odpowiedź błędu jeśli istnieje
			context_updates = {}
			if result.get('status_code'):
				context_updates['ksef_http_status'] = result['status_code']
			if result.get('data'):
				context_updates['payload_response'] = json.dumps(result['data'], ensure_ascii=False)
			if result.get('error'):
				context_updates['provider_message'] = result['error']
			
			return {
				"success": False,
				"error": result.get('error'),
				"context_updates": context_updates
			}

		# 5. Sukces - przetwarzaj odpowiedź
		data = result.get('data', {})
		invoices = data.get('invoices', [])
		invoice_count = data.get('invoiceCount', 0)
		
		_logger.info(f"[KSeF][Python] Found {invoice_count} invoices")

		# 6. Przygotuj aktualizację pól logu
		update_vals = {
			'ksef_api_status_code': data.get('processingCode'),
			'ksef_api_status_message': data.get('processingDescription'),
			'ksef_http_status': result.get('status_code', 200),
			'payload_request': json.dumps({
				'date_from': date_from.strftime('%Y-%m-%d'),
				'date_to': date_to.strftime('%Y-%m-%d'),
				'page_size': page_size
			}, ensure_ascii=False),
			'payload_response': json.dumps(data, ensure_ascii=False),
		}

		# 7. Utwórz child logi dla nowych faktur
		created_count = 0
		skipped_count = 0

		for invoice in invoices:
			ksef_number = invoice.get('ksefNumber')
			if not ksef_number:
				continue

			# Sprawdź czy faktura już istnieje
			existing_move = self.env['account.move'].search([
				('ksef_number', '=', ksef_number),
				('move_type', '=', 'in_invoice'),
			], limit=1)

			if existing_move:
				_logger.info(f"[KSeF] Faktura {ksef_number} już istnieje jako {existing_move.id}")
				skipped_count += 1
				continue

			# Sprawdź czy nie ma już child logu
			existing_child = self.env['communication.log'].search([
				('ksef_invoice_number', '=', ksef_number),
				('direction', '=', 'import'),
				('parent_id', '=', self.id),
			], limit=1)

			if existing_child:
				_logger.info(f"[KSeF] Child log już istnieje dla {ksef_number}")
				skipped_count += 1
				continue

			# Utwórz child log
			child_vals = {
				'provider_id': self.provider_id.id,
				'direction': 'import',
				'document_model': 'account.move',
				'state': 'draft',
				'ksef_operation': 'import_invoice',
				'ksef_next_operation': 'restore_invoice',
				'ksef_invoice_number': ksef_number,
				'ksef_status': 'pending',
				'ksef_next_execution': fields.Datetime.now(),
				'parent_id': self.id,
				'provider_message': f"Import faktury {invoice.get('invoiceNumber', '')} (KSeF: {ksef_number})",
				# Przekaż zakres dat do childa
				'ksef_import_days_back': self.ksef_import_days_back,
				'company_id': self.company_id.id,
			}

			# Jeśli nie mamy tokenów, najpierw auth
			if not self.ksef_access_token:
				child_vals['ksef_operation'] = 'auth'
				child_vals['ksef_next_operation'] = 'import_invoice'

			self.env['communication.log'].with_company(self.company_id).create(child_vals)
			created_count += 1

		# 8. Dodaj statystyki do aktualizacji
		update_vals.update({
			'ksef_discovered_count': invoice_count,
			'ksef_created_jobs': created_count,
			'provider_message': f"Lista faktur: {invoice_count} znaleziono, {created_count} nowych, {skipped_count} pominiętych",
		})

		_logger.info(f"[KSeF][Python] Utworzono {created_count} child logów")

		return {
			"success": True,
			"data": {
				"invoice_count": invoice_count,
				"created": created_count,
				"skipped": skipped_count,
			},
			"context_updates": update_vals
		}

	# =============================================================================

	def _process_python_flow(self):
		_logger.info("[KSeF][Python] _process_python_flow - Dyspozytor dla Python flow - wzorowany na _determine_next_ksef_operations")
		
		self.ensure_one()
		
		# 1. Lock i status (jak wcześniej)
		self.write({
			'is_processing': True,
			'processing_pid': os.getpid(),
			'processing_lock_until': fields.Datetime.now() + timedelta(minutes=10),
			'ksef_status': 'in_progress',
			'ksef_last_execution': fields.Datetime.now(),
		})
		self.env.cr.commit()
		
		try:
			# 2. Wybór flow na podstawie direction i operation
			if self.direction == 'export':
				return self._execute_export_operation()
			else:  # import
				return self._process_import_flow()
				
		except Exception as e:
			# Obsługa błędów
			self.write({
				'is_processing': False,
				'ksef_status': 'failed',
				'ksef_retry_count': self.ksef_retry_count + 1,
				'provider_message': str(e),
				'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=5),
			})
			self.env.cr.commit()
			return {"success": False, "error": str(e)}

	# =============================================================================

	# ================================================================

	def _process_import_flow(self):
		_logger.info("[KSeF][Python] _process_import_flow - Flow importu - dynamiczna sekwencja zależna od kontekstu")
		operation = self.ksef_operation
		self.ksef_status = 'in_progress'
		
		# Określ sekwencję (jak w _determine_next_ksef_operations)
		if operation == 'auth':
			if self.ksef_invoice_number:
				sequence = ['auth', 'import_invoice', 'restore_invoice', 'completed']
			else:
				sequence = ['auth', 'import_list', 'completed']
		elif operation == 'import_list':
			sequence = ['import_list', 'completed']
		elif operation == 'import_invoice':
			sequence = ['import_invoice', 'restore_invoice', 'completed']
		elif operation == 'restore_invoice':
			sequence = ['restore_invoice', 'completed']
		else:
			sequence = ['completed']
		
		# Znajdź następną operację
		try:
			current_idx = sequence.index(operation)
			next_op = sequence[current_idx + 1] if current_idx + 1 < len(sequence) else 'completed'
		except (ValueError, IndexError):
			next_op = 'failed'
		
		# Wykonaj bieżącą operację
		result = self._execute_import_operation(operation)
		
		if not result.get('success'):
			return result
		
		# Ustaw następną operację
		self.write({
			'ksef_operation': next_op,
			'ksef_next_execution': fields.Datetime.now(),
			'is_processing': False,
		})
		self.env.cr.commit()
		
		return {"success": True}

	# ================================================================

	# ================================================================
	###def _process_python_flow(self):
	def _execute_export_operation(self):
		_logger.info("[KSeF][Python] _execute_export_operation - Python backend – kompatybilny z lifecycle communication.log.")
		self.ensure_one()
		
		provider = self.provider_id
		config_id = provider.provider_config_id
		config = self.env[provider.provider_model].browse([config_id])
		
		service = ProviderKsefApiService(config, self)
		operation = self.ksef_operation
		
		# ============================================================
		# 1. LOCK + STATUS IN_PROGRESS
		# ============================================================
		self.write({
			'is_processing': True,
			'processing_pid': os.getpid(),
			'processing_lock_until': fields.Datetime.now() + timedelta(minutes=10),
			'ksef_status': 'in_progress',
			'ksef_last_execution': fields.Datetime.now(),
		})
		self.env.cr.commit()
		next_operation = ''

		try:
			# ============================================================
			# 2. TOKEN MANAGEMENT (dla operacji wymagających autoryzacji)
			# ============================================================
			operations_requiring_tokens = [
				'open_session', 'send_invoice', 'check_status', 
				'download_upo', 'close_session'
			]
			
			if operation in operations_requiring_tokens:
				token_status = self._check_and_refresh_tokens_if_needed(config)
				
				if token_status == 'reauth_required':
					# Przełącz na auth i zakończ ten krok
					self.write({
						'ksef_operation': 'auth',
						'ksef_next_execution': fields.Datetime.now(),
						'ksef_status': 'pending',
						'is_processing': False,
						'provider_message': 'Reauthentication required - switching to auth'
					})
					self.env.cr.commit()
					return {"success": False, "requires_auth": True}
				
				elif token_status == 'refresh_failed':
					# Zaplanuj ponowną próbę
					retry_delay = self._calculate_retry_delay()
					self.write({
						'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=retry_delay),
						'ksef_retry_count': self.ksef_retry_count + 1,
						'ksef_status': 'pending',
						'is_processing': False,
						'provider_message': f'Refresh failed, will retry in {retry_delay} min'
					})
					self.env.cr.commit()
					return {"success": False, "error": "Refresh failed, will retry"}
				
				# Dla 'valid' i 'refreshed' - kontynuuj
				if token_status == 'refreshed':
					_logger.info("[KSeF] Tokens were refreshed, continuing with operation")
			
			# ============================================================
			# 3. WYWOŁANIE SERVICE
			# ============================================================
			result = None
			
			if operation == "auth":
				result = service.auth()
				
			elif operation == "open_session":
				result = service.open_session()
				
			elif operation == "send_invoice":
				if not self.file_data:
					return {"success": False, "error": "No file_data in log record"}
				
				# Przygotuj XML do wysyłki
				if isinstance(self.file_data, bytes):
					try:
						xml_bytes = base64.b64decode(self.file_data)
					except:
						xml_bytes = self.file_data
				else:
					xml_bytes = self.file_data.encode('utf-8')
				
				result = service.send_invoice(xml_bytes)
				
				# Jeśli sukces - wywołaj mark_sent()
				if result.get('success'):
					invoice_ref = result.get('data', {}).get('invoiceReferenceNumber')
					self.mark_sent(external_id=invoice_ref)
					
					# Zapisz hash jeśli jest
					if result.get('data', {}).get('invoiceHash'):
						self.write({
							'ksef_invoice_hash': result['data']['invoiceHash']
						})

			elif operation == "check_status":
				result = service.check_invoice_status()
				
				if result.get('success'):
					self.mark_status_checked(payload=json.dumps(result.get('data'), indent=2))
					
					# Sprawdź czy UPO jest dostępne i pobierz NATYCHMIAST
					data = result.get('data', {})
					upo_url = data.get('upoDownloadUrl')
					
					if upo_url:
						_logger.info(f"[KSeF] UPO URL found, downloading immediately")
						try:
							# KROK 1: Pobierz UPO
							upo_response = requests.get(upo_url, timeout=30)
							upo_response.raise_for_status()
							upo_content = upo_response.content
							
							# KROK 2: Zapisz jako załącznik do faktury
							if self.document_model == 'account.move' and self.document_id:
								self._attach_upo_to_move(upo_content)
								
								# KROK 3: Aktualizuj fakturę Odoo o numer KSeF
								move = self.env['account.move'].browse(self.document_id)
								if move.exists():
									ksef_number = data.get('ksefNumber')
									if ksef_number:
										move.write({'ksef_number': ksef_number})
										_logger.info(f"[KSeF] Updated move {self.document_id} with ksef_number: {ksef_number}")
								
								_logger.info(f"[KSeF] UPO attached to move {self.document_id}")
							else:
								# Nie ma faktury - zapisz w logu
								self.write({
									'file_data': base64.b64encode(upo_content),
									'file_name': f"UPO_{self.ksef_reference_number}.xml"
								})
								_logger.warning(f"[KSeF] No account.move, saved UPO to file_data")
							
							# KROK 4: Aktualizuj LOG o dane z odpowiedzi
							update_fields = {
								'ksef_invoice_number': data.get('ksefNumber'),
								#'ksef_reference_number': data.get('ksefNumber'),  # numer KSeF faktury 
								'ksef_api_status_code': data.get('status', {}).get('code'),
								'ksef_api_status_message': data.get('status', {}).get('description'),
								'ksef_processing_code': data.get('processingCode'),
							}
							# Usuń None values
							update_fields = {k: v for k, v in update_fields.items() if v is not None}
							if update_fields:
								self.write(update_fields)
							
							# KROK 5: Wywołaj mark_received (ustawi state='received', receive_date)
							self.mark_received(payload=json.dumps(data, indent=2))

							# KROK 6: ZAKOŃCZ - wszystko mamy, sesją się nie przejmujemy
							self.write({
								'ksef_operation': 'completed',
								'ksef_status': 'success',  # <--- sukces, nie pending!
								'is_processing': False,
								# Nie ustawiamy next_execution - koniec
							})
							self.env.cr.commit()
							
							_logger.info(f"[KSeF] UPO downloaded successfully, flow completed")
							return {"success": True}  # <--- WYJŚCIE, bez przechodzenia do punktu 7							
							
						except Exception as e:
							_logger.error(f"[KSeF] UPO download failed: {e}")
							next_operation = None  # pójdzie do metody decyzyjnej
					else:
						# Przypadek 2: UPO NIE jest gotowe - sprawdź status
						status_code = data.get('status', {}).get('code')
						status_desc = data.get('status', {}).get('description', '')
						
						# Błędy krytyczne - faktura odrzucona
						if status_code in [130, 140, 330, 400, 440, 441, 442, 443, 444, 445, 446]:
							# Dla 440 (duplikat) - to nie jest błąd, faktura już istnieje
							if status_code == 440:
								_logger.info(f"[KSeF] Invoice already exists in KSeF (code 440)")
								
								# Zapisz komunikat na fakturze Odoo jeśli istnieje
								if self.document_model == 'account.move' and self.document_id:
									move = self.env['account.move'].browse(self.document_id)
									if move.exists():
										# Użyj description i details z odpowiedzi
										description = data.get('status', {}).get('description', '')
										details = data.get('status', {}).get('details', [])
										
										# Połącz description i details w jeden komunikat
										full_message = f"📌 {description}"
										if details:
											full_message += ": " + " ".join(details)
										
										# Dodaj wiadomość do chattera faktury
										move.message_post(
											body=full_message,
											subject="📌 KSeF - Duplikat faktury",
											message_type='notification',
											subtype_xmlid='mail.mt_note',
										)
										_logger.info(f"[KSeF] Saved to move [{move}]: {full_message}")
								
								# Zakończ flow - faktura już jest w KSeF
								self.mark_received(payload=json.dumps(data, indent=2))
								self.write({
									'ksef_operation': 'completed',
									'ksef_status': 'success',
									'is_processing': False,
								})
								self.env.cr.commit()
								return {"success": True}
							#
							self.mark_error(f"KSeF error {status_code}: {status_desc}", operation='check_status')
							next_operation = 'failed'
							_logger.error(f"[KSeF] Invoice rejected with code {status_code}: {status_desc}")
							
						# Przypadek 3: W trakcie przetwarzania (brak UPO, ale nie błąd)
						else:
							# Zostań w check_status z opóźnieniem
							next_operation = 'check_status'
							delay = self.provider_id._get_ksef_config().status_check_delay or 5
							self.write({
								'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=delay)
							})
							_logger.info(f"[KSeF] UPO not ready, retry in {delay} minutes (status: {status_code})")

				else:
					# Błąd - next_operation = None
					next_operation = None
				
			elif operation == "download_upo":
				result = service.download_upo()
				
				# Jeśli sukces - wywołaj mark_received()
				if result.get('success'):
					self.mark_received(payload=json.dumps(result.get('data'), indent=2))
					
					# Jeśli UPO zawiera NumerKSeFDokumentu, zapisz go
					if result.get('data', {}).get('numer_ksef_dokumentu'):
						self.write({
							'ksef_reference_number': result['data']['numer_ksef_dokumentu']
						})
				
			elif operation == "close_session":
				result = service.close_session()
				
			else:
				return {"success": False, "error": f"Unsupported Python operation: {operation}"}
			
			# ============================================================
			# 4. OBSŁUGA BŁĘDU Z OPERACJI
			# ============================================================
			if not result.get("success"):
				self.write({
					'ksef_status': 'failed',
					'ksef_retry_count': self.ksef_retry_count + 1,
					'provider_message': result.get("error"),
					'is_processing': False,
					'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=5),
				})
				self.env.cr.commit()
				return result
			
			# ============================================================
			# 5. ZAPIS PAYLOADÓW
			# ============================================================
			if result.get("payload_request") is not None:
				self.store_java_request(json.dumps(result["payload_request"], ensure_ascii=False))
			
			if result.get("payload_response") is not None:
				self.store_java_response(json.dumps(result["payload_response"], ensure_ascii=False))
			
			# ============================================================
			# 6. AKTUALIZACJA PÓL KSeF
			# ============================================================
			context_updates = result.get("context_updates") or {}
			if context_updates:
				self.write(context_updates)
			
			# ============================================================
			# 7. DETERMINE NEXT OPERATION (na podstawie wyniku)
			# ============================================================
			next_operation = self._determine_next_operation_based_on_result(operation, result)
			
			update_vals = {
				'ksef_status': 'pending',
				'ksef_retry_count': 0,
				'ksef_next_execution': fields.Datetime.now(),
			}
			
			if next_operation:
				update_vals["ksef_operation"] = next_operation
			else:
				update_vals.update({
					"ksef_operation": "completed",
					"ksef_status": "success",
				})
			
			# ============================================================
			# 8. UNLOCK
			# ============================================================
			update_vals['is_processing'] = False
			self.write(update_vals)
			self.env.cr.commit()
			
			return {"success": True}
			
		except Exception as e:
			self.write({
				'is_processing': False,
				'ksef_status': 'failed',
				'ksef_retry_count': self.ksef_retry_count + 1,
				'provider_message': str(e),
				'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=5),
			})
			self.env.cr.commit()
			
			return {"success": False, "error": str(e)}



	# =============================================================================
	###def XXX_process_python_flow(self):
	def _execute_import_operation(self, operation):
		_logger.info("[KSeF][Python] _execute_import_operation - Python backend – kompatybilny z lifecycle communication.log.")
		self.ensure_one()
		
		provider = self.provider_id
		config_id = provider.provider_config_id
		config = self.env[provider.provider_model].browse([config_id])
		
		service = ProviderKsefApiService(config, self)
		operation = self.ksef_operation
		
		# ============================================================
		# 1. LOCK + STATUS IN_PROGRESS
		# ============================================================
		self.write({
			'is_processing': True,
			'processing_pid': os.getpid(),
			'processing_lock_until': fields.Datetime.now() + timedelta(minutes=10),
			'ksef_status': 'in_progress',
			'ksef_last_execution': fields.Datetime.now(),
		})
		self.env.cr.commit()
		next_operation = ''

		try:
			# ============================================================
			# 2. TOKEN MANAGEMENT (dla operacji wymagających autoryzacji)
			# ============================================================
			operations_requiring_tokens = [
				'open_session', 'send_invoice', 'check_status', 
				'download_upo', 'close_session', 'import_list',
				'import_invoice', 'restore_invoice'
			]
			
			if operation in operations_requiring_tokens:
				token_status = self._check_and_refresh_tokens_if_needed(config)
				
				if token_status == 'reauth_required':
					# Przełącz na auth i zakończ ten krok
					self.write({
						'ksef_operation': 'auth',
						'ksef_next_execution': fields.Datetime.now(),
						'ksef_status': 'pending',
						'is_processing': False,
						'provider_message': 'Reauthentication required - switching to auth'
					})
					self.env.cr.commit()
					return {"success": False, "requires_auth": True}
				
				elif token_status == 'refresh_failed':
					# Zaplanuj ponowną próbę
					retry_delay = self._calculate_retry_delay()
					self.write({
						'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=retry_delay),
						'ksef_retry_count': self.ksef_retry_count + 1,
						'ksef_status': 'pending',
						'is_processing': False,
						'provider_message': f'Refresh failed, will retry in {retry_delay} min'
					})
					self.env.cr.commit()
					return {"success": False, "error": "Refresh failed, will retry"}
				
				# Dla 'valid' i 'refreshed' - kontynuuj
				if token_status == 'refreshed':
					_logger.info("[KSeF] Tokens were refreshed, continuing with operation")
			
			# ============================================================
			# 3. WYWOŁANIE SERVICE
			# ============================================================
			result = None
			
			if operation == "auth":
				result = service.auth()
				
			elif operation == "open_session":
				result = service.open_session()
				
			# ============================================================
			# OPERACJE IMPORTU
			# ============================================================

			elif operation == "import_list":
				result = self._process_import_list(service)
				
				# Obsługa wyniku podobna jak dla innych operacji
				if result.get('success'):
					# Zapisz payload itp.
					next_operation = self._determine_next_operation_based_on_result(operation, result)
					self.mark_received()
				else:
					# Obsługa błędu
					next_operation = 'failed'

			elif operation == "import_invoice":
				result = self._process_import_invoice(service)
				
				if result.get('success'):
					# Po pobraniu pojedynczej faktury, przejdź do restore_invoice
					next_operation = "restore_invoice"
					self.mark_status_checked()
				else:
					next_operation = 'failed'

			elif operation == "restore_invoice":
				result = self._execute_ksef_python_operation(provider)
				if result.get('success'):
					next_operation = 'completed'
					
			else:
				return {"success": False, "error": f"Unsupported Python operation: {operation}"}
			
			# ============================================================
			# 4. OBSŁUGA BŁĘDU Z OPERACJI
			# ============================================================
			if not result.get("success"):
				self.write({
					'state': 'error',
					'ksef_status': 'failed',
					'ksef_retry_count': self.ksef_retry_count + 1,
					'provider_message': result.get("error"),
					'is_processing': False,
					'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=5),
				})
				self.env.cr.commit()
				return result
			
			# ============================================================
			# 5. ZAPIS PAYLOADÓW
			# ============================================================
			if result.get("payload_request") is not None:
				self.store_java_request(json.dumps(result["payload_request"], ensure_ascii=False))
			
			if result.get("payload_response") is not None:
				self.store_java_response(json.dumps(result["payload_response"], ensure_ascii=False))
			
			# ============================================================
			# 6. AKTUALIZACJA PÓL KSeF
			# ============================================================
			context_updates = result.get("context_updates") or {}
			if context_updates:
				self.write(context_updates)
			
			# ============================================================
			# 7. DETERMINE NEXT OPERATION (na podstawie wyniku)
			# ============================================================
			next_operation = self._determine_next_operation_based_on_result(operation, result)
			
			update_vals = {
				'ksef_status': 'pending',
				'ksef_retry_count': 0,
				'ksef_next_execution': fields.Datetime.now(),
			}

			if next_operation == 'completed':
				update_vals["ksef_status"] = "success"

			if next_operation:
				update_vals["ksef_operation"] = next_operation
				_logger.info(f"[KSeF] Operation {operation} completed, next: {next_operation}")
			else:
				update_vals.update({
					"ksef_operation": "completed",
					"ksef_status": "success",
				})
				_logger.info(f"[KSeF] Operation {operation} completed, flow finished")

			ksef_status = update_vals.get("ksef_status")
			_logger.info(f"\n🧩🧩🧩 [KSeF] Operation {operation} completed\nnext: {next_operation}\nksef_status {ksef_status}")
			
			# ============================================================
			# 8. UNLOCK
			# ============================================================
			update_vals['is_processing'] = False
			self.write(update_vals)
			self.env.cr.commit()
			
			return {"success": True}
			
		except Exception as e:
			self.write({
				'is_processing': False,
				'ksef_status': 'failed',
				'ksef_retry_count': self.ksef_retry_count + 1,
				'provider_message': str(e),
				'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=5),
			})
			self.env.cr.commit()
			
			return {"success": False, "error": str(e)}


	# =============================================================================


	# =============================================================================
	# Nowa metoda do określania następnej operacji
	# =============================================================================
	def _determine_next_operation_based_on_result(self, operation, result):
		"""
		Określa następną operację na podstawie wyniku bieżącej.
		"""
		if operation == "auth":
			if self.direction == 'import':
				# Może być: 'import_list' (dla parent) lub 'import_invoice' (dla child)
				next_op = self.ksef_next_operation
				_logger.info(f"[KSeF] Auth for import, next from field: {next_op}")
				return next_op
			else:
				return "open_session"
		
		elif operation == "open_session":
			return "send_invoice"
		
		elif operation == "send_invoice":
			# Po wysłaniu, jeśli auto_check_status włączone - sprawdzaj status
			if self.provider_id and hasattr(self.provider_id, '_get_ksef_config'):
				config = self.provider_id._get_ksef_config()
				if config and config.auto_check_status:
					return "check_status"
			return "close_session"

		elif operation == "check_status":
			data = result.get('data', {})
			status_code = data.get('status', {}).get('code')
			
			# TYLKO logika decyzyjna, ŻADNYCH zapisów
			if status_code == 200:
				if data.get('upoDownloadUrl'):
					return "download_upo"	  # mamy URL, pobierz UPO
				else:
					return "check_status"	  # nie ma URL, sprawdź ponownie
			elif status_code in [130, 140, 330, 440, 441, 442, 443, 444, 445, 446]:
				return "failed"				# błąd krytyczny
			else:
				return "check_status"		  # inne kody - ponów
		
		elif operation == "download_upo":
			return "close_session"
		
		elif operation == "close_session":
			return "completed"

		elif operation == "import_list":
			# Po liście - koniec pracy tego rekordu (parent)
			return "completed"

		elif operation == "import_invoice":
			# Po pobraniu XML - idziemy do restore_invoice
			return "restore_invoice"

		elif operation == "restore_invoice":
			# Po odtworzeniu faktury - koniec
			return "completed"

		return None

	# =======================================================================================

	#	po zmianie z _process_single_ksef_step
	#def _process_single_ksef_step(self):
	def _process_java_flow( self):
		"""
		Przetwarza JEDEN krok KSeF dla zablokowanego rekordu.
		"""
		try:
			# 1. Oznacz jako w trakcie przetwarzania i COMMIT (hard commit)
			self.write({
				'is_processing': True,
				'processing_pid': os.getpid(),
				'processing_lock_until': fields.Datetime.now() + timedelta(minutes=10),
				'ksef_status': 'in_progress',
				'ksef_last_execution': fields.Datetime.now(),
			})
			
			# HARD COMMIT - uwalniamy blokadę FOR UPDATE
			self.env.cr.commit()
			
			# 2. Pobierz provider KSeF
			provider = self.provider_id
			if not provider or provider.provider_type != 'ksef':
				self._handle_ksef_error("Invalid provider type")
				return False

			# ============================================
			# A. SPRAWDŹ I ODSWIEŻ TOKENY PRZED OPERACJĄ
			# ============================================
			operations_requiring_tokens = [
				'open_session', 
				'send_invoice', 
				'check_status',  
				'close_session', 
				'import_list',
				'import_invoice',
				'import_invoices'
			]

			# specjalna obsługa zamykania sesji
			if self.ksef_operation == 'close_session':
				should_close, reason = self._should_close_session()
				if not should_close:
					_logger.warning(f"[KSeF] Cannot close session: {reason}")
					# Jeśli nie możemy zamknąć sesji, to nie pomijajmy - oznacza to błąd
					self._handle_ksef_error(f"Cannot close session: {reason}")
					return False
				else:
					_logger.info(f"[KSeF] Proceeding with close_session: {reason}")
					# Kontynuuj normalne wykonanie close_session przez Java JAR

			if self.ksef_operation in operations_requiring_tokens:
				_logger.info(f"[KSeF] Checking tokens for {self.ksef_operation}")
				
				# Użyj istniejącej metody
				is_valid, needs_refresh, error_msg = self._check_tokens_validity()
				_logger.info(f"[KSeF] Token status: valid={is_valid}, needs_refresh={needs_refresh}, msg={error_msg}")
				
				# Jeśli tokeny nieważne → wykonaj auth
				if not is_valid:
					_logger.warning(f"[KSeF] Tokens invalid, running auth before {self.ksef_operation}")
					
					# Zapamiętaj oryginalną operację
					original_operation = self.ksef_operation
					
					try:
						# Tymczasowo ustaw auth
						self.ksef_operation = 'auth'
						
						# Wykonaj auth (używając istniejącej logiki)
						if self._should_use_python(provider):
							auth_result = self._execute_ksef_python_operation(provider)
						else:
							auth_result = self._execute_ksef_java_operation(provider)
						
						# Sprawdź wynik auth
						if not auth_result.get('success'):
							self.ksef_operation = original_operation
							self._handle_ksef_error(f"Auth failed before {original_operation}: {auth_result.get('error')}")
							return False
						
						self._save_tokens_from_auth_result(auth_result)
						_logger.info(f"[KSeF] Auth successful, saved new tokens")
						
					finally:
						# ZAWSZE przywróć oryginalną operację (nawet jeśli auth się nie udało)
						self.ksef_operation = original_operation
						self.env.cr.commit()  # Commit zmiany operacji

			# 3. Call appropriate implementation
			if self._should_use_python(provider):
				result = self._execute_ksef_python_operation(provider)  # Python
			else:
				result = self._execute_ksef_operation(provider)			# Java

			# 4. Obsłuż wynik
			if result.get('success'):
				self._handle_ksef_success(result)
			else:
				self._handle_ksef_error(result.get('error', 'Unknown error'))
			
			# 5. Odblokuj rekord
			self.write({'is_processing': False})
			self.env.cr.commit()
			
			return True
			
		except Exception as e:
			_logger.error(f"[KSeF] Error in step processing for log {self.id}: {e}")
			
			# W razie błędu - odblokuj i zaplanuj retry
			self.write({
				'is_processing': False,
				'ksef_status': 'failed',
				'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=5),
				'provider_message': f"Processing error: {str(e)}",
			})
			self.env.cr.commit()
			return False
	
	# NEW
	def _execute_ksef_java_operation(self, provider):
		"""
		Wywołuje operację Java dla bieżącego ksef_operation.
		"""
		_logger.info(f"[KSeF] Starting Java operation '{self.ksef_operation}' for log {self.id}")
		
		# Pobierz konfigurację KSeF
		ksef_config = provider._get_ksef_config()
		if not ksef_config:
			return {
				'success': False,
				'error': "KSeF configuration not found",
				'duration_ms': 0,
			}
		
		# Mapowanie operacji KSeF na pliki JAR
		jar_mapping = {
			'auth': 'ksef-auth.jar',
			'open_session': 'ksef-open-session.jar',
			'send_invoice': 'ksef-send-invoice.jar',
			'close_session': 'ksef-close-session.jar',
			'check_status': 'ksef-check-status.jar',
			'download_upo': 'ksef-download-upo.jar',
			'import_list': 'ksef-get-received-invoices.jar',
			'import_invoice': 'ksef-get-received-invoices.jar', 
			'import_invoices': 'ksef-get-received-invoices.jar',
		}
		
		operation = self.ksef_operation
		jar_file = jar_mapping.get(operation)
		
		if not jar_file:
			return {
				'success': False,
				'error': f"Unknown KSeF operation: {operation}",
				'duration_ms': 0,
			}

		# Zbuduj pełną ścieżkę do JAR-a
		jar_path = ksef_config._get_jar_path(jar_file)
		if not jar_path or not os.path.exists(jar_path):
			return {
				'success': False,
				'error': f"JAR file not found: {jar_file} at {jar_path}",
				'duration_ms': 0,
			}

		# Przygotuj dane wejściowe dla Java (POPRAWIONA METODA)
		input_data = self._prepare_java_input(ksef_config)
		
		# Zapisz request (do debugowania)
		self.store_java_request(json.dumps(input_data, indent=2, ensure_ascii=False))
		
		# DEBUG: Loguj input przed wysłaniem
		_logger.info(f"[KSeF] Sending input to Java JAR: {operation}")
		_logger.debug(f"[KSeF] Input preview: {json.dumps(input_data, ensure_ascii=False)[:500]}...")
		
		# Wywołaj Javę
		start_time = time.time()
		try:
			result = ksef_config._call_java_jar(jar_path, input_data)
			duration_ms = int((time.time() - start_time) * 1000)
			
			# Dodaj duration do wyniku
			result['duration_ms'] = duration_ms
			
			_logger.info(f"[KSeF] Java call completed in {duration_ms}ms, success: {result.get('success', False)}")
			
			# Zapisz odpowiedź
			response_str = json.dumps(result, indent=2, ensure_ascii=False)
			self.store_java_response(response_str)
			
			# Parsuj kontekst
			self.parse_java_response_to_context()
			
			# Zapisz czas wykonania
			self.write({'duration_ms': duration_ms})
			
			# Dodatkowe logowanie dla debugowania
			if result.get('success'):
				_logger.info(f"[KSeF] Java operation '{operation}' succeeded")
			else:
				_logger.error(f"[KSeF] Java operation '{operation}' failed: {result.get('error', 'Unknown error')}")
			
			return result
			
		except subprocess.TimeoutExpired:
			duration_ms = int((time.time() - start_time) * 1000)
			error_msg = f"Java process timeout after {duration_ms}ms"
			
			_logger.error(f"[KSeF] Java timeout for log {self.id}, operation: {operation}")
			
			return {
				'success': False,
				'error': error_msg,
				'duration_ms': duration_ms,
			}
			
		except Exception as e:
			duration_ms = int((time.time() - start_time) * 1000)
			error_msg = f"Java execution failed: {str(e)}"
			
			_logger.error(f"[KSeF] Java error for log {self.id}, operation: {operation}: {e}", exc_info=True)
			
			return {
				'success': False,
				'error': error_msg,
				'duration_ms': duration_ms,
			}


	# ============================================
	# METODA _execute_ksef_python_operation (ZMIENIONA)
	# ============================================
	def _execute_ksef_python_operation(self, provider):
		"""
		Wywołuje operację KSeF w Python (analogicznie do Java JAR).
		Struktura IDENTYCZNA jak _execute_ksef_java_operation.
		"""
		_logger.info(f"[KSeF Python] Starting Python operation '{self.ksef_operation}' for log {self.id}")
		
		# 1. Pobierz konfigurację KSeF
		ksef_config = provider._get_ksef_config()
		if not ksef_config:
			return {
				'success': False,
				'error': "KSeF configuration not found",
				'duration_ms': 0,
			}
		
		# 2. Mapowanie operacji KSeF na funkcje Python (analogicznie do JAR mapping)
		python_operation_mapping = {
			'download_upo': '_execute_python_download_upo',
			'restore_invoice': '_execute_python_restore_invoice',
		}
	
		operation = self.ksef_operation
		python_method_name = python_operation_mapping.get(operation)
		
		if not python_method_name:
			return {
				'success': False,
				'error': f"Unsupported Python operation: {operation}",
				'duration_ms': 0,
			}
		
		# 3. Przygotuj dane wejściowe dla Python (POPRAWIONA METODA)
		input_data = self._prepare_python_input(ksef_config)
		
		# Zapisz request (do debugowania) - IDENTYCZNIE jak Java
		self.store_java_request(json.dumps(input_data, indent=2, ensure_ascii=False))
		
		# DEBUG: Loguj input przed wysłaniem
		_logger.info(f"[KSeF Python] Sending input to Python operation: {operation}")
		_logger.debug(f"[KSeF Python] Input preview: {json.dumps(input_data, ensure_ascii=False)[:500]}...")
		
		# 4. Wywołaj Python metodę (analogicznie do Java)
		start_time = time.time()
		try:
			# Użyj dynamicznego wywołania metody
			python_method = getattr(self, python_method_name)
			result = python_method(ksef_config, input_data)  # <--- ZMIANA: dodano input_data
			duration_ms = int((time.time() - start_time) * 1000)
			
			# Dodaj duration do wyniku
			result['duration_ms'] = duration_ms
			
			_logger.info(f"[KSeF Python] Python call completed in {duration_ms}ms, success: {result.get('success', False)}")
			
			# Zapisz odpowiedź IDENTYCZNIE jak Java
			try:
				response_str = json.dumps(result, indent=2, ensure_ascii=False)
			except Exception as e:
				_logger.warning(f"[KSeF Python] JSON serialization failed: {e}, storing as string\n{result}")
				response_str = str(result)
			self.store_java_response(response_str)
			
			# Parsuj kontekst IDENTYCZNIE jak Java
			self.parse_java_response_to_context()
			
			# Zapisz czas wykonania
			self.write({'duration_ms': duration_ms})
			
			# Dodatkowe logowanie dla debugowania
			if result.get('success'):
				_logger.info(f"[KSeF Python] Python operation '{operation}' succeeded")
			else:
				_logger.error(f"[KSeF Python] Python operation '{operation}' failed: {result.get('error', 'Unknown error')}")
			
			return result
			
		except Exception as e:
			duration_ms = int((time.time() - start_time) * 1000)
			error_msg = f"Python execution failed: {str(e)}"
			
			_logger.error(f"[KSeF Python] Python error for log {self.id}, operation: {operation}: {e}", exc_info=True)
			
			return {
				'success': False,
				'error': error_msg,
				'duration_ms': duration_ms,
			}


	# ============================================
	# METODA _execute_python_restore_invoice
	# ============================================
	def _execute_python_restore_invoice(self, ksef_config, input_data):
		"""
		Python implementation: odtwarza fakturę z XML w Odoo.
		Struktura IDENTYCZNA jak _execute_python_download_upo.
		"""
		try:
			# 1. Wywołaj istniejącą metodę odtwarzania
			invoice = self.action_restore_ksef_invoice()
			invoice.ksef_process_state = 'imported'
			
			# 2. Przygotuj strukturę wyniku (identyczną do innych operacji Python)
			return {
				'success': True,
				'data': {
					'move_id': invoice.id,
					'move_created': True,  # Zawsze True dla action_restore_ksef_invoice
					'move_updated': False,
					'ksef_number': self.ksef_invoice_number,
					'invoice_number': invoice.name,
					'invoice_date': invoice.invoice_date,
					'move_type': invoice.move_type,
					'state': invoice.state,
				},
				'context': {
					'operation': 'restore_invoice',
					'timestamp': fields.Datetime.now().isoformat(),
					'invoice_restored': True,
					'move_id': invoice.id,
				}
			}
			
		except ValidationError as e:
			# Obsługa błędów walidacji
			return {
				'success': False,
				'error': str(e),
				'data': {
					'restored': False,
					'error_type': 'validation_error',
				}
			}
		except Exception as e:
			# Obsługa innych błędów
			return {
				'success': False,
				'error': str(e),
				'data': {
					'restored': False,
					'error_type': 'unexpected_error',
				}
			}


	def _execute_python_download_upo(self, ksef_config, input_data):
		"""
		Python implementation: pobiera UPO XML, parsuje, zapisuje załącznik,
		aktualizuje account.move z NumerKSeFDokumentu.
		AKCEPTOWANE input_data zgodne z _prepare_python_input.
		"""
		import xml.etree.ElementTree as ET
		from io import BytesIO
		
		_logger.info(f"[KSeF Python] Starting download_upo execution")
		
		try:
			# 1. Pobierz dane z input_data (z _prepare_python_input)
			upo_context = input_data.get('context', {}).get('upo', {})
			
			download_url = upo_context.get('url')
			upo_reference = upo_context.get('referenceNumber')
			
			if not download_url:
				raise ValueError("Missing download URL in input data")
			
			_logger.info(f"[KSeF Python] Downloading UPO from: {download_url[:100]}...")
			
			# 2. Pobierz XML
			response = requests.get(
				download_url,
				timeout=30,
				headers={
					'User-Agent': 'Odoo KSeF Integration/1.0',
					'Accept': 'application/xml'
				}
			)
			
			response.raise_for_status()
			xml_content = response.content
			_logger.info(f"[KSeF Python] UPO downloaded: {len(xml_content)} bytes")
			
			# 3. Parsuj XML żeby wyciągnąć NumerKSeFDokumentu
			numer_ksef = None
			try:
				# XML może mieć namespace
				root = ET.fromstring(xml_content)
				
				# Szukaj NumerKSeFDokumentu (może być z namespace)
				namespaces = {
					'ns': 'http://crd.gov.pl/wzor/2023/12/13/12648/'  # przykładowy namespace UPO
				}
				
				# Próba 1: Bez namespace
				for elem in root.iter():
					if elem.tag.endswith('NumerKSeFDokumentu'):
						numer_ksef = elem.text
						break
				
				# Próba 2: Z namespace
				if not numer_ksef:
					for ns in namespaces.values():
						try:
							elem = root.find(f'.//{{{ns}}}NumerKSeFDokumentu')
							if elem is not None and elem.text:
								numer_ksef = elem.text
								break
						except:
							pass
				
				# Próba 3: Szukaj po tekście w całym XML
				if not numer_ksef:
					xml_text = xml_content.decode('utf-8', errors='ignore')
					import re
					match = re.search(r'<NumerKSeFDokumentu[^>]*>([^<]+)</NumerKSeFDokumentu>', xml_text)
					if match:
						numer_ksef = match.group(1)
				
				_logger.info(f"[KSeF Python] Parsed UPO XML, NumerKSeFDokumentu: {numer_ksef}")
				
			except Exception as e:
				_logger.warning(f"[KSeF Python] Error parsing UPO XML: {e}")
				numer_ksef = None
			
			# 4. Zapisz jako załącznik do account.move
			if self.document_model != 'account.move':
				raise ValueError(f"download_upo only for account.move, not {self.document_model}")
			
			record = self.env[self.document_model].browse(self.document_id)
			if not record.exists():
				raise ValueError(f"Document {self.document_id} not found")
			
			# Utwórz załącznik
			attachment = self.env['ir.attachment'].with_company(self.company_id).create({
				'company_id': self.company_id.id,
				'name': f"UPO_{upo_reference or 'unknown'}.xml",
				'datas': base64.b64encode(xml_content),
				'res_model': self.document_model,
				'res_id': self.document_id,
				'type': 'binary',
				'mimetype': 'application/xml',
			})
			
			_logger.info(f"[KSeF Python] Created attachment: {attachment.id}")
			
			# 5. Aktualizuj account.move z NumerKSeFDokumentu
			invoice_updated = False
			if numer_ksef and hasattr(record, 'ksef_number'):
				record.write({
					'ksef_number': numer_ksef,
					'ksef_sent_date': fields.Datetime.now(),
				})
				invoice_updated = True
				_logger.info(f"[KSeF Python] Updated account.move {record.id}: ksef_number={numer_ksef}")
			
			# 6. Przygotuj wynik (analogiczny do Java)
			return {
				'success': True,
				'data': {
					'upo_reference': upo_reference,
					'content_size': len(xml_content),
					'numer_ksef_dokumentu': numer_ksef,
					'attachment_id': attachment.id,
					'invoice_updated': invoice_updated,
					'invoice_id': record.id,
				},
				'context': {
					'operation': 'download_upo',
					'timestamp': fields.Datetime.now().isoformat(),
					'upo_downloaded': True,
					'numer_ksef': numer_ksef,
				}
			}
			
		except requests.exceptions.RequestException as e:
			_logger.error(f"[KSeF Python] HTTP request failed: {e}")
			raise ValueError(f"HTTP request failed: {e}")
		except Exception as e:
			_logger.error(f"[KSeF Python] Unexpected error in download_upo: {e}", exc_info=True)
			raise

	# inteligentnie buduje context dla każdej operacji
	def _prepare_java_input(self, ksef_config):
		"""
		Przygotowuje JSON input dla Java JAR w poprawnym formacie dla każdej operacji.
		
		Struktury:
		- auth: config + credentials
		- open_session: runtime + context + tokens (z output auth)
		- send_invoice: runtime + context + tokens + params (invoice_xml)
		- check_status/download_upo/close_session: runtime + context + tokens + params
		- import_list: runtime + context + tokens + params
		- import_invoice: runtime + context + tokens + params
		- import_invoices: runtime + context + tokens + params
		"""
		
		# ============================================
		# 1. OPERACJA AUTH - struktura z config/credentials
		# ============================================
		if self.ksef_operation == 'auth':
			# BUDUJ CONFIG
			config = {
				"operation": "auth",
				"environment": ksef_config.environment,
				"auth_type": ksef_config.auth_type,
				"base_url": ksef_config.base_url,
			}
			
			# BUDUJ CREDENTIALS
			credentials = {}
			
			if ksef_config.auth_type == 'certificate':
				if ksef_config.auth_keystore_p12 and ksef_config.auth_keystore_p12.datas:
					data = ksef_config.auth_keystore_p12.datas
					
					if isinstance(data, bytes):
						data = data.decode('ascii')
					
					if data.startswith('TUlJ'):  # "TUlJ" to base64("MII")
						data = base64.b64decode(data).decode('ascii')
						_logger.warning(f"[KSeF] Auth cert was double-base64, decoded")
					
					credentials['auth_certificate'] = data
					credentials['auth_password'] = ksef_config.auth_keystore_password or ""
					credentials['auth_alias'] = "ksef-auth"

				if ksef_config.sign_keystore_p12 and ksef_config.sign_keystore_p12.datas:
					data = ksef_config.sign_keystore_p12.datas
					
					if isinstance(data, bytes):
						data = data.decode('ascii')
					
					if data.startswith('TUlJ'):
						data = base64.b64decode(data).decode('ascii')
					
					credentials['sign_certificate'] = data
					credentials['sign_password'] = ksef_config.sign_keystore_password or ""
					credentials['sign_alias'] = "ksef-sign"

				if ksef_config.mf_certificate_pem:
					credentials['mf_public_key'] = ksef_config.mf_certificate_pem

				# ✅ KLUCZOWE: NIP jest WYMAGANY dla komunikacji KSeF
				if not ksef_config.company_nip:
					raise ValidationError(
						f"Brak NIP firmy w konfiguracji KSeF! "
						f"NIP jest wymagany do autoryzacji z KSeF. "
						f"Sprawdź konfigurację providera lub VAT firmy."
					)
				
				# ✅ NIP musi mieć 10 cyfr
				nip = ksef_config.company_nip.strip()
				if len(nip) != 10 or not nip.isdigit():
					raise ValidationError(
						f"Nieprawidłowy NIP firmy: '{ksef_config.company_nip}'. "
						f"NIP musi składać się z 10 cyfr."
					)
				
				credentials['nip'] = nip
				_logger.info(f"[KSeF] Using NIP: {nip}")

					
			elif ksef_config.auth_type == 'jet_token':
				credentials.update({
					'jet_api_key': ksef_config.jet_api_key or "",
					'jet_api_token': ksef_config.jet_api_token or "",
				})
				# ✅ KLUCZOWE: NIP jest WYMAGANY dla komunikacji KSeF
				if not ksef_config.company_nip:
					raise ValidationError(
						f"Brak NIP firmy w konfiguracji KSeF! "
						f"NIP jest wymagany do autoryzacji z KSeF. "
						f"Sprawdź konfigurację providera lub VAT firmy."
					)
			 
				# ✅ NIP musi mieć 10 cyfr
				nip = ksef_config.company_nip.strip()
				if len(nip) != 10 or not nip.isdigit():
					raise ValidationError(
						f"Nieprawidłowy NIP firmy: '{ksef_config.company_nip}'. "
						f"NIP musi składać się z 10 cyfr."
					)
			 
				credentials['nip'] = nip
				_logger.info(f"[KSeF] Using NIP: {nip}")
			
			# Struktura dla auth
			return {
				"config": config,
				"credentials": credentials,
				"context": None,
				"params": None
			}

		# ============================================
		# 2. OPERACJA OPEN_SESSION - struktura z runtime/context/tokens
		# ============================================
		elif self.ksef_operation == 'open_session':
			if not self.payload_context:
				raise ValueError("Missing auth context")
			
			payload_ctx = json.loads(self.payload_context)
			
			# WALIDACJA - czy mamy wymagane pola
			runtime = payload_ctx.get('runtime', {})
			if not runtime.get('baseUrl'):
				runtime['baseUrl'] = ksef_config.base_url
				#raise ValueError("Java JAR auth didn't return baseUrl in runtime")
			
			if not payload_ctx.get('tokens', {}).get('accessToken'):
				raise ValueError("Java JAR auth didn't return accessToken")
			
			return {
				"runtime": runtime,
				"context": payload_ctx.get('context', {}),
				"tokens": payload_ctx.get('tokens', {})
			}
		
		# ============================================
		# 3. OPERACJA SEND_INVOICE
		# ============================================
		elif self.ksef_operation == 'send_invoice':
			# Pobierz session_runtime (to jest output z open_session zapisany w bazie)
			if not self.session_runtime:
				raise ValueError("Missing session runtime for send_invoice")
			
			session_ctx = json.loads(self.session_runtime)
			
			# DEBUG: Sprawdź co mamy w session_ctx
			_logger.info(f"[KSeF DEBUG] Session runtime keys: {list(session_ctx.keys())}")
			
			# KLUCZOWA POPRAWKA: Usuń nested context jeśli zawiera tylko nip
			if 'context' in session_ctx:
				nested_context = session_ctx['context']
				# Sprawdź czy to tylko {"nip": "..."}
				if isinstance(nested_context, dict) and len(nested_context) == 1 and 'nip' in nested_context:
					_logger.info(f"[KSeF DEBUG] Removing nested context with only nip: {nested_context}")
					del session_ctx['context']
				else:
					_logger.warning(f"[KSeF DEBUG] Nested context has unexpected structure: {nested_context}")
			
			# Reszta kodu bez zmian...
			config = {
				"environment": ksef_config.environment,
				"company_nip": ksef_config.company_nip,
				"auth_type": ksef_config.auth_type,
				"base_url": ksef_config.base_url,
			}
			
			if isinstance(self.file_data, bytes):
				# Sprawdź czy to już Base64
				try:
					# Spróbuj zdekodować - jeśli się uda, to już jest Base64
					test_decode = base64.b64decode(self.file_data)
					# Jeśli po decode to XML, to file_data już jest Base64
					if test_decode.startswith(b'<?xml'):
						# file_data to Base64 bytes - użyj jako string
						invoice_xml_base64 = self.file_data.decode('ascii')
						_logger.info("[KSeF] file_data already Base64, using as-is")
					else:
						# file_data to raw XML - zakoduj
						invoice_xml_base64 = base64.b64encode(self.file_data).decode('ascii')
						_logger.info("[KSeF] file_data is raw XML, encoding to Base64")
				except:
					# Błąd decode - prawdopodobnie raw XML
					invoice_xml_base64 = base64.b64encode(self.file_data).decode('ascii')
					_logger.info("[KSeF] file_data decode failed, treating as raw XML")
			else:
				invoice_xml_base64 = self.file_data  # już string Base64
			
			input_data = {
				"operation": "send_invoice",
				"config": config,
				"context": session_ctx,  # ← TERAZ BEZ KLUCZA "context"
				"params": {
					"invoice_xml_base64": invoice_xml_base64,
					"file_name": self.file_name or "invoice.xml"
				}
			}
			
			return input_data

		# ============================================
		# 4. OPERACJA CHECK_STATUS
		# ============================================
		elif self.ksef_operation == 'check_status':
			"""
			Przygotowuje input dla check-status.jar.
			Struktura: context.tokens (bez dodatkowego zagnieżdżenia!)
			"""
			
			# ------------------------------------------------------------
			# 1. WYMAGANE DANE - bez if-ów, tylko walidacja
			# ------------------------------------------------------------
			
			# session_runtime jest WYMAGANY dla check_status
			if not self.session_runtime:
				raise ValueError("Missing session_runtime for check_status")
			
			# reference_number jest WYMAGANY
			if not self.ksef_reference_number and not self.external_id:
				raise ValueError("Missing reference number for check_status")
			
			# ------------------------------------------------------------
			# 2. PARSOWANIE - proste, bez if-ów
			# ------------------------------------------------------------
			
			session_ctx = json.loads(self.session_runtime)
			
			# ------------------------------------------------------------
			# 3. BUDOWANIE CONTEXT - użyj tego co jest
			# ------------------------------------------------------------
			
			# Tokeny - użyj z session_ctx lub z payload_context (najświeższe)
			tokens = {}
			
			# Najpierw sprawdź payload_context (mogą być nowsze tokeny z auth)
			if self.payload_context:
				payload_ctx = json.loads(self.payload_context)
				tokens = payload_ctx.get('tokens', {})
			
			# Jeśli nie ma w payload_context, użyj z session_ctx
			if not tokens and 'tokens' in session_ctx:
				tokens = session_ctx['tokens']
			
			# Buduj context z WYMAGANYMI polami
			context = {
				'tokens': tokens,  # WYMAGANE - nawet jeśli puste
				'runtime': session_ctx.get('runtime', {}),
				'session': session_ctx.get('session', {}),
			}
			
			# Dodaj opcjonalne pola jeśli istnieją
			if 'context' in session_ctx and isinstance(session_ctx['context'], dict):
				if 'nip' in session_ctx['context']:
					context['nip'] = session_ctx['context']['nip']
			
			if 'encryptionDebug' in session_ctx:
				context['encryptionDebug'] = session_ctx['encryptionDebug']
			
			# ------------------------------------------------------------
			# 4. PARAMS - WYMAGANY reference_number
			# ------------------------------------------------------------
			
			# Priority: ksef_reference_number > external_id
			reference_number = self.ksef_reference_number or self.external_id
			
			params = {
				'reference_number': reference_number
			}
			
			# ------------------------------------------------------------
			# 5. CREDENTIALS - tylko jeśli auth_type = certificate
			# ------------------------------------------------------------
			
			credentials = {}
			
			if ksef_config.auth_type == 'certificate':
				# AUTH certificate - WYMAGANY dla certificate auth
				if not ksef_config.auth_keystore_p12 or not ksef_config.auth_keystore_p12.datas:
					raise ValueError("Missing auth certificate for certificate auth")
				
				auth_data = ksef_config.auth_keystore_p12.datas
				
				# Konwersja bytes → base64 string
				if isinstance(auth_data, bytes):
					auth_data = base64.b64encode(auth_data).decode('ascii')
				
				# Sprawdź czy to już base64 (po prostu użyj)
				credentials['auth_certificate'] = auth_data
				credentials['auth_password'] = ksef_config.auth_keystore_password or ""
				credentials['auth_alias'] = "ksef-auth"
				
				# SIGN certificate - WYMAGANY dla certificate auth
				if ksef_config.sign_keystore_p12 and ksef_config.sign_keystore_p12.datas:
					sign_data = ksef_config.sign_keystore_p12.datas
					
					if isinstance(sign_data, bytes):
						sign_data = base64.b64encode(sign_data).decode('ascii')
					
					credentials['sign_certificate'] = sign_data
					credentials['sign_password'] = ksef_config.sign_keystore_password or ""
					credentials['sign_alias'] = "ksef-sign"
				
				# NIP - WYMAGANY
				if ksef_config.company_nip:
					credentials['nip'] = ksef_config.company_nip
				else:
					raise ValueError("Missing company NIP for certificate auth")
			
			# ------------------------------------------------------------
			# 6. FINALNA STRUKTURA - WYMAGANE pola
			# ------------------------------------------------------------
			
			input_data = {
				"operation": "check_status",
				"config": {
					"environment": ksef_config.environment,
					"auth_type": ksef_config.auth_type,
					"company_nip": ksef_config.company_nip,
					"base_url": ksef_config.base_url,
				},
				"context": context,	  # BEZ dodatkowego zagnieżdżenia!
				"params": params,
			}
			
			# Dodaj credentials tylko jeśli istnieją
			if credentials:
				input_data["credentials"] = credentials
			
			# ------------------------------------------------------------
			# 7. LOGGING - tylko istotne informacje
			# ------------------------------------------------------------
			
			_logger.info(f"[KSeF] Prepared check_status input:")
			_logger.info(f"  - Reference: {reference_number}")
			_logger.info(f"  - Tokens: {'Present' if tokens else 'Missing'}")
			_logger.info(f"  - Credentials: {'Added' if credentials else 'Not needed'}")
			
			if tokens and 'accessTokenValidUntil' in tokens:
				_logger.info(f"  - Token expiry: {tokens['accessTokenValidUntil']}")
			
			return input_data


		# ============================================
		# 5. OPERACJA CLOSE_SESSION
		# ============================================
		elif self.ksef_operation == 'close_session':
			"""
			Przygotowuje input dla close-session.jar.
			Wersja zaktualizowana zgodnie z nowym JAR-em.
			"""
			# 1. WYMAGANE DANE
			if not self.session_runtime:
				raise ValueError("Missing session_runtime for close_session")
			
			if not self.ksef_reference_number and not self.external_id:
				raise ValueError("Missing reference number for close_session")
			
			# 2. PARSOWANIE session_runtime
			try:
				session_ctx = json.loads(self.session_runtime)
			except json.JSONDecodeError as e:
				raise ValueError(f"Invalid JSON in session_runtime: {e}")
			
			# 3. BUDOWANIE CONTEXT
			# Pobierz tokeny z różnych możliwych źródeł
			tokens = {}
			
			# Najpierw z payload_context (najświeższe)
			if self.payload_context:
				payload_ctx = json.loads(self.payload_context)
				tokens = payload_ctx.get('tokens', {})
			
			# Jeśli nie ma, spróbuj z session_ctx
			if not tokens and 'tokens' in session_ctx:
				tokens = session_ctx['tokens']
			
			# 4. BUDOWANIE INPUT DATA - KLUCZOWA ZMIANA!
			reference_number = self.ksef_reference_number or self.external_id
			
			# Struktura wejściowa dla nowego JAR-a
			input_data = {
				"runtime": {
					"baseUrl": ksef_config.base_url,  # <-- DODAJ TUTAJ base_url z konfiguracji
				},
				"context": session_ctx.get('context', {}),
				"session": session_ctx.get('session', {}),
				"tokens": tokens,
			}
			
			# Jeśli w session_ctx już jest runtime, uaktualnij go
			if 'runtime' in session_ctx:
				input_data['runtime'].update(session_ctx['runtime'])
			
			# Dodaj reference_number jeśli nie ma w session
			if 'session' not in input_data or not input_data['session'].get('referenceNumber'):
				input_data['session'] = input_data.get('session', {})
				input_data['session']['referenceNumber'] = reference_number
			
			# DEBUG: Loguj strukturę
			_logger.info(f"[KSeF] Prepared close_session input:")
			_logger.info(f"  - Base URL: {ksef_config.base_url}")
			_logger.info(f"  - Reference: {reference_number}")
			_logger.info(f"  - Token present: {'Yes' if tokens else 'No'}")
			
			return input_data


		#
		#
		#############################################################################################################
		elif self.ksef_operation in ['download_upo']:
			# Pobierz dane sesji z session_runtime
			if not self.session_runtime:
				raise ValueError(f"Missing session runtime for {self.ksef_operation}. Run open_session first.")
			
			try:
				session_ctx = json.loads(self.session_runtime)
				
				# DEBUG: Sprawdź strukturę session
				_logger.info(f"[KSeF] Session runtime keys: {list(session_ctx.keys())}")
				
				# Podstawowa struktura
				input_data = {
					"runtime": session_ctx.get('runtime', {}),
					"context": session_ctx.get('context', {}),
					"tokens": session_ctx.get('tokens', {}),
				}
				
				# Dodaj specyficzne parametry dla każdej operacji
				params = {}
				
				if self.ksef_operation == 'send_invoice' and self.file_data:
					try:
						invoice_xml = base64.b64decode(self.file_data).decode('utf-8')
						params['invoice_xml'] = invoice_xml
						_logger.info(f"[KSeF] Prepared invoice XML, length: {len(invoice_xml)} chars")
					except Exception as e:
						raise ValueError(f"Error decoding invoice XML: {e}")
				
				elif self.ksef_operation in ['check_status', 'download_upo']:
					# Użyj reference_number z logu lub z session
					ref = self.ksef_reference_number or self.external_id
					if ref:
						params['reference_number'] = ref
					elif session_ctx.get('session') and session_ctx['session'].get('referenceNumber'):
						params['reference_number'] = session_ctx['session']['referenceNumber']
					else:
						_logger.warning(f"[KSeF] No reference number found for {self.ksef_operation}")
				
				elif self.ksef_operation == 'import_invoices':
					# Parametry dla importu faktur (data range, etc.)
					# Można dodać później
					pass
				
				# Dodaj params jeśli są
				if params:
					input_data["params"] = params
				
				return input_data
				
			except json.JSONDecodeError as e:
				raise ValueError(f"Invalid JSON in session_runtime: {e}")
			except Exception as e:
				raise ValueError(f"Error preparing {self.ksef_operation} input: {e}")


		# ============================================
		# 6. INPUT DLA RÓŻNYCH OPERACJI IMPORTU
		# ============================================
		elif self.ksef_operation in ['import_list', 'import_invoice', 'import_invoices']:
			# 1. Pobierz dane z payload_context (tokeny z auth)
			if not self.payload_context:
				raise ValueError(f"Missing auth context for {self.ksef_operation}")
			
			payload_ctx = json.loads(self.payload_context)
			
			# 2. Podstawowa struktura
			input_data = {
				"operation": "import_invoices",  # Java oczekuje TYLKO "import_invoices"
				"config": {
					"environment": ksef_config.environment,
					"auth_type": ksef_config.auth_type,
					"company_nip": ksef_config.company_nip,
					"base_url": ksef_config.base_url,
				},
				"context": payload_ctx,  # musi zawierać tokens
				"params": {}
			}
			
			# 3. DODAJ SPECYFICZNE PARAMETRY DLA KAŻDEJ OPERACJI
			
			# a) import_list - TYLKO lista (bez pobierania)
			if self.ksef_operation == 'import_list':
				input_data["params"] = {
					"days_back": self.ksef_import_days_back or 60,
					"page_size": self.ksef_import_page_size or 50,
					"download_all": False,  # NIE pobieraj faktur
				}
			
			# b) import_invoice - POJEDYNCZA faktura po ksef_number
			elif self.ksef_operation == 'import_invoice':
				if not self.ksef_invoice_number:
					raise ValueError("Missing ksef_invoice_number for import_invoice")
				
				# Java oczekuje operation: "import_invoices" ale z params.ksef_number
				input_data = {
					"operation": "import_invoices",
					"config": {
						"environment": ksef_config.environment,
						"auth_type": ksef_config.auth_type,
						"company_nip": ksef_config.company_nip,
						"base_url": ksef_config.base_url,
					},
					"context": payload_ctx,
					"params": {
						"ksef_number": self.ksef_invoice_number,  # <-- POJEDYNCZA FAKTURA
						#"download_dir": self.ksef_download_dir or "/tmp/ksef_invoices",
					}
				}

			# c) import_invoices - LISTA + pobranie (combo)
			elif self.ksef_operation == 'import_invoices':
				input_data["params"] = {
					"days_back": self.ksef_import_days_back or 60,
					"page_size": self.ksef_import_page_size or 50,
					"download_all": self.ksef_download_all or False,
					#"download_dir": self.ksef_download_dir or "/tmp/ksef_invoices",
				}
			
			return input_data
		
		# ============================================
		# 7. OPERACJE NIEZNANE
		# ============================================
		else:
			raise ValueError(f"Unsupported KSeF operation: {self.ksef_operation}")

	# ============================================
	# METODY DO OBSŁUGI RETRY I DELAY
	# ============================================
	
	def _calculate_retry_delay(self):
		"""
		Oblicza opóźnienie przed ponowną próbą (exponential backoff).
		
		Returns:
			int: Opóźnienie w minutach
		"""
		if self.ksef_operation == 'check_status':
			# 2, 5, 10, 15, 30, 60 minut...
			delays = [2, 5, 10, 15, 30, 60]
			retry_idx = min(self.ksef_retry_count - 1, len(delays) - 1)
			return delays[max(retry_idx, 0)]

		# Dla innych operacji: exponential backoff
		delay = 5 * (2 ** (self.ksef_retry_count - 1))
		return min(delay, 120)  # Max 2 godziny
	
	def _get_min_delay_for_operation(self, operation):
		"""
		Minimalny czas między operacjami (zapobiega zbyt częstym wywołaniom).
		
		Args:
			operation (str): Nazwa operacji KSeF
			
		Returns:
			int: Minimalny czas w sekundach
		"""
		delays = {
			'check_status': 300,	# 5 minut między sprawdzaniem statusu
			'download_upo': 120,	# 2 minuty
			'auth': 60,			 # 1 minuta
			'open_session': 60,
			'send_invoice': 60,
			'close_session': 60,
			'import_invoices': 300, # 5 minut
		}
		return delays.get(operation, 60)
	
	def _can_process_ksef_step(self):
		"""
		Sprawdza czy krok KSeF może być wykonany.
		
		Returns:
			bool: True jeśli można przetwarzać
		"""
		# 1. Sprawdź podstawowe warunki
		if self.ksef_operation in ['completed', 'failed']:
			return False
		
		if self.ksef_status not in ['pending', 'waiting_delay']:
			return False
		
		if self.is_processing and self.processing_lock_until > fields.Datetime.now():
			return False
		
		# 2. Sprawdź czy nie za wcześnie dla następnego wykonania
		if self.ksef_next_execution and self.ksef_next_execution > fields.Datetime.now():
			return False
		
		# 3. Sprawdź minimalny czas od ostatniego wykonania
		if self.ksef_last_execution:
			min_delay = self._get_min_delay_for_operation(self.ksef_operation)
			elapsed = (fields.Datetime.now() - self.ksef_last_execution).total_seconds()
			if elapsed < min_delay:
				return False
		
		# 4. Sprawdź provider
		if not self.provider_id or self.provider_id.provider_type != 'ksef':
			return False
		
		return True
	
	# zarządzanie sekwencją
	def _determine_next_ksef_operations(self, result):
		"""
		Określa następne operacje na podstawie wyniku - ULEPSZONA WERSJA.
		"""
		# Domyślna sekwencja dla export
		if self.direction == 'export':
			sequence = ['auth', 'open_session', 'send_invoice', 'close_session']
			
			# Dodaj check_status i download_upo jeśli włączone
			if self.provider_id and hasattr(self.provider_id, '_get_ksef_config'):
				ksef_config = self.provider_id._get_ksef_config()
				if ksef_config and ksef_config.auto_check_status:
					sequence.extend(['check_status', 'download_upo'])
			
			sequence.append('completed')
			
		elif self.direction == 'import':
			# DEBUG - bardziej szczegółowe
			_logger.info(f"[KSeF DEBUG] Import flow for operation: {self.ksef_operation}")
			
			if self.ksef_operation == 'auth':
				# Dla auth zawsze idź do import_invoice jeśli mamy numer faktury
				if self.ksef_invoice_number:
					sequence = ['auth', 'import_invoice', 'completed']
					_logger.info(f"[KSeF DEBUG] Auth with invoice {self.ksef_invoice_number} → import_invoice")
				else:
					sequence = ['auth', 'import_list', 'completed']
					_logger.info(f"[KSeF DEBUG] Auth without invoice → import_list")
			
			elif self.ksef_operation == 'import_list':
				sequence = ['import_list', 'completed']
				_logger.info(f"[KSeF DEBUG] import_list → completed")
			
			elif self.ksef_operation == 'import_invoice':
				sequence = ['import_invoice', 'completed']
				_logger.info(f"[KSeF DEBUG] import_invoice → completed")
			
			elif self.ksef_operation == 'import_invoices':
				sequence = ['import_invoices', 'completed']
				_logger.info(f"[KSeF DEBUG] import_invoices → completed")
			
			else:
				_logger.error(f"[KSeF DEBUG] Unknown import operation: {self.ksef_operation}")
				sequence = []
		
		# DEBUG: Zapisz sekwencję
		_logger.info(f"[KSeF DEBUG] Sequence for {self.direction}: {sequence}")
		_logger.info(f"[KSeF DEBUG] Current operation: {self.ksef_operation}")
		
		# Znajdź bieżącą operację w sekwencji
		try:
			current_idx = sequence.index(self.ksef_operation)
			_logger.info(f"[KSeF DEBUG] Current index in sequence: {current_idx}")
			
			if current_idx + 1 < len(sequence):
				next_op = sequence[current_idx + 1]
			else:
				next_op = 'completed'
				
			# Określ następną po następnej
			if next_op == 'completed':
				after_next = 'none'
			else:
				try:
					next_idx = sequence.index(next_op)
					if next_idx + 1 < len(sequence):
						after_next = sequence[next_idx + 1]
					else:
						after_next = 'completed'
				except ValueError:
					after_next = 'none'
					
		except ValueError:
			# Bieżąca operacja nie jest w sekwencji
			_logger.warning(f"[KSeF] Operation {self.ksef_operation} not in sequence {sequence}")
			next_op = 'failed'
			after_next = 'none'
		
		# Określ czas następnego wykonania
		next_execution = fields.Datetime.now()
		
		# Specyficzne opóźnienia dla operacji
		if next_op == 'check_status':
			# 2 minuty po zamknięciu sesji
			delay_minutes = 2
			if self.provider_id and hasattr(self.provider_id, '_get_ksef_config'):
				ksef_config = self.provider_id._get_ksef_config()
				if ksef_config:
					delay_minutes = ksef_config.status_check_delay
			next_execution = fields.Datetime.now() + timedelta(minutes=delay_minutes)
		
		elif next_op == 'download_upo':
			# Natychmiast po check_status
			next_execution = fields.Datetime.now()
		
		elif next_op == 'close_session':
			# 1 minuta po wysłaniu
			next_execution = fields.Datetime.now() + timedelta(minutes=1)
		
		_logger.info(f"[KSeF DEBUG] Next operations: current={next_op}, after={after_next}, exec={next_execution}")
		
		return {
			'current': next_op,
			'next': after_next,
			'next_execution': next_execution,
		}

	# METODA POMOCNICZA DO ZAPISU FAKTUR
	def _save_invoice_as_attachment(self, ksef_number, invoice_xml_base64, move_id=None):
		"""
		Zapisuje fakturę XML jako załącznik i tworzy/linkuje account.move.
		
		Args:
			ksef_number (str): Numer KSeF faktury
			invoice_xml_base64 (str): Zawartość faktury w Base64
			move_id (int): ID istniejącego account.move (opcjonalnie)
		
		Returns:
			tuple: (account.move record, ir.attachment record)
		"""
		try:
			# 1. Dekoduj XML
			invoice_xml = base64.b64decode(invoice_xml_base64)
			xml_content = invoice_xml.decode('utf-8', errors='ignore')
			
			# 2. Parsuj XML aby wyciągnąć dane faktury
			import xml.etree.ElementTree as ET
			try:
				root = ET.fromstring(xml_content)
				namespaces = {'ns': 'http://crd.gov.pl/wzor/2023/12/13/12648/'}
				
				# Wyciągnij numer faktury, datę, NIPy, kwoty
				invoice_data = self._parse_invoice_xml(root, namespaces)
			except Exception as e:
				_logger.warning(f"[KSeF] XML parsing error: {e}, using basic data")
				invoice_data = {
					'invoice_number': ksef_number.split('-')[0] if '-' in ksef_number else ksef_number,
					'invoice_date': fields.Date.today(),
				}
			
			# 3. Znajdź lub utwórz account.move
			move = None
			
			if move_id:
				# Użyj istniejącego
				move = self.env['account.move'].browse(move_id)
				if not move.exists():
					move = None
			
			if not move:
				# Szukaj po numerze KSeF
				move = self.env['account.move'].search([
					('ksef_number', '=', ksef_number)
				], limit=1)
			
			if not move:
				# Szukaj po numerze faktury
				move = self.env['account.move'].search([
					('invoice_number', '=', invoice_data.get('invoice_number')),
					('partner_id.vat', '=', invoice_data.get('seller_nip')),
					('invoice_date', '=', invoice_data.get('invoice_date')),
				], limit=1)
			
			if not move:
				# Utwórz nowy account.move (szkielet)
				move_vals = {
					'move_type': 'in_invoice',  # Faktura zakupowa
					'partner_id': self._find_or_create_partner(invoice_data.get('seller_nip'),
															 invoice_data.get('seller_name')),
					'invoice_date': invoice_data.get('invoice_date') or fields.Date.today(),
					'invoice_date_due': invoice_data.get('invoice_date_due'),
					'ref': invoice_data.get('invoice_number'),
					'invoice_origin': 'KSeF Import',
					'ksef_number': ksef_number,
					'invoice_amount_untaxed': invoice_data.get('net_amount', 0),
					'invoice_amount_tax': invoice_data.get('vat_amount', 0),
					'amount_total': invoice_data.get('gross_amount', 0),
					'currency_id': self.env.ref('base.PLN').id if invoice_data.get('currency') == 'PLN' else None,
					'state': 'draft',
					'company_id': self.company_id.id,
				}
				move = self.env['account.move'].with_company(self.company_id).create(move_vals)
				_logger.info(f"[KSeF] Created new account.move {move.id} for KSeF {ksef_number}")
			else:
				# Zaktualizuj istniejący
				move.write({
					'ksef_number': ksef_number,
					'ksef_import_date': fields.Datetime.now(),
				})
				_logger.info(f"[KSeF] Updated existing account.move {move.id} with KSeF {ksef_number}")
			
			# 4. Utwórz załącznik POWIĄZANY Z account.move
			attachment_vals = {
				'company_id': move.company_id.id,
				'name': f"KSeF_{ksef_number}.xml",
				'datas': invoice_xml_base64,
				'res_model': 'account.move',
				'res_id': move.id,  # <-- KLUCZOWE: powiązanie z account.move
				'type': 'binary',
				'mimetype': 'application/xml',
				'description': f"Faktura KSeF {ksef_number} zaimportowana {fields.Datetime.now()}",
			}
			
			attachment = self.env['ir.attachment'].with_company(move.company_id).create(attachment_vals)
			_logger.info(f"[KSeF] Saved invoice {ksef_number} as attachment {attachment.id} linked to move {move.id}")
			
			# 5. Zaktualizuj communication.log z ID dokumentu
			if self.document_model == 'account.move' and not self.document_id:
				self.write({
					'document_id': move.id,
					'document_model': 'account.move',
				})
			
			return move, attachment
			
		except Exception as e:
			_logger.error(f"[KSeF] Error saving invoice {ksef_number}: {e}", exc_info=True)
			return None, None

	def _parse_invoice_xml(self, root, namespaces):
		"""
		Parsuje XML faktury FA(3) i wyciąga kluczowe dane.
		"""
		data = {}
		
		# Przykładowa ekstrakcja - dostosuj do rzeczywistego schematu FA(3)
		try:
			# Numer faktury
			nr_faktury = root.find('.//{*}NrFaktury')
			if nr_faktury is not None:
				data['invoice_number'] = nr_faktury.text
			
			# Data wystawienia
			data_wyst = root.find('.//{*}DataWystawienia')
			if data_wyst is not None and data_wyst.text:
				from datetime import datetime
				try:
					data['invoice_date'] = datetime.strptime(data_wyst.text[:10], '%Y-%m-%d').date()
				except:
					pass
			
			# Sprzedawca (Podmiot1)
			sprzedawca = root.find('.//{*}Podmiot1')
			if sprzedawca is not None:
				nip = sprzedawca.find('.//{*}NIP')
				if nip is not None:
					data['seller_nip'] = nip.text
				nazwa = sprzedawca.find('.//{*}Nazwa')
				if nazwa is not None:
					data['seller_name'] = nazwa.text
			
			# Kwoty
			p_13_1 = root.find('.//{*}P_13')
			if p_13_1 is not None:
				try:
					data['net_amount'] = float(p_13_1.text)
				except:
					pass
			
			p_14_1 = root.find('.//{*}P_14')
			if p_14_1 is not None:
				try:
					data['vat_amount'] = float(p_14_1.text)
				except:
					pass
			
			p_15 = root.find('.//{*}P_15')
			if p_15 is not None:
				try:
					data['gross_amount'] = float(p_15.text)
				except:
					pass
			
		except Exception as e:
			_logger.warning(f"[KSeF] XML parsing partial error: {e}")
		
		return data

	def _find_or_create_partner(self, nip, name=None):
		"""
		Znajduje lub tworzy partnera po NIP.
		"""
		if not nip:
			return None
		
		# Szukaj partnera po NIP
		partner = self.env['res.partner'].search([
			('company_id', '=', self.company_id.id),
			('vat', 'ilike', f'%{nip}%')
		], limit=1)
		
		if not partner:
			# Utwórz nowego partnera
			partner_vals = {
				'name': name or f"KSeF {nip}",
				'vat': f"PL{nip}" if len(nip) == 10 else nip,
				'company_type': 'company',
				'supplier_rank': 1,
				'company_id': self.company_id.id
			}
			partner = self.env['res.partner'].with_company(self.company_id).create(partner_vals)
			_logger.info(f"[KSeF] Created new partner {partner.id} for NIP {nip}")
		
		return partner.id
	# end: METODA POMOCNICZA DO ZAPISU FAKTUR

	#	
	def _add_to_history(self, status, result):
		"""
		Dodaje wpis do historii KSeF.
		
		Args:
			status (str): 'success' lub 'failed'
			result (dict): Wynik operacji
			
		Returns:
			list: Zaktualizowana historia
		"""
		history_entry = {
			'operation': self.ksef_operation,
			'status': status,
			'timestamp': datetime.now().isoformat(),
			'duration_ms': result.get('duration_ms', 0),
			'retry_count': self.ksef_retry_count,
		}
		
		# Dodaj dodatkowe informacje w zależności od statusu
		if status == 'success':
			if 'referenceNumber' in result.get('data', {}):
				history_entry['reference_number'] = result['data']['referenceNumber']
			if 'invoiceNumber' in result.get('data', {}):
				history_entry['invoice_number'] = result['data']['invoiceNumber']
		else:
			history_entry['error'] = result.get('error', 'Unknown error')[:500]
		
		current_history = self.ksef_history or []
		current_history.append(history_entry)
		
		# Ogranicz historię do ostatnich 50 wpisów
		if len(current_history) > 50:
			current_history = current_history[-50:]
		
		return current_history

	# zapisuje tokeny i context dla następnych operacji
	def _handle_ksef_success(self, result):
		"""
		Obsługuje sukces operacji KSeF - ZAKTUALIZOWANA WERSJA.
		"""
		# DEBUG
		_logger.info(f"[KSeF DEBUG] _handle_ksef_success called for operation: {self.ksef_operation}")
		_logger.info(f"[KSeF DEBUG] Current ksef_next_operation: {self.ksef_next_operation}")
		_logger.info(f"[KSeF DEBUG] Result keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")

		# ✅ KLUCZOWA POPRAWKA: Jeśli operacja to 'completed' lub 'failed' - NIE przetwarzaj dalej!
		if self.ksef_operation in ['completed', 'failed']:
			_logger.warning(f"[KSeF] Attempted to handle success for already {self.ksef_operation} operation {self.id}")
			return

		# ✅ Również sprawdź czy state już nie jest 'received'/'error'
		if self.state in ['received', 'error'] and self.ksef_operation not in ['import_list', 'auth', 'check_status']:
			_logger.warning(f"[KSeF] Attempted to handle success for already {self.state} record {self.id}")
			return

		# 1. Ustal następną operację
		next_ops = self._determine_next_ksef_operations(result)
		from_ksef_operation = f'{self.ksef_operation}'

		# 2. Przygotuj wartości do update
		update_vals = {
			# Historia i retry
			'ksef_history': self._add_to_history('success', result),
			'ksef_retry_count': 0,
			'ksef_last_execution': fields.Datetime.now(),
			
			# KLUCZOWA ZMIANA: Status zależy od tego czy to koniec sekwencji
			'ksef_status': 'success' if next_ops['current'] == 'success' else 'pending',
			'ksef_operation': next_ops['current'],
			'ksef_next_operation': next_ops['next'],
			'ksef_next_execution': next_ops['next_execution'],
		}
		
		# 2. Specyficzne dane dla operacji
		operation_data = result.get('data', {})

		# =====================================================================
		# AUTH
		# =====================================================================		
		if self.ksef_operation == 'auth':
			# KLUCZOWE: Zapisz tokeny w payload_context dla następnych operacji
			if result.get('context'):
				update_vals['payload_context'] = json.dumps(result['context'], ensure_ascii=False)
				_logger.info(f"[KSeF] Auth success - saved context to payload_context")
			elif result.get('data') and isinstance(result['data'], dict):
				# Fallback: sprawdź czy tokens są w data
				if 'tokens' in result['data']:
					update_vals['payload_context'] = json.dumps({
						'tokens': result['data']['tokens']
					}, ensure_ascii=False)
				elif 'context' in result['data'] and isinstance(result['data']['context'], dict):
					update_vals['payload_context'] = json.dumps(
						result['data']['context'], 
						ensure_ascii=False
					)

		# =====================================================================
		# OPEN SESSION
		# =====================================================================					
		elif self.ksef_operation == 'open_session':
			# Zapisuj token sesji i reference number
			update_vals.update({
				'ksef_session_token': operation_data.get('sessionToken'),
				'ksef_reference_number': operation_data.get('referenceNumber'),
			})
			
			# KLUCZOWE: Zapisz pełny context sesji dla następnych operacji
			if result.get('context'):
				session_context = result['context']
				update_vals.update({
					'session_runtime': json.dumps(session_context, ensure_ascii=False),
					'payload_context': json.dumps(session_context, ensure_ascii=False),
				})
				_logger.info(f"[KSeF] Open session success - saved session runtime")
				
			elif result.get('data') and isinstance(result['data'], dict):
				# Fallback: może context jest w data
				if 'context' in result['data']:
					session_context = result['data']['context']
					update_vals.update({
						'session_runtime': json.dumps(session_context, ensure_ascii=False),
						'payload_context': json.dumps(session_context, ensure_ascii=False),
					})
				
		# =====================================================================
		# SEND INVOICE
		# =====================================================================
		elif self.ksef_operation == 'send_invoice':
			# Java zwraca invoiceReferenceNumber, NIE referenceNumber!
			invoice_ref = operation_data.get('invoiceReferenceNumber')
			invoice_hash = ""
			
			if not invoice_ref:
				_logger.error(f"[KSeF] Java response missing invoiceReferenceNumber: {operation_data}")
				# Może być w context.invoice
				if result.get('context', {}).get('invoice', {}).get('referenceNumber'):
					invoice_ref = result['context']['invoice']['referenceNumber']
			
			if not invoice_ref:
				raise ValueError(f"Java didn't return invoice reference number. Data: {operation_data}")
			
			_logger.info(f"[KSeF] Invoice sent, reference: {invoice_ref}")

			invoice_hash = result.get('data', {}).get('hashSHA256')

			if not invoice_hash:
				invoice_hash = result.get('context', {}).get('invoice', {}).get('hashSHA256')

			if invoice_hash:
				_logger.info(f"[KSeF] ✅ Invoice hash received: {invoice_hash}")
				# zapisanie invoice_hash na fakturze
				document = self.env[self.document_model].browse([self.document_id])
				if document:
					document.ksef_invoice_hash = invoice_hash
			else:
				_logger.warning(f"[KSeF] ⚠️ No invoice hash in response!")
			
			update_vals.update({
				'ksef_invoice_number': invoice_ref,  # Używamy referenceNumber jako invoiceNumber
				'external_id': invoice_ref,
				'ksef_invoice_hash': invoice_hash, # ✅ Zapamiętujemy hash'a faktury
				'ksef_status': 'pending',
			})
			
			# Zapisz context jeśli jest
			if result.get('context'):
				update_vals['payload_context'] = json.dumps(result['context'], ensure_ascii=False)
			
			# Zaktualizuj workflow - UŻYJ invoice_ref!
			self.mark_sent(external_id=invoice_ref)

			# by OdooGPT:
			_logger.debug(f"KSEF OP: {self.ksef_operation}, DATA: {result}")
			if self.ksef_operation == 'send_invoice' and result.get('success'):
				self.ksef_invoice_number = result['data'].get('invoiceReferenceNumber')
				self.mark_sent(external_id=result['data'].get('invoiceReferenceNumber'))

				# ✅ TUTAJ TEŻ DLA PEWNOŚCI:
				if invoice_hash:
					self.write({
						'ksef_invoice_hash': invoice_hash
					})

		# =====================================================================
		# CHECK STATUS
		# =====================================================================
		elif self.ksef_operation == 'check_status':
			"""
			Obsługa check_status z użyciem globalnego mappinga.
			"""
			_logger.info(f"[KSeF] Handling check_status success")
			
			data = result.get('data', {})
			context = result.get('context', {})
			
			status_code = data.get('statusCode', 0)
			try:
				status_code = int(status_code)
			except (TypeError, ValueError):
				status_code = None

			upo_available = data.get('upoAvailable', False)
			
			# 1. POBRZ MAPPING Z GLOBALNEJ STAŁEJ
			mapping = self.KSEF_STATUS_MAPPING.get(status_code)
			
			if not mapping:
				# Domyślny mapping dla nieznanego statusu
				mapping = {
					'state': 'sent' if status_code < 400 else 'error',
					'method': 'mark_status_checked',
					'desc': f'Nieznany status: {status_code}'
				}
				_logger.warning(f"[KSeF] Unknown status code: {status_code}, using default mapping")
			
			state = mapping['state']
			core_method = mapping['method']
			description = mapping['desc']
			
			_logger.info(f"[KSeF] Status {status_code} → state: {state}, method: {core_method}")
			
			# 2. PRZYGOTUJ WARTOŚCI DLA KSeF
			update_vals = {
				'ksef_history': self._add_to_history('success', result),
				'ksef_retry_count': 0,
				'ksef_last_execution': fields.Datetime.now(),
				'ksef_status': 'pending',
				'provider_message': f"{description} (Kod: {status_code})",
			}
			
			# 3. ZAPISZ TOKENY
			if context.get('tokens'):
				current_ctx = json.loads(self.payload_context) if self.payload_context else {}
				current_ctx['tokens'] = context['tokens']
				update_vals['payload_context'] = json.dumps(current_ctx, ensure_ascii=False)
			
			# 4. ✅ POPRAWNA LOGIKA NASTĘPNEJ OPERACJI
			
			if status_code == 200 and upo_available:
				# Sesja zakończona, UPO dostępne → pobierz UPO
				update_vals.update({
					'ksef_operation': 'download_upo',
					'ksef_next_operation': 'completed',
					'ksef_next_execution': fields.Datetime.now(),
					'state': 'queued',  # ✅ KLUCZOWE
					'ksef_status': 'pending',
				})
				
				if data.get('upo', {}).get('pages', []):
					upo = data['upo']['pages'][0]
					update_vals.update({
						'ksef_upo_reference': upo.get('referenceNumber'),
						'ksef_upo_url': upo.get('downloadUrl'),
					})
					
			elif status_code == 200 and not upo_available:
				# Sesja zakończona, UPO NIE gotowe → ponów check_status za X minut
				delay_minutes = 2  # Krótkie opóźnienie dla ponowienia
				if self.provider_id and hasattr(self.provider_id, '_get_ksef_config'):
					ksef_config = self.provider_id._get_ksef_config()
					if ksef_config and hasattr(ksef_config, 'status_check_delay'):
						delay_minutes = ksef_config.status_check_delay
				
				update_vals.update({
					'ksef_operation': 'check_status',  # ✅ PONÓW TĘ SAMĄ OPERACJĘ
					'ksef_next_operation': 'check_status',
					'ksef_next_execution': fields.Datetime.now() + timedelta(minutes=delay_minutes),
					'ksef_status': 'pending',  # ✅ NADAL PENDING (nie success!)
				})
				
				_logger.info(f"[KSeF] UPO not ready, retrying check_status in {delay_minutes} minutes")
				
			elif status_code == 100:  # Sesja otwarta (nie powinno się zdarzyć po close_session)
				# To jest błąd - sesja powinna być zamknięta
				update_vals.update({
					'ksef_operation': 'failed',
					'ksef_next_operation': 'none',
					'ksef_status': 'failed',
					'provider_message': f"ERROR: Session still open (code: 100) after close_session",
				})
				
			elif status_code == 120:  # UPO gotowe (specjalny status)
				update_vals.update({
					'ksef_operation': 'download_upo',
					'ksef_next_operation': 'completed',
					'ksef_status': 'pending',
					'ksef_next_execution': fields.Datetime.now(),
				})
				
			elif status_code in [130, 140]:  # Błędy → koniec flow
				update_vals.update({
					'ksef_operation': 'failed',
					'ksef_next_operation': 'none',
					'ksef_status': 'failed',
				})
			elif status_code in range(440, 460):  # Błędy weryfikacji faktur
				error_desc = self.KSEF_STATUS_MAPPING.get(
					status_code, 
					{'desc': f'Błąd weryfikacji KSeF: {status_code}'}
				)['desc']
				
				update_vals.update({
					'ksef_operation': 'failed',
					'ksef_next_operation': 'none',
					'ksef_status': 'failed',
					'provider_message': f"KSeF error {status_code}: {error_desc}",
				})
		
			# 5. ZAPISZ KSeF WARTOŚCI
			self.write(update_vals)
			
			# 6. WYWOŁAJ ODPOWIEDNIĄ METODĘ CORE
			method_dispatcher = {
				'mark_status_checked': lambda: self.mark_status_checked(
					payload=json.dumps(result, indent=2)
				),
				'mark_received': lambda: self.mark_received(
					payload=json.dumps(result, indent=2)
				),
				'mark_error': lambda: self.mark_error(
					description, operation='check_status'
				),
			}
			
			if core_method in method_dispatcher:
				method_dispatcher[core_method]()
			
			# 7. UPEWNIJ SIĘ ŻE STATE JEST PRAWIDŁOWY
			if self.state != state:
				self.write({'state': state})

		# =====================================================================
		# DOWNLOAD UPO
		# =====================================================================
		elif from_ksef_operation == 'download_upo':
			"""
			Obsługa sukcesu pobrania UPO.
			"""
			_logger.info(f"[KSeF] Handling download_upo success")
			
			data = result.get('data', {})
			
			# 1. PRZYGOTUJ WARTOŚCI SPECYFICZNE DLA download_upo
			update_vals = {
				'ksef_history': self._add_to_history('success', result),
				'ksef_retry_count': 0,
				'ksef_last_execution': fields.Datetime.now(),
				'ksef_status': 'success',
				'provider_message': f"UPO pobrano: {data.get('content_size', 0)} bajtów, "
								   f"Numer KSeF: {data.get('numer_ksef_dokumentu', 'brak')}",
			}
			
			# 2. USTAW NASTĘPNĄ OPERACJĘ
			# Po pobraniu UPO → zamknij sesję
			update_vals.update({
				'ksef_operation': 'completed',
				'ksef_next_operation': 'none',
				#'ksef_next_execution': fields.Datetime.now(),
			})
			
			# 3. ZAPISZ KSeF WARTOŚCI
			self.write(update_vals)
			
			# 4. ✅ KLUCZOWE: Ustaw state przez mark_received()
			# UPO = potwierdzenie odbioru dokumentu → state='received'
			payload_for_mark = {
				'upo_reference': data.get('upo_reference'),
				'numer_ksef': data.get('numer_ksef_dokumentu'),
				'attachment_id': data.get('attachment_id'),
				'content_size': data.get('content_size'),
			}
			
			self.mark_received(payload=json.dumps(payload_for_mark, indent=2))
			
			# 5. Upewnij się że state='received'
			if self.state != 'received':
				self.write({'state': 'received'})
				_logger.info(f"[KSeF] State set to: received")
			
			_logger.info(f"[KSeF] download_upo completed successfully, next: close_session")

		# =====================================================================
		# CLOSE SESSION
		# =====================================================================
		elif self.ksef_operation == 'close_session':
			"""
			Obsługa sukcesu zamknięcia sesji.
			"""
			_logger.info(f"[KSeF] Handling close_session success")
			
			# 1. PRZYGOTUJ WARTOŚCI
			update_vals = {
				'ksef_history': self._add_to_history('success', result),
				'ksef_retry_count': 0,
				'ksef_last_execution': fields.Datetime.now(),
				'ksef_status': 'pending',
				'provider_message': f"Sesja zamknięta: {self.ksef_reference_number}",
			}
			
			# 2. ✅ UŻYJ ksef_next_operation ZAMIAST WŁASNEJ LOGIKI!
			# self.ksef_next_operation powinno być już ustawione na 'check_status' przez _determine_next_ksef_operations
			next_op = self.ksef_next_operation
			
			if not next_op or next_op == 'none':
				# Jeśli nie ma następnej operacji, sprawdź konfigurację
				will_check_status = False
				if self.provider_id and hasattr(self.provider_id, '_get_ksef_config'):
					ksef_config = self.provider_id._get_ksef_config()
					will_check_status = ksef_config and ksef_config.auto_check_status
				
				next_op = 'check_status' if will_check_status else 'completed'
			
			# Określ operację po następnej
			if next_op == 'check_status':
				after_next = 'download_upo'
				next_execution = fields.Datetime.now() + timedelta(minutes=2)
			elif next_op == 'completed':
				after_next = 'none'
				next_execution = False
			else:
				after_next = 'none'
				next_execution = fields.Datetime.now()
			
			update_vals.update({
				'ksef_operation': next_op,
				'ksef_next_operation': after_next,
				'ksef_next_execution': next_execution,
			})
			
			# 3. ZAPISZ NOWE TOKENY JEŚLI ZWRÓCONE
			if result.get('tokens'):
				_logger.info(f"[KSeF] New tokens received from close_session")
				current_ctx = json.loads(self.payload_context) if self.payload_context else {}
				current_ctx['tokens'] = result['tokens']
				update_vals['payload_context'] = json.dumps(current_ctx, ensure_ascii=False)
			
			# 4. ZAPISZ
			self.write(update_vals)
			
			# 5. ✅ KLUCZOWE: Jeśli NIE idziemy do check_status, to oznacz jako received
			if next_op == 'completed':
				self.mark_received(payload=json.dumps(result, indent=2))
				if self.state != 'received':
					self.write({'state': 'received'})
			
			_logger.info(f"[KSeF] close_session completed successfully, next: {next_op}")


		# =====================================================================
		# IMPORT FAKTURY
		# =====================================================================
		elif self.ksef_operation == 'import_invoice':
			"""
			Obsługa pobrania pojedynczej faktury.
			"""
			data = result.get('data', {})
			context = result.get('context', {})

			ksef_number = data.get('ksefNumber')
			invoice_xml_base64 = data.get('invoiceXmlBase64')
			
			if not invoice_xml_base64:
				update_vals = {
					'state': 'error',
					'ksef_status': 'failed',
					'ksef_operation': 'failed',
					'provider_message': f"No XML returned for {ksef_number}",
				}
				self.write(update_vals)
				self.mark_error(f"Failed to download invoice {ksef_number}")
				return
			
			# Sukces: pobrano fakturę - ZAPISZ DO file_data
			# Zamiast od razu tworzyć account.move, zapisz XML do file_data
			update_vals = {
				# ✅ KLUCZOWE: Zapisz pobrany XML do file_data
				'file_data': invoice_xml_base64,
				'file_name': f"KSeF_{ksef_number}.xml",
				
				# ✅ State = 'queued' (kolejka do dalszego przetwarzania)
				'state': 'queued',
				'ksef_status': 'pending',
				
				# ✅ Pola KSeF
				'ksef_history': self._add_to_history('success', result),
				'ksef_retry_count': 0,
				'ksef_last_execution': fields.Datetime.now(),
				'ksef_operation': 'restore_invoice',  # lub 'ready_for_import' jeśli chcesz osobny krok
				'ksef_next_operation': 'none',
				'ksef_next_execution': fields.Datetime.now(),  # ← Natychmiast!
				
				'provider_message': f"Invoice {ksef_number} downloaded, ready for import",
			}
			
			# ✅ Zapisz tokeny jeśli odświeżone
			if context.get('tokens'):
				current_ctx = json.loads(self.payload_context) if self.payload_context else {}
				current_ctx['tokens'] = context['tokens']
				update_vals['payload_context'] = json.dumps(current_ctx, ensure_ascii=False)
			
			# ✅ ZAPISZ
			self.write(update_vals)
			
			# ✅ Wywołaj mark_received() aby ustawić standardowe pola core
			self.mark_received(payload=json.dumps({
				'ksef_number': ksef_number,
				'file_size': data.get('invoiceSize', 0),
				'status': data.get('status', 'UNKNOWN'),
			}, indent=2))
			
			# ✅ Ale ZACHOWAJ state='queued' (nie zmieniaj na 'received')
			# mark_received() może próbować ustawić state='received'
			# Jeśli tak się dzieje, po wywołaniu mark_received() przywróć 'queued':
			if self.state != 'queued':
				self.write({'state': 'queued'})
			
			_logger.info(f"[KSeF] Invoice {ksef_number} downloaded successfully, saved to file_data")


		# =====================================================================
		# RESTORE INVOICE
		# =====================================================================
		elif self.ksef_operation == 'restore_invoice':
			move_id = result['data'].get('move_id')
			if not move_id and self.document_id:
				move_id = self.document_id
			
			update_vals = {
				'ksef_history': self._add_to_history('success', result),
				'ksef_retry_count': 0,
				'ksef_last_execution': fields.Datetime.now(),
				'ksef_status': 'success',
				'ksef_operation': 'completed',  # Kończymy flow
				'ksef_next_operation': 'none',
				'document_id': move_id,
				'document_model': 'account.move',
			}
			
			self.write(update_vals)
			self.mark_received(payload=json.dumps(result['data']))


		# =====================================================================
		# IMPORT LISTY FAKTUR i FAKTUR
		# =====================================================================
		elif self.ksef_operation in ['import_list', 'import_invoices']:
			_logger.info(f"[KSeF] Handling {self.ksef_operation} success")
			
			data = result.get('data', {})
			context = result.get('context', {})
			
			# 1. Zapisz tokeny jeśli odświeżone
			if context.get('tokens'):
				current_ctx = json.loads(self.payload_context) if self.payload_context else {}
				current_ctx['tokens'] = context['tokens']
				self.payload_context = json.dumps(current_ctx, ensure_ascii=False)
			
			# 2. SPECYFICZNA OBSŁUGA DLA KAŻDEJ OPERACJI
			
			# a) import_list - utwórz rekordy import_invoice dla każdej faktury
			if self.ksef_operation == 'import_list':
				invoices = data.get('invoices', [])
				invoice_count = data.get('invoiceCount', 0)
				created_child_ids = []
				_logger.info(f"[KSeF] Found {invoice_count} invoices, creating child records")
				
				# Dla każdej faktury utwórz rekord import_invoice
				for invoice in invoices:
					ksef_number = invoice.get('ksefNumber')
					if ksef_number:
						# 1. SPRAWDŹ czy faktura już istnieje w systemie
						existing_move = self.env['account.move'].search([
							('ksef_number', '=', ksef_number),
							('move_type', '=', 'in_invoice'),
						], limit=1)
						
						if existing_move:
							_logger.info(f"📢 [KSeF] Invoice {ksef_number} already exists as account.move {existing_move.id}, skipping")
							continue  # POMIŃ - już mamy tę fakturę
						
						# 2. Sprawdź czy nie ma już child logu dla tej faktury
						existing_child_log = self.env['communication.log'].search([
							('ksef_invoice_number', '=', ksef_number),
							('direction', '=', 'import'),
						], limit=1)
						
						if existing_child_log:
							_logger.info(f"📢 [KSeF] Child log already exists for {ksef_number}, skipping")
							continue  # POMIŃ - już mamy child log

						_logger.info(
							f"\n🚨 ksef_number {ksef_number} existing_move {existing_move} existing_child_log {existing_child_log}"
						)

						
						# 3. TYLKO jeśli nie ma ani account.move ani child logu → utwórz child
						child_log = self.env['communication.log'].create({
							'provider_id': self.provider_id.id,
							'direction': 'import',
							'document_model': 'account.move',  # Będzie utworzony później
							'document_id': False,  # Na razie brak - utworzymy po pobraniu XML
							# ✅ DEFAULT STATE
							'state': 'draft',  # w przygotowaniu

							# ✅ SEKWENCJA: auth → import_invoice → completed
							'ksef_operation': 'auth',				# <-- ZACZYNA OD AUTH
							'ksef_next_operation': 'import_invoice', # <-- POTEM IMPORT_INVOICE

							# ✅ KLUCZOWE: Numer faktury KSeF
							'ksef_invoice_number': ksef_number,  # <-- KLUCZOWE!
							'ksef_reference_number': ksef_number,

							'ksef_status': 'pending',
							'ksef_next_execution': fields.Datetime.now(),
							'parent_id': self.id,
							'ksef_import_days_back': self.ksef_import_days_back,
							#'ksef_download_dir': self.ksef_download_dir,
							'provider_message': f"Import invoice {invoice.get('invoiceNumber', '')} (KSeF: {ksef_number})",
							'company_id': self.company_id.id,
						})
						created_child_ids.append(child_log.id)
						_logger.info(f"[KSeF] Created child log {child_log.id} for KSeF {ksef_number}")

				# ============================================
				# 2. LOGIKA DLA PUSTEJ LISTY CHILD RECORDS
				# ============================================
				if not created_child_ids:
					# NIE utworzono żadnych child records
					_logger.info(f"[KSeF] No new invoices to import (all {invoice_count} already exist)")
					
					update_vals = {
						'ksef_history': self._add_to_history('success', result),
						'ksef_retry_count': 0,
						'ksef_last_execution': fields.Datetime.now(),
						'state': 'received',  # <-- Otrzymaliśmy listę (pustą)
						
						# ✅ 'completed' a nie 'failed' - to jest sukces, nie błąd
						'ksef_status': 'success',
						'ksef_operation': 'completed',
						'ksef_next_operation': 'none',
						'ksef_next_execution': False,
						
						'provider_message': f"No new invoices to import (all {invoice_count} already exist in system)",
					}
				else:
					# Utworzono child records
					_logger.info(f"[KSeF] Created {len(created_child_ids)} child import records")
					
					update_vals = {
						'ksef_history': self._add_to_history('success', result),
						'ksef_retry_count': 0,
						'ksef_last_execution': fields.Datetime.now(),
						'state': 'received',  # <-- Otrzymaliśmy listę (z child records)
						
						# Parent kończy pracę, child będą przetwarzane osobno
						'ksef_status': 'success',
						'ksef_operation': 'completed',
						'ksef_next_operation': 'none',
						'ksef_next_execution': False,
						
						'provider_message': f"Import list completed, created {len(created_child_ids)} child import records",
					}
			
				# ============================================
				# 3. ZAPISZ TOKENY I COMMIT
				# ============================================
				if context.get('tokens'):
					current_ctx = json.loads(self.payload_context) if self.payload_context else {}
					current_ctx['tokens'] = context['tokens']
					update_vals['payload_context'] = json.dumps(current_ctx, ensure_ascii=False)
				
				self.write(update_vals)
				self.env.cr.commit()
				
				_logger.info(f"[KSeF] import_list {'completed with no new invoices' if not created_child_ids else f'created {len(created_child_ids)} child records'}")
				# Zakończ import_list
				return  # ⚠️ KLUCZOWE: ZAKOŃCZ METODĘ! ⚠️
			
			# c) import_invoices - combo (lista + ewentualne pobieranie)
			elif self.ksef_operation == 'import_invoices':
				invoice_count = data.get('invoiceCount', 0)
				download_count = data.get('downloadCount', 0)
				
				if data.get('download_all') and download_count > 0:
					# Pobrano wszystkie faktury
					update_vals = {
						'ksef_history': self._add_to_history('success', result),
						'ksef_retry_count': 0,
						'ksef_last_execution': fields.Datetime.now(),
						'ksef_status': 'success',
						'ksef_operation': 'completed',
						'ksef_next_operation': 'none',
						'provider_message': f"Downloaded {download_count} invoices",
					}
					self.mark_received(payload=json.dumps(result, indent=2))
				else:
					# Tylko lista - utwórz child records jak dla import_list
					invoices = data.get('invoices', [])
					for invoice in invoices:
						ksef_number = invoice.get('ksefNumber')
						if ksef_number:
							self.env['communication.log'].create({
								'provider_id': self.provider_id.id,
								'direction': 'import',
								'document_model': 'account.move',
								'ksef_operation': 'import_invoice',
								'ksef_invoice_number': ksef_number,
								'ksef_status': 'pending',
								'ksef_next_execution': fields.Datetime.now(),
								'parent_id': self.id,
								'company_id': self.company_id.id,
							})
					
					update_vals = {
						'ksef_history': self._add_to_history('success', result),
						'ksef_retry_count': 0,
						'ksef_last_execution': fields.Datetime.now(),
						'ksef_status': 'success',
						'ksef_operation': 'completed',
						'ksef_next_operation': 'none',
						'provider_message': f"List imported: {invoice_count} invoices",
					}
			
			self.write(update_vals)


		# =====================================================================
		# COMPLETED
		# =====================================================================
		elif from_ksef_operation == 'completed':
			pass


		# =======================================================		
		# 3. Ustal następną operację
		# =======================================================
		if from_ksef_operation not in ['close_session', 'check_status', 'download_upo', 'import_invoice', 'import_invoices', 'import_list']:
			# Tylko dla operacji które NIE mają własnej obsługi
			next_ops = self._determine_next_ksef_operations(result)
			update_vals.update({
				'ksef_operation': next_ops['current'],
				'ksef_next_operation': next_ops['next'],
				'ksef_next_execution': next_ops['next_execution'],
			})
		# =======================================================
		# 4. Zaktualizuj workflow communication.log
		# =======================================================
		if self.ksef_operation == 'send_invoice':
			self.mark_sent(external_id=operation_data.get('referenceNumber'))
		elif self.ksef_operation == 'check_status':
			self.mark_status_checked(payload=json.dumps(result, indent=2))
		
		# 5. Zapisz wszystko
		self.write(update_vals)
		
		# Log dla debugowania
		_logger.info(
			f"[KSeF] Operation {self.ksef_operation} completed successfully, "
			f"next: {next_ops['current']}"
		)

	def _handle_ksef_error(self, error_msg):
		"""
		Obsługuje błąd operacji KSeF z WSZYSTKIMI polami.
		"""
		# 1. Zwiększ licznik prób
		self.ksef_retry_count += 1

		# 2. Dla check_status - większy limit prób
		max_retries = self.ksef_max_retries
		if self.ksef_operation == 'check_status':
			max_retries = 20  # Więcej prób dla check_status (może długo czekać na UPO)
		
		# 3. Dodaj do historii
		history_entry = {
			'operation': self.ksef_operation,
			'status': 'failed',
			'timestamp': datetime.now().isoformat(),
			'error': str(error_msg)[:500],
			'retry_count': self.ksef_retry_count,
		}
		
		current_history = self.ksef_history or []
		current_history.append(history_entry)
		
		# 4. Przygotuj wartości update
		update_vals = {
			'ksef_history': current_history,
			'ksef_last_execution': fields.Datetime.now(),
		}
		
		# 5. Sprawdź czy przekroczono max prób
		if self.ksef_retry_count >= self.ksef_max_retries:
			# FAIL - koniec sekwencji
			update_vals.update({
				'ksef_status': 'failed',
				'ksef_operation': 'failed',
				'ksef_next_operation': 'none',
				'ksef_next_execution': False,
				'state': 'error',
				'status': 'error',
				'provider_message': f"Max retries ({self.ksef_max_retries}) exceeded: {error_msg}",
			})
			
			# Wywołaj standardowy error handler
			self.mark_error(f"KSeF failed after {self.ksef_max_retries} retries: {error_msg}")
			
		else:
			# RETRY - zaplanuj ponowną próbę
			retry_delay = self._calculate_retry_delay()
			next_execution = fields.Datetime.now() + timedelta(minutes=retry_delay)
			
			update_vals.update({
				'ksef_status': 'pending',
				'ksef_next_execution': next_execution,
				'provider_message': f"Retry {self.ksef_retry_count}/{self.ksef_max_retries} in {retry_delay}min: {error_msg}",
			})
		
		# 6. Zapisz
		self.write(update_vals)

	
	def _determine_next_operation(self, result):
		"""
		Określa następną operację na podstawie wyniku.
		"""
		# Domyślna sekwencja dla export
		if self.direction == 'export':
			sequence = ['auth', 'open_session', 'send_invoice', 'close_session']
			
			# Jeśli włączone auto-check status
			provider = self.provider_id
			if provider and hasattr(provider, '_get_ksef_config'):
				ksef_config = provider._get_ksef_config()
				if ksef_config and ksef_config.auto_check_status:
					# Wstaw check_status i download_upo po send_invoice
					sequence = ['auth', 'open_session', 'send_invoice', 
							   'check_status', 'download_upo', 'close_session']
		
		elif self.direction == 'import':
			sequence = ['auth', 'import_invoices']
		else:
			sequence = []
		
		# Znajdź bieżącą operację w sekwencji
		try:
			current_idx = sequence.index(self.ksef_operation)
			if current_idx + 1 < len(sequence):
				next_op = sequence[current_idx + 1]
			else:
				next_op = 'completed'
		except ValueError:
			next_op = 'failed'
		
		# Określ czas następnego wykonania
		next_execution = fields.Datetime.now()
		
		# Opóźnienia specyficzne dla operacji
		delays = {
			'check_status': 5,	# 5 minut po wysłaniu
			'download_upo': 2,	# 2 minuty po status
			'close_session': 1,   # 1 minuta po UPO
		}
		
		if next_op in delays:
			next_execution = fields.Datetime.now() + timedelta(minutes=delays[next_op])
		
		return {
			'current': next_op,
			'next': self._get_next_after(next_op),
			'next_execution': next_execution,
		}
	
	def _get_next_after(self, operation):
		"""
		Zwraca operację po podanej operacji.
		"""
		if operation in ['completed', 'failed']:
			return 'none'
		
		# Uproszczona logika - można rozbudować
		next_mapping = {
			'auth': 'open_session',
			'open_session': 'send_invoice',
			'send_invoice': 'check_status',
			'check_status': 'download_upo',
			'download_upo': 'close_session',
			'close_session': 'completed',
			'import_invoices': 'completed',
		}
		
		return next_mapping.get(operation, 'none')
	
	def _get_retry_delay(self):
		"""
		Oblicza opóźnienie przed ponowną próbą (exponential backoff).
		"""
		# 1, 2, 4, 8, 16, 32, 64 minut...
		return min(2 ** (self.ksef_retry_count - 1), 64)


	# ====================================================================================
	# Cron główny dla importu listy
	# ====================================================================================
	@api.model
	def _cron_ksef_schedule_import_list(self):
		"""
		Cron uruchamiany co godzinę, który sprawdza czy trzeba stworzyć 
		zadanie importu listy faktur dla providerów KSeF.
		
		Działa na zasadzie:
		1. Sprawdza wszystkich aktywnych providerów KSeF
		2. Dla każdego sprawdza czy minął czas na kolejny import
		3. Jeśli tak, tworzy rekord communication.log z ksef_operation='import_list'
		4. Główny cron (_cron_process_ksef_queue) przetworzy ten rekord
		"""
		_logger.info("[KSeF Import Cron] Starting import list scheduler")
		
		# 1. Znajdź aktywnych providerów KSeF
		ksef_providers = self.env['communication.provider'].search([
			('provider_type', '=', 'ksef'),
			('active', '=', True),
		])
		
		created_count = 0
		skipped_count = 0
		
		for provider in ksef_providers:
			try:
				# 2. Pobierz konfigurację KSeF dla tego providera
				ksef_config = provider._get_ksef_config()
				if not ksef_config:
					_logger.warning(f"[KSeF Import] No KSeF config for provider {provider.id}")
					skipped_count += 1
					continue
				
				# 3. Sprawdź czy import jest włączony
				if not getattr(ksef_config, 'import_enabled', True):
					_logger.debug(f"[KSeF Import] Import disabled for provider {provider.id}")
					skipped_count += 1
					continue
				
				# 4. Sprawdź czy już czas na następny import
				should_create, reason = self._should_create_import_list_job(ksef_config, provider)
				
				if not should_create:
					_logger.debug(f"[KSeF Import] Skipping provider {provider.id}: {reason}")
					skipped_count += 1
					continue
				
				# 5. Utwórz rekord import_list
				list_record = self._create_import_list_record(ksef_config, provider)
				
				if list_record:
					created_count += 1
					_logger.info(f"[KSeF Import] Created import list job {list_record.id} for provider {provider.id}")
					
					# 6. Natychmiast zaplanuj przetworzenie (opcjonalnie)
					# list_record.ksef_next_execution = fields.Datetime.now()
					# Możesz od razu wywołać _process_single_ksef_step() lub poczekać na główny cron
					
			except Exception as e:
				_logger.error(f"[KSeF Import] Error processing provider {provider.id}: {e}")
				continue
		
		_logger.info(f"[KSeF Import Cron] Finished. Created: {created_count}, Skipped: {skipped_count}")
		return {
			'created': created_count,
			'skipped': skipped_count,
		}


	# pomocniczo 
	def _get_provider_tokens(self, provider):
		"""
		Pobiera cache'owane tokeny z providera.
		"""
		ksef_config = provider._get_ksef_config()
		if not ksef_config:
			return None
		
		# Jeśli provider ma pole last_tokens
		if hasattr(ksef_config, 'last_tokens') and ksef_config.last_tokens:
			return ksef_config.last_tokens
		
		# Albo szukaj ostatniego udanego auth w logach
		last_auth_log = self.env['communication.log'].search([
			('company_id', '=', provider.company_id.id),
			('provider_id', '=', provider.id),
			('ksef_operation', '=', 'auth'),
			('status', '=', 'success'),
			('payload_context', '!=', False),
		], order='create_date desc', limit=1)
		
		if last_auth_log and last_auth_log.payload_context:
			try:
				context = json.loads(last_auth_log.payload_context)
				return context.get('tokens')
			except:
				pass
		
		return None

	def _are_tokens_valid(self, tokens):
		"""
		Sprawdza czy tokeny są ważne.
		"""
		if not tokens:
			return False
		
		access_expiry = tokens.get('accessTokenValidUntil')
		if not access_expiry:
			return False
		
		try:
			expiry = datetime.fromisoformat(access_expiry.replace('Z', '+00:00'))
			now = datetime.utcnow()
			# 5-minutowy bufor bezpieczeństwa
			return now < (expiry - timedelta(minutes=5))
		except:
			return False

	def _should_create_import_list_job(self, ksef_config, provider):
		"""
		Decyduje czy utworzyć zadanie importu listy dla danego providera.
		
		Returns: (should_create: bool, reason: str)
		"""
		# 1. Sprawdź czy nie ma już aktywnego zadania import_list
		recent_hours = 1  # Szukaj zadań z ostatniej godziny
		cutoff_time = fields.Datetime.now() - timedelta(hours=recent_hours)
		
		existing_jobs = self.env['communication.log'].search([
			('provider_id', '=', provider.id),
			('ksef_operation', '=', 'import_list'),
			('state', 'not in', ['completed', 'failed', 'error']),
			('create_date', '>=', cutoff_time),
			('company_id', '=', provider.company_id.id)
		], limit=1)
		
		if existing_jobs:
			return False, f"Already has active import_list job {existing_jobs[0].id}"
		
		# 2. Sprawdź częstotliwość
		last_success = getattr(ksef_config, 'import_last_success_date', None)
		frequency_hours = getattr(ksef_config, 'import_frequency_hours', 12)
		
		if not last_success:
			# Nigdy nie było importu - utwórz zadanie
			return True, "First import ever"
		
		# Oblicz ile godzin minęło od ostatniego importu
		hours_passed = (fields.Datetime.now() - last_success).total_seconds() / 3600
		
		if hours_passed >= frequency_hours:
			return True, f"Frequency reached ({hours_passed:.1f}h >= {frequency_hours}h)"
		else:
			return False, f"Frequency not reached yet ({hours_passed:.1f}h < {frequency_hours}h)"

	def _create_import_list_record(self, ksef_config, provider):
		"""
		Tworzy rekord communication.log dla importu listy faktur.
		"""
		try:
			# 1. Oblicz zakres dat
			date_from, date_to = self._calculate_import_date_range(ksef_config)
			
			# 2. Przygotuj parametry importu
			import_params = {
				'date_from': date_from.isoformat(),
				'date_to': date_to.isoformat(),
				'subject_type': getattr(ksef_config, 'import_subject_type', 'SUBJECT2'),
				'date_type': 'INVOICING',  # Data wystawienia faktury
				'page_size': getattr(ksef_config, 'import_page_size', 100),
				'max_pages': getattr(ksef_config, 'import_max_pages', 10),
				'max_invoices': 1000,  # Bezpieczny limit
			}
			
			# 3. Utwórz unikalny external_id
			timestamp = fields.Datetime.now().strftime('%Y%m%d_%H%M')
			external_id = f"IMPORT_LIST_{provider.code or provider.id}_{timestamp}"
			
			# 4. Utwórz rekord
			values = {
				'document_model': 'communication.provider',
				'document_id': provider.id,
				'external_id': external_id,
				'message': f"Automatic import list: {date_from} to {date_to}",
				'direction': 'import',
				'operation': 'fetch',
				'status': 'success',  # Na początek sukces, zmieni się jeśli błąd
				'state': 'draft',
				'provider_id': provider.id,
				'provider_type': 'ksef',
				
				# Pola KSeF
				'ksef_import_params': import_params,
				'ksef_status': 'pending',
				'ksef_next_execution': fields.Datetime.now(),
				
				# Statystyki (początkowe)
				'ksef_discovered_count': 0,
				'ksef_created_jobs': 0,
				
				# Wykonane przez system
				'executed_by': self.env.ref('base.user_root').id,
				'company_id': provider.company_id.id,
			}
			provider_tokens = self._get_provider_tokens(provider)
			if provider_tokens and self._are_tokens_valid(provider_tokens):
				values.update( {'ksef_operation': 'import_list', 'ksef_next_operation': 'completed', 'payload_context': json.dumps({'tokens': provider_tokens}), })
			else:
				values.update( {'ksef_operation': 'auth', 'ksef_next_operation': 'import_list', })
	
			list_record = self.env['communication.log'].create( values)
			
			# 5. Zapisz informację o utworzonym zadaniu w konfiguracji (opcjonalnie)
			# ksef_config.write({
			#	 'import_last_scheduled_date': fields.Datetime.now(),
			# })
			
			return list_record
			
		except Exception as e:
			_logger.error(f"[KSeF Import] Error creating import list record: {e}")
			return None

	def _calculate_import_date_range(self, ksef_config):
		"""
		Oblicza zakres dat dla importu listy.
		Strategia:
		1. Jeśli nie było wcześniejszego importu: ostatnie X dni
		2. Jeśli był: od ostatniego importu + 1 minuta do teraz
		3. Zawsze z buforem (import_days_back)
		"""
		now = fields.Datetime.now()
		default_days = 30
		last_success = getattr(ksef_config, 'import_last_success_date', None)
		days_back = getattr(ksef_config, 'import_days_back', default_days)
		
		# Data końcowa = teraz
		date_to = now
		
		if last_success:
			# Od ostatniego udanego importu + 1 minuta (żeby uniknąć duplikatów)
			date_from = last_success + timedelta(minutes=1)
			
			# Ale nie wcześniej niż X dni wstecz (bufor bezpieczeństwa)
			min_date = now - timedelta(days=days_back)
			date_from = max(date_from, min_date)
			
			_logger.info(f"[KSeF Import] Using incremental range: {date_from} to {date_to}")
		else:
			# Pierwszy import - pobierz z buforem dni
			date_from = now - timedelta(days=days_back)
			_logger.info(f"[KSeF Import] First import, using buffer {days_back} days: {date_from} to {date_to}")
		
		# Sprawdź czy zakres nie jest zbyt mały (mniej niż 1 minuta)
		if (date_to - date_from).total_seconds() < 60:
			date_from = date_to - timedelta(minutes=5)
			_logger.warning(f"[KSeF Import] Date range too small, extended to 5 minutes")
		
		return date_from, date_to




	# ====================================================================================

# =============================================================================
# Klasa główna CommunicationProviderKsef z konfiguracją ścieżki JAR
# =============================================================================
class CommunicationProviderKsef(models.Model):
	_name = "communication.provider.ksef"
	_inherit = ["mail.thread", "mail.activity.mixin"]
	_description = "Provider KSeF FA(3) z JET API i obsługą Java JAR"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	# ROZSZERZENIE SPOZA DOKUMENTACJI FSEF (fragment - do uzupełnienia)
	#  Użycie:
	#   uom_type = self.UN_CEFACT_UOM.get(raw.ksef_p_8a, "quantity")
	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

	UN_CEFACT_UOM = {
		"C62": "quantity",
		"HUR": "quantity",
		"DAY": "quantity",
		"KGM": "quantity",
		"LTR": "quantity",
		"P1":  "percent",
	}

	# -------------------------------------------------------------------------
	# Konfiguracja powiadomie
	# -------------------------------------------------------------------------

	alert_contact_id = fields.Many2one(
		"res.partner",
		string="Kontakt alarmowy",
		help="Osoba odpowiedzialna za monitoring komunikacji KSeF"
	)

	alert_email = fields.Char(
		related="alert_contact_id.email",
		store=False
	)

	alert_phone = fields.Char(
		related="alert_contact_id.mobile",
		store=False
	)

	# -------------------------------------------------------------------------
	# POLA KONFIGURACYJNE
	# -------------------------------------------------------------------------

	api_backend = fields.Selection(
		[
			('java', 'Java Client'),
			('python', 'Python HTTP Client'),
		],
		string="KSeF API Backend",
		default='java',
		required=True,
	)

	api_mode = fields.Selection(
		[
			('java_only', 'Java Only'),
			('hybrid', 'Hybrid (Java + Python)'),
			('python_only', 'Python Only'),
		],
		default='java_only',
	)

	name = fields.Char(string="Nazwa konfiguracji", required=True)
	code = fields.Char(string="Kod", required=True)
	active = fields.Boolean(string="Aktywny", default=True)
	description = fields.Text(string="Opis")
	company_id = fields.Many2one(
		'res.company',
		string="Firma",
		required=True,
		default=lambda self: self.env.company
	)

	import_template_id = fields.Many2one(
		'xml.export.template', 
		string="Szablon importu faktur",
		required=True,
	)

	qr_report_template_id = fields.Many2one(
		"ir.ui.view",
		string="Szablon wydruku faktury (QR)",
		domain="[('type','=','qweb')]",
		help=(
			"Szablon QWeb faktury, do którego zostanie "
			"doklejona sekcja QR KSeF."
		)
	)

	# NEW FIELD FOR MIGRATION CONTROL
	use_python_http = fields.Boolean(
		string="Użyj Python",
		default=True,
		help="""Użyj implementacji Python HTTP zamiast Java JAR dla operacji HTTP.
		Java JAR nadal używany dla autoryzacji (XAdES signing).
		"""
	)
	
	# NEW FIELD FOR GRADUAL ROLLOUT
	python_operations = fields.Selection([
		('none', 'Tylko Java'),
		('open_close', 'Open/Close Session'),
		('status_upo', 'Status + UPO'),
		('send_invoice', 'Wysyłanie faktur'),
		('all', 'Wszystkie operacje HTTP'),
	],
		string="Operacje w Python",
		default='all',
		help="Przełączanie operacji Python / Java"
	)

	# -------------------------------------------------------------------------
	# KONFIGURACJA IMPORTU FAKTUR (BAZOWE POLA)
	# -------------------------------------------------------------------------
	import_enabled = fields.Boolean(
		string="Import faktur włączony",
		default=True,
		help="Czy automatycznie importować faktury odebrane z KSeF?"
	)

	import_frequency_hours = fields.Integer(
		string="Częstotliwość importu (godziny)",
		default=12,
		help="Co ile godzin uruchamiać import listy faktur"
	)

	import_last_success_date = fields.Datetime(
		string="Data ostatniego udanego importu",
		help="Data i czas ostatniego pobrania listy faktur"
	)

	import_days_back = fields.Integer(
		string="Dni wstecz (bufor)",
		default=2,
		help="Dla bezpieczeństwa - zawsze pobieraj X dni wstecz"
	)

	import_subject_type = fields.Selection([
		('SUBJECT1', 'Faktury wystawione'),
		('SUBJECT2', 'Faktury odebrane'),
	], 
		string="Typ faktur do importu",
		default='SUBJECT2',
		help="SUBJECT2 = faktury które do nas przyszły (odebrane)"
	)

	import_page_size = fields.Integer(
		string="Rozmiar strony API",
		default=100,
		help="Ilość faktur na stronie (max 100 dla KSeF)"
	)

	import_max_pages = fields.Integer(
		string="Maksymalna ilość stron",
		default=10,
		help="Bezpieczny limit - maksymalnie 10 stron × 100 = 1000 faktur"
	)

	# Pole pomocnicze do obliczeń
	import_next_schedule = fields.Datetime(
		string="Następny zaplanowany import",
		compute='_compute_import_next_schedule',
		store=True
	)

	@api.depends('import_last_success_date', 'import_frequency_hours')
	def _compute_import_next_schedule(self):
		"""Oblicza kiedy powinien być następny import"""
		for record in self:
			if not record.import_last_success_date:
				record.import_next_schedule = fields.Datetime.now()
			else:
				last = record.import_last_success_date
				frequency = record.import_frequency_hours or 12
				record.import_next_schedule = last + timedelta(hours=frequency)

	
	# -------------------------------------------------------------------------
	# KONFIGURACJA ŚCIEŻKI JAR (NOWE POLE)
	# -------------------------------------------------------------------------
	jar_directory = fields.Char(
		string="Ścieżka do plików JAR",
		default="/opt/ksef/client/",
		required=True,
		help="Ścieżka do katalogu z plikami .jar (ksef-auth.jar, ksef-send-invoice.jar, etc.)"
	)
	
	# Walidacja ścieżki JAR
	@api.constrains('jar_directory')
	def _check_jar_directory(self):
		for record in self:
			if not record.jar_directory:
				raise ValidationError("Ścieżka do plików JAR jest wymagana")
			
			# Sprawdź czy katalog istnieje (tylko ostrzeżenie)
			if not os.path.isdir(record.jar_directory):
				_logger.warning(f"JAR directory does not exist: {record.jar_directory}")
	
	# -------------------------------------------------------------------------
	# POZOSTAŁE POLA KONFIGURACYJNE (jak wcześniej)
	# -------------------------------------------------------------------------

	base_url = fields.Char(
		string="URL API KSeF",
		help="Pełny URL endpointu API KSeF (np. https://api-test.ksef.mf.gov.pl/api/v2)",
		default="https://api-test.ksef.mf.gov.pl/api/v2",
	)

	qr_code_url = fields.Char(
		string="URL dla QR",
		help="Adres URL zależny od środowiska",
		default="https://qr-test.ksef.mf.gov.pl"
	)
	
	environment = fields.Selection([
		('test', 'Środowisko testowe API v2'),
		('production', 'Środowisko produkcyjne API v2'),
	], string="Środowisko API", default='test', required=True)
	
	auth_type = fields.Selection([
		('jet_token', 'Token JET API'),
		('certificate', 'Certyfikat .p12/.pfx'),
	], string="Typ autoryzacji", default='jet_token', required=True)
	
	# Pola JET API
	jet_api_key = fields.Char(
		string="Klucz API JET",
		groups="base.group_system"
	)
	
	jet_api_token = fields.Char(
		string="Token API JET",
		groups="base.group_system"
	)
	
	# Pola certyfikatu
	auth_keystore_p12 = fields.Many2one(
		'ir.attachment',
		string="AUTH keystore (.p12)",
	)

	auth_keystore_password = fields.Char(
		groups="base.group_system",
	)

	sign_keystore_p12 = fields.Many2one(
		'ir.attachment',
		string="SIGN keystore (.p12)",
	)

	sign_keystore_password = fields.Char(
		groups="base.group_system",
	)
	
	company_nip = fields.Char(
		related="company_id.vat_clean",
		string="NIP Firmy",
		required="1",
		store=True
	)
	
	mf_certificate_pem = fields.Text(
		string="Klucz publiczny MF (PEM)",
		help="Publiczny klucz RSA Ministerstwa Finansów"
	)
	
	# Opcje
	validate_before_send = fields.Boolean(
		string="Waliduj przed wysłaniem",
		default=True,
	)
	
	auto_check_status = fields.Boolean(
		string="Automatycznie sprawdzaj status",
		default=True
	)
	
	status_check_delay = fields.Integer(
		string="Opóźnienie sprawdzania statusu (min)",
		default=5
	)
	
	debug_mode = fields.Boolean(
		string="Tryb debug",
		default=False,
	)

	# ============================================
	# METODY DO OBSŁUGI PYTHON REQUEST/RESPONSE
	# ============================================
	def _call_python_http(self, input_data, timeout=60):
		"""
		Python equivalent of _call_java_jar.
		Returns identical format to Java output.
		"""
		from ksef_python_client import KSeFPythonClient
		
		operation = input_data.get('operation')
		context = input_data.get('context', {})
		params = input_data.get('params', {})
		
		_logger.info(f"[Python HTTP] Starting operation: {operation}")
		
		try:
			# Initialize client
			client = KSeFPythonClient(
				environment=self.environment,
				session_token=context.get('sessionToken')
			)
			
			# Map operation to method
			if operation == 'open_session':
				# Get auth token from context (from previous auth operation)
				tokens = context.get('tokens', {})
				auth_token = tokens.get('accessToken')
				
				if not auth_token:
					raise ValueError("Missing auth token for open_session")
				
				result = client.open_session(auth_token)
				
				# Format identical to Java
				return {
					'success': True,
					'data': {
						'sessionToken': result.get('sessionToken'),
						'referenceNumber': result.get('referenceNumber'),
						'sessionId': result.get('sessionId'),
					},
					'context': {
						'session': result,
						'runtime': {
							'baseUrl': self._get_base_url(),
							'integrationMode': self.environment.upper(),
						}
					}
				}
			
			elif operation == 'send_invoice':
				invoice_xml = params.get('invoice_xml')
				if not invoice_xml:
					raise ValueError("Missing invoice XML")
				
				result = client.send_invoice(invoice_xml)
				
				return {
					'success': True,
					'data': {
						'referenceNumber': result.get('referenceNumber'),
						'invoiceNumber': result.get('invoiceNumber'),
						'processingCode': result.get('processingCode'),
						'processingDescription': result.get('processingDescription'),
					}
				}
			
			elif operation == 'check_status':
				# Get reference number from context or log
				reference_number = params.get('reference_number') or context.get('referenceNumber')
				if not reference_number:
					raise ValueError("Missing reference number for check_status")
				
				result = client.check_status(reference_number)
				
				return {
					'success': True,
					'data': {
						'processingStatus': result.get('processingStatus'),
						'processingCode': result.get('processingCode'),
						'processingDescription': result.get('processingDescription'),
						'referenceNumber': reference_number,
					}
				}
			
			elif operation == 'download_upo':
				reference_number = params.get('reference_number') or context.get('referenceNumber')
				if not reference_number:
					raise ValueError("Missing reference number for download_upo")
				
				result = client.download_upo(reference_number)
				
				return_data = {
					'referenceNumber': reference_number,
					'contentType': result.get('contentType'),
				}
				
				if 'json' in result:
					return_data['json'] = result['json']
				if 'content' in result:
					return_data['content'] = result['content']
					return_data['filename'] = result.get('filename')
				
				return {
					'success': True,
					'data': return_data
				}
			
			elif operation == 'close_session':
				result = client.close_session()
				
				return {
					'success': True,
					'data': result
				}
			
			else:
				raise ValueError(f"Unsupported Python operation: {operation}")
		
		except Exception as e:
			_logger.error(f"[Python HTTP] Operation failed: {operation} - {e}")
			
			# Format error identically to Java
			return {
				'success': False,
				'error': str(e),
				'operation': operation,
			}


	def _get_base_url(self):
		"""Helper method for base URL"""
		if self.environment == 'test':
			return 'https://x-api-test.ksef.mf.gov.pl/v2'
		return 'https://x-api-test.ksef.mf.gov.pl/v2'
	
	# -------------------------------------------------------------------------
	# METODY POMOCNICZE - JAVA
	# -------------------------------------------------------------------------
	
	def _get_jar_path(self, jar_filename):
		"""
		Zwraca pełną ścieżkę do pliku JAR.
		
		Args:
			jar_filename (str): Nazwa pliku .jar
			
		Returns:
			str: Pełna ścieżka lub None jeśli nie istnieje
		"""
		if not self.jar_directory:
			return None
		
		jar_path = os.path.join(self.jar_directory, jar_filename)
		
		# Sprawdź czy plik istnieje
		if os.path.isfile(jar_path):
			return jar_path
		
		# Próba z różnymi rozszerzeniami
		for ext in ['', '.jar', '.JAR']:
			test_path = os.path.join(self.jar_directory, f"{jar_filename}{ext}")
			if os.path.isfile(test_path):
				return test_path
		
		_logger.warning(f"JAR file not found: {jar_filename} in {self.jar_directory}")
		return None
	
	def _call_java_jar(self, jar_path, input_data, timeout=300):
		"""
		Wywołuje plik JAR z danymi JSON przez stdin.
		"""
		if not os.path.isfile(jar_path):
			return {
				'success': False,
				'error': f"JAR file does not exist: {jar_path}"
			}
		
		# DEBUG: Zapisz input do pliku
		debug_dir = "/tmp/odoo_ksef_debug"
		os.makedirs(debug_dir, exist_ok=True)
		debug_file = os.path.join(debug_dir, f"input_{int(time.time())}.json")
		
		try:
			json_input = json.dumps(input_data, ensure_ascii=False, indent=2)
			
			with open(debug_file, 'w', encoding='utf-8') as f:
				f.write(json_input)
			
			_logger.info(f"[Java] Input saved to: {debug_file}")
			_logger.info(f"[Java] Input size: {len(json_input)} chars")
			
			# DEBUG: Pokrótce input
			_logger.info(f"[Java] Input preview (first 500 chars): {json_input[:500]}")
			
		except Exception as e:
			_logger.error(f"[Java] Error saving debug file: {e}")
			json_input = json.dumps(input_data, ensure_ascii=False)
		
		start_time = time.time()
		
		try:
			# DEBUG: Log command
			_logger.info(f"[Java] Running: java -jar {jar_path}")

			java_args = [
				'java',
				'-Xmx2g',						# 2GB heap memory
				'-Xms512m',						# 512MB initial heap
				'-XX:MaxMetaspaceSize=512m',	# Limit metaspace
				'-XX:+UseSerialGC',				# ← SerialGC (prostszy, stabilniejszy)
				'-jar', jar_path,
			]

			# TYLKO dla JAR-ów które nie są send-invoice
			if 'send-invoice' not in jar_path:
				java_args.extend(['--json-input', '-out', 'stdout'])

			_logger.info(f"\n[Java] Running: java_args = {java_args}")
			
			# Wywołaj proces Java
			process = subprocess.Popen(
				java_args,
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
				encoding='utf-8',
				bufsize=-1,
			)
			
			# Wyślij dane i poczekaj na wynik z timeout
			stdout, stderr = process.communicate(
				input=json_input,
				timeout=timeout
			)
			
			duration_ms = int((time.time() - start_time) * 1000)
			
			# DEBUG: Zapisuj wszystko
			debug_output_file = debug_file.replace('input_', 'output_')
			with open(debug_output_file, 'w', encoding='utf-8') as f:
				f.write(f"=== STDOUT ({len(stdout)} chars) ===\n")
				f.write(stdout)
				f.write(f"\n\n=== STDERR ({len(stderr)} chars) ===\n")
				f.write(stderr)
				f.write(f"\n\n=== EXIT CODE: {process.returncode} ===\n")
			
			_logger.info(f"[Java] Output saved to: {debug_output_file}")
			_logger.info(f"[Java] Exit code: {process.returncode}")
			_logger.info(f"[Java] Stdout length: {len(stdout)} chars")
			_logger.info(f"[Java] Stderr length: {len(stderr)} chars")
			
			if stderr:
				_logger.error(f"[Java] Stderr content: {stderr[:1000]}")
			
			if stdout:
				_logger.info(f"[Java] Stdout preview: {stdout[:500]}")
			
			# Sprawdź kod wyjścia
			if process.returncode != 0:
				_logger.error(f"[Java] Process exited with code {process.returncode}")
				return {
					'success': False,
					'error': f"Java process error (exit {process.returncode}): {stderr[:500] if stderr else 'No error message'}",
					'stdout': stdout,
					'stderr': stderr,
					'duration_ms': duration_ms,
				}
			
			# Parsuj odpowiedź JSON
			try:
				result = json.loads(stdout)
				result['duration_ms'] = duration_ms
				result['success'] = result.get('success', True)
				_logger.info(f"[Java] Parsed result, success: {result.get('success')}")
				return result
				
			except json.JSONDecodeError as e:
				_logger.error(f"[Java] JSON parse error: {e}")
				_logger.error(f"[Java] Raw stdout: {stdout[:1000]}")
				return {
					'success': False,
					'error': f"Invalid JSON response from Java: {e}",
					'raw_output': stdout[:1000],
					'duration_ms': duration_ms,
				}
				
		except subprocess.TimeoutExpired:
			if process:
				process.kill()
				process.wait()
			
			_logger.error(f"[Java] Timeout after {timeout} seconds")
			return {
				'success': False,
				'error': f"Java process timeout after {timeout} seconds",
				'duration_ms': int((time.time() - start_time) * 1000),
			}
			
		except Exception as e:
			_logger.error(f"[Java] Unexpected error: {e}", exc_info=True)
			return {
				'success': False,
				'error': f"Java execution failed: {str(e)}",
				'duration_ms': int((time.time() - start_time) * 1000),
			}

	
	# -------------------------------------------------------------------------
	# METODY DLA COMMUNICATION.PROVIDER
	# -------------------------------------------------------------------------
	
	def _get_ksef_config(self):
		"""
		Zwraca obiekt konfiguracji KSeF dla providera.
		Używane przez communication.log do pobrania konfiguracji.
		"""
		# To jest sam obiekt konfiguracji
		return self
	
	def _find_provider(self):
		"""
		Znajduje lub tworzy communication.provider powiązany z tą konfiguracją.
		"""
		provider = self.env['communication.provider'].search([
			('company_id', '=', self.company_id.id),
			('provider_type', '=', 'ksef'),
			('provider_config_id', '=', self.id),
			('provider_model', '=', 'communication.provider.ksef')
		], limit=1)
		
		if not provider:
			# Utwórz nowy provider
			provider = self.env['communication.provider'].create({
				'name': f"KSeF Provider: {self.name}",
				'code': f"KSEF_{self.code}",
				'provider_type': 'ksef',
				'provider_config_id': self.id,
				'provider_model': 'communication.provider.ksef',
				'active': self.active,
				'company_id': self.company_id.id,
			})
		
		return provider
	
	# -------------------------------------------------------------------------
	# COMPUTE METHODS
	# -------------------------------------------------------------------------
	
	@api.depends_context('company')
	def _compute_company_nip(self):
		"""Pobiera NIP firmy z konfiguracji Odoo"""
		for record in self:
			company = self.env.company
			if hasattr(company, 'vat_clean') and company.vat_clean:
				record.company_nip = company.vat_clean
			elif company.vat:
				# Czyszczenie NIP
				nip = company.vat.replace('PL', '').replace('-', '').strip()
				if len(nip) == 10 and nip.isdigit():
					record.company_nip = nip
				else:
					record.company_nip = False
			else:
				record.company_nip = False
	
	@api.depends('name', 'code', 'environment', 'auth_type')
	def _compute_display_name(self):
		"""Kompletna wyświetlana nazwa"""
		for record in self:
			env = "TEST" if record.environment == 'test' else "PROD"
			auth = {
				'jet_token': 'JET',
				'certificate': 'CERT',
			}.get(record.auth_type, '?')
			record.display_name = f"{record.name} [{record.code}] {env}/{auth}"
	
	display_name = fields.Char(
		compute="_compute_display_name",
		store=True
	)
	
	# -------------------------------------------------------------------------
	# WALIDACJE
	# -------------------------------------------------------------------------
	@api.constrains('company_nip')
	def _check_company_nip(self):
		"""Walidacja NIP"""
		for record in self:
			if record.company_nip:
				nip = record.company_nip.strip()
				if len(nip) != 10 or not nip.isdigit():
					raise ValidationError("NIP musi mieć 10 cyfr")
	
	@api.constrains('auth_type', 'jet_api_key', 'jet_api_token')
	def _check_jet_credentials(self):
		"""Walidacja dla JET API"""
		for record in self:
			if record.auth_type == 'jet_token':
				if not record.jet_api_key or not record.jet_api_token:
					raise ValidationError(
						"Dla autoryzacji JET API wymagane są zarówno klucz jak i token API"
					)
	
	@api.constrains('auth_type', 'auth_keystore_p12', 'sign_keystore_p12')
	def _check_certificate_credentials(self):
		"""Walidacja dla certyfikatu"""
		for record in self:
			if record.auth_type == 'certificate':
				if not record.auth_keystore_p12 or not record.sign_keystore_p12:
					raise ValidationError(
						"Dla autoryzacji certyfikatem wymagane są oba keystore (AUTH i SIGN)"
					)

	# -------------------------------------------------------------------------
	# PROVIDER TEST
	# -------------------------------------------------------------------------

	def provider_test(self, return_status=False):
		"""
		Test dostępności środowiska KSeF.

		:param return_status:
			False → zwraca akcję UI (dla użytkownika)
			True  → zwraca dict ze statusem (dla cron/system)
		"""

		_logger.info(f"[KSeF] Test konfiguracji: {self.name}")

		status_ok = False
		notification_type = "warning"
		notification_msg = ""

		try:
			response = requests.get(self.base_url, timeout=10)

			if response.status_code != 200:
				notification_type = "danger"
				notification_msg = f"HTTP {response.status_code} - {response.reason}"

			else:
				data = response.json()
				received_status = data.get('status', 'BRAK_POLA_STATUS')

				if str(received_status).lower() == 'healthy':
					status_ok = True
					notification_type = "success"
					notification_msg = f"Status: {received_status} (OK)"
				else:
					notification_type = "danger"
					notification_msg = f"Oczekiwano 'Healthy', otrzymano: '{received_status}'"

		except Exception as e:
			notification_type = "danger"
			notification_msg = str(e)

		if not notification_msg:
			notification_msg = f"Test dla: {self.base_url}"

		# --------------------------------------------------
		# TRYB SYSTEMOWY (cron / monitoring)
		# --------------------------------------------------
		if return_status:
			return {
				"ok": status_ok,
				"message": notification_msg,
				"type": notification_type
			}

		# --------------------------------------------------
		# TRYB UI (manualny test użytkownika)
		# --------------------------------------------------
		return {
			'type': 'ir.actions.client',
			'tag': 'display_notification',
			'params': {
				'title': f'Test konfiguracji KSeF: {self.name}',
				'message': notification_msg,
				'type': notification_type,
				'sticky': True,
			}
		}

	# -------------------------------------------------------------------------
	# SEND DOCUMENT (najważniejsza metoda)
	# -------------------------------------------------------------------------

	def send_document(self, log):
		"""
		Minimalny adapter wymagany przez core.
		Manualne wywołanie = przetworzenie JEDNEGO rekordu
		przez centralny sterownik KSeF.
		"""
		_logger.info(
			"[KSeF] send_document(manual) log=%s -> _cron_process_ksef_queue",
			log.id
		)

		# WYWOŁANIE CENTRALNEGO STEROWNIKA
		CommunicationLog = self.env['communication.log']
		CommunicationLog._cron_process_ksef_queue(log_ids=[log.id])

		return True

	# -------------------------------------------------------------------------
	# STATUS CHECK (UPO / finalny status KSeF)
	# -------------------------------------------------------------------------

	def get_status(self, log):
		"""
		Pobranie statusu dokumentu z KSeF.
		Obecnie STUB.
		"""
		pass

	# -------------------------------------------------------------------------
	# FETCH DOCUMENTS (import faktur zakupowych)
	# -------------------------------------------------------------------------

	def fetch_documents(self):
		"""
		Pobieranie dokumentów (np. faktur zakupowych lub UPO).
		Obecnie STUB.
		"""
		pass

	# -------------------------------------------------------------------------
	# AUTHENTICATE
	# -------------------------------------------------------------------------
	def authenticate(self):
		"""
		Autoryzacja KSeF.
		Na razie STUB. Docelowo:
		- generowanie tokenu sesyjnego,
		- lub użycie tokenu z konfiguracji providera,
		- lub podpisywanie żądania certyfikatem.
		"""
		_logger.info(f"[KSeF] authenticate")
		return True


# =============================================================================
# Rozszerzenie CommunicationProvider o metodę do pobierania konfiguracji KSeF
# =============================================================================
class CommunicationProvider(models.Model):
	_inherit = "communication.provider"
	
	def _get_ksef_config(self):
		"""
		Zwraca konfigurację KSeF powiązaną z tym providerem.
		"""
		if self.provider_type != 'ksef':
			return None
		
		# Znajdź konfigurację KSeF
		model = self.provider_model
		config_id = self.provider_config_id
		
		if model and config_id:
			try:
				return self.env[model].browse(config_id)
			except:
				pass
		
		return None




#################################################################################
#EoF

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
#
# Odoo 18 – Account Move – KSeF QR (ONLINE / KOD I)
#
# Zakres:
# - jawny tryb wystawienia KSeF (online / offline)
# - generowanie URL QR KSeF (KOD I) na żądanie
# - generowanie obrazu QR (PNG base64) WYŁĄCZNIE w locie
#
# Wykluczenia:
# - OFFLINE / KOD II
# - zapisy obrazów QR w bazie
# - fallbacki hash
#
#################################################################################
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import hashlib
import base64
from io import BytesIO
import qrcode

import logging
_logger = logging.getLogger(__name__)

# ===============================================================================
# Transformacja Python Base64 → Base64URL 
# ===============================================================================
def base64_to_base64url(base64_string):
	"""
	Konwertuje standard Base64 na Base64URL.
	
	Args:
		base64_string (str): Standard Base64 string (może mieć = padding)
		
	Returns:
		str: Base64URL string (bez =, z - i _ zamiast + i /)
	"""
	# 1. Usuń padding '=' jeśli istnieje
	base64_string = base64_string.rstrip('=')
	
	# 2. Zamień znaki
	# '+' → '-'
	# '/' → '_'
	base64url_string = base64_string.replace('+', '-').replace('/', '_')
	
	return base64url_string

def base64url_to_base64(base64url_string):
	"""
	Konwertuje Base64URL na standard Base64.
	
	Args:
		base64url_string (str): Base64URL string (bez =, z - i _)
		
	Returns:
		str: Standard Base64 string (z padding = jeśli potrzebny)
	"""
	# 1. Zamień znaki z powrotem
	# '-' → '+'
	# '_' → '/'
	base64_string = base64url_string.replace('-', '+').replace('_', '/')
	
	# 2. Dodaj padding '=' aby długość była wielokrotnością 4
	padding = 4 - (len(base64_string) % 4)
	if padding != 4:
		base64_string += '=' * padding
	
	return base64_string


class AccountMove(models.Model):
	_inherit = "account.move"

	# -------------------------------------------------------------------------
	# KONFIGURACJA / STAN
	# -------------------------------------------------------------------------

	ksef_issue_mode = fields.Selection(
		[
			("online", "KSeF – online"),
			("offline", "KSeF – offline"),
		],
		string="Tryb wystawienia KSeF",
		default="online",
		required=True,
		tracking=True,
		copy=False,
		help="Jawny tryb wystawienia faktury dla KSeF i kodów QR.",
	)

	# Lekkie cache (opcjonalne, techniczne)
	ksef_invoice_hash = fields.Char(
		string="Hash faktury (KSeF)",
		readonly=True,
		copy=False,
		help="SHA-256 XML faktury wysyłanej do KSeF (Base64URL).",
	)

	ksef_qr_invoice_url = fields.Char(
		string="URL QR KSeF",
		readonly=True,
		copy=False,
		help="Pełny URL KOD I dla weryfikacji faktury w KSeF.",
	)

	# -------------------------------------------------------------------------------
	# Tryb Offline
	# -------------------------------------------------------------------------------
	ksef_offline_mode = fields.Selection(
		[
			("mf", "Awaria KSeF (MF)"),
			("taxpayer", "Awaria po stronie podatnika"),
			("business", "Tryb uzgodniony / organizacyjny"),
		],
		string="Rodzaj trybu OFFLINE (KSeF)",
		copy=False,
		tracking=True,
	)

	ksef_offline_reason = fields.Text(
		string="Uzasadnienie wystawienia w trybie OFFLINE",
		copy=False,
		tracking=True,
	)

	ksef_offline_state = fields.Char(
		string="Status OFFLINE (KSeF)",
		compute="_compute_ksef_offline_state",
		readonly=True,
		tracking=True,
		copy=False,
	)

	def _compute_ksef_offline_state(self):
		for move in self:
			if move.ksef_issue_mode != "offline":
				move.ksef_offline_state = False
				continue

			logs = self.env["communication.log"].search(
				[
					("company_id", "=", move.company_id.id),
					("document_model", "=", "account.move"),
					("document_id", "=", move.id),
					("provider_id.provider_type", "=", "ksef"),
				],
				order="id desc",
				limit=1,
			)

			if not logs:
				move.ksef_offline_state = "Brak danych"
				continue

			state_map = {
				"offline_pending": "Oczekuje na dosłanie do KSeF",
				"queued": "W kolejce do wysyłki",
				"processing": "W trakcie wysyłki",
				"sent": "Wysłano do KSeF",
				"confirmed": "Przyjęto w KSeF",
				"completed": "Zakończono",
				"failed": "Błąd wysyłki",
			}

			move.ksef_offline_state = state_map.get(
				logs.state, logs.state
			)

	@api.constrains("ksef_issue_mode", "ksef_offline_mode", "ksef_offline_reason")
	def _check_ksef_offline_fields(self):
		for move in self:
			if move.ksef_issue_mode == "offline":
				if not move.ksef_offline_mode:
					raise ValidationError(
						_("Należy wskazać rodzaj trybu OFFLINE (KSeF).")
					)
				if not move.ksef_offline_reason:
					raise ValidationError(
						_("Należy podać uzasadnienie wystawienia w trybie OFFLINE.")
					)

	# -------------------------------------------------------------------------
	# ŹRÓDŁO XML (JEDYNE, BEZ ZGADYWANIA)
	# -------------------------------------------------------------------------

	def _get_ksef_invoice_xml_bytes(self):
		"""
		Zwraca BYTES dokładnie tego XML, który został użyty do wysyłki do KSeF.

		Źródło:
		- communication.log (provider_type = 'ksef')

		Brak XML => brak QR (celowo, zgodnie z MF).
		"""
		self.ensure_one()

		log = self.env["communication.log"].search(
			[
				("document_model", "=", "account.move"),
				("document_id", "=", self.id),
				("file_data", "!=", False),
				("provider_id.provider_type", "=", "ksef"),
				('company_id', '=',  self.company_id.id),
			],
			order="create_date desc",
			limit=1,
		)

		if not log or not log.file_data:
			return None

		if isinstance(log.file_data, bytes):
			return log.file_data

		return log.file_data.encode("utf-8")

	def _get_ksef_invoice_hash_from_log(self, ksef_invoice_hash=None):
		"""
		Zwraca hash faktury KSeF (Base64) zapisany podczas wysyłki.
		Jest to JEDYNE źródło prawdy dla QR ONLINE.
		"""
		self.ensure_one()

		domain = [
			("document_model", "=", "account.move"),
			("document_id", "=", self.id),
		]
		if not ksef_invoice_hash:
			domain.append( ("ksef_invoice_hash", "!=", False) )

		log = self.env["communication.log"].search( domain, order="create_date desc", limit=1,)


		seq = 1
		if not log:
			if self.log_ids:
				log = self.log_ids[0]
			else:
				return None

		if ksef_invoice_hash and log:
			log.ksef_invoice_hash = ksef_invoice_hash
		elif log and log.file_data:
			ksef_invoice_hash = self._compute_ksef_invoice_hash()
			if ksef_invoice_hash:
				log.ksef_invoice_hash = ksef_invoice_hash
			seq = 2
		else:
			seq = 9

		log_ids = self.log_ids
		result = log.ksef_invoice_hash if log else None

		_logger.info(
			f"\n🚨  _get_ksef_invoice_hash_from_log [{log}]"
			f"\nksef_invoice_hash {ksef_invoice_hash}"
			f"\nlog.ksef_invoice_hash {log.ksef_invoice_hash}"
			f"\nresult {result}"
			f"\nlog_ids = {log_ids}"
			f"\ndocument_id = {self.id}"
			f"\ndomain = {domain}"
			f"\nseq = {seq}"
		)

		return result

	# -------------------------------------------------------------------------
	# HASH SHA-256 → Base64URL (BEZ FALLBACKÓW)
	# -------------------------------------------------------------------------

	def _compute_ksef_invoice_hash(self):
		"""
		Oblicza hash SHA-256 z XML faktury i koduje go jako Base64URL.

		Zapisuje wynik w polu ksef_invoice_hash (cache).
		"""
		self.ensure_one()

		if self.ksef_invoice_hash:
			_logger.info(f'\n⚡️ _compute_ksef_invoice_hash: ksef_invoice_hash EXIST !')
			return self.ksef_invoice_hash

		file_data = self._get_ksef_invoice_xml_bytes()
		if not file_data:
			_logger.info(f'\n⚡️ _compute_ksef_invoice_hash: NOT file_data')
			return None

		if isinstance(file_data, bytes):
			try:
				xml_bytes = base64.b64decode(file_data)
			except:
				xml_bytes = file_data
		else:
			xml_bytes = file_data.encode('utf-8')

		xml_hash = hashlib.sha256(xml_bytes).digest()
		xml_hash_b64 = base64.b64encode(xml_hash).decode('utf-8')

		self.ksef_invoice_hash = xml_hash_b64
		_logger.info(f'\n⚡️ _compute_ksef_invoice_hash: xml_hash_b64 = {xml_hash_b64}')
		return xml_hash_b64

	# -------------------------------------------------------------------------
	# KONFIGURACJA QR (Z PROVIDERA)
	# -------------------------------------------------------------------------

	def _get_ksef_qr_base_url(self):
		"""
		Pobiera bazowy URL QR z konfiguracji providera KSeF.

		communication.provider.ksef.qr_code_url
		jest JEDYNYM źródłem prawdy.
		"""
		self.ensure_one()

		provider = self.env["communication.provider.ksef"].search(
			[("company_id", "=", self.company_id.id)],
			limit=1,
		)

		if not provider:
			raise UserError(
				_("Brak skonfigurowanego providera KSeF dla tej firmy.")
			)

		return provider.get_qr_base_url()

	# -------------------------------------------------------------------------
	# BUDOWA URL KOD I (ONLINE)
	# -------------------------------------------------------------------------

	def _build_ksef_qr_invoice_url(self):
		"""
		Buduje pełny URL KOD I dla faktury ONLINE.

		Format:
		{base_url}/invoice/{NIP}/{DD-MM-RRRR}/{SHA256_BASE64URL}
		
		Dla faktur wychodzących (out_invoice, out_refund):
			NIP = NIP firmy (wystawcy)
		Dla faktur przychodzących (in_invoice, in_refund):
			NIP = NIP partnera (wystawcy faktury)
		"""
		self.ensure_one()

		ksef_invoice_hash = None
		if self.ksef_issue_mode == "offline":
			ksef_invoice_hash = self._compute_ksef_invoice_hash()
			_logger.info(f'\n💥 OFFLINE MODE _build_ksef_qr_invoice_url ksef_invoice_hash = {ksef_invoice_hash}')

		invoice_hash_b64 = self._get_ksef_invoice_hash_from_log(ksef_invoice_hash=ksef_invoice_hash)
		if not invoice_hash_b64:
			return None

		invoice_hash = base64_to_base64url(invoice_hash_b64)

		if not self.ksef_invoice_hash:
			self.ksef_invoice_hash = invoice_hash

		if not self.invoice_date:
			raise UserError(_("Brak daty wystawienia faktury (P_1)."))

		# ============================================================
		# ✅ POPRAWKA: WYBÓR NIP W ZALEŻNOŚCI OD KIERUNKU FAKTURY
		# ============================================================
		if self.move_type in ('out_invoice', 'out_refund'):
			# Faktura sprzedaży/wysłana – NIP wystawcy (firma)
			nip = (self.company_id.vat or "").replace("PL", "").replace("-", "")
			_logger.info(f"[KSeF QR] Faktura wychodząca, używam NIP firmy: {nip}")
		else:
			# Faktura zakupu/importowana – NIP wystawcy (partner)
			nip = (self.partner_id.vat or "").replace("PL", "").replace("-", "")
			_logger.info(f"[KSeF QR] Faktura przychodząca, używam NIP partnera: {nip}")
		
		if len(nip) != 10 or not nip.isdigit():
			raise UserError(_("Nieprawidłowy NIP sprzedawcy."))

		base_url = self._get_ksef_qr_base_url()
		date_str = self.invoice_date.strftime("%d-%m-%Y")

		url = f"{base_url}/invoice/{nip}/{date_str}/{invoice_hash}"

		self.ksef_qr_invoice_url = url
		return url

	# -------------------------------------------------------------------------
	# QR IMAGE (PNG BASE64) – WYŁĄCZNIE ON-DEMAND
	# -------------------------------------------------------------------------

	def _get_ksef_qr_image_base64(self):
		"""
		Generuje obraz QR (PNG base64) WYŁĄCZNIE w locie:
		- przy generowaniu PDF
		- przy manualnym podglądzie

		Nic nie zapisuje w bazie.
		"""
		self.ensure_one()

		url = self._build_ksef_qr_invoice_url()
		if not url:
			return None

		qr = qrcode.QRCode(
			version=1,
			error_correction=qrcode.constants.ERROR_CORRECT_L,
			box_size=6,
			border=3,
		)
		qr.add_data(url)
		qr.make(fit=True)

		img = qr.make_image(fill_color="black", back_color="white")
		buffer = BytesIO()
		img.save(buffer, format="PNG")

		return base64.b64encode(buffer.getvalue()).decode()

	# -------------------------------------------------------------------------
	# AKCJA UI – MANUALNE PRZYGOTOWANIE QR
	# -------------------------------------------------------------------------

	def action_generate_ksef_qr(self):
		"""
		Akcja użytkownika:
		- waliduje możliwość wygenerowania QR
		- NIE zapisuje obrazów
		- przygotowuje dane pod PDF / e-mail
		"""
		self.ensure_one()

		_logger.info(f"\nAKCJA UI – MANUALNE PRZYGOTOWANIE QR :: action_generate_ksef_qr")

		#if self.ksef_issue_mode != "online":
		#	raise UserError(_("Kod QR dostępny jest tylko dla trybu ONLINE."))

		url = self._build_ksef_qr_invoice_url()

		if not url:
			raise UserError(
				_("Nie można wygenerować kodu QR – Nie mogę ustalić URL faktury KSeF.")
			)

		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"title": _("KSeF"),
				"message": _(
					"Kod QR KSeF został przygotowany i będzie widoczny "
					"w wydruku PDF faktury."
					f"{url}"
				),
				"type": "success",
				"sticky": False,
			},
		}

	# -----------------------------------------------------------------------
	# na potrzeby wydruku faktury z QR
	# -----------------------------------------------------------------------
	def get_ksef_provider(self):
		"""Pobierz aktywnego providera KSeF dla tej faktury."""
		self.ensure_one()
		log = self.env["communication.log"].search(
			[
				("document_model", "=", "account.move"),
				("document_id", "=", self.id),
			],
			order="create_date desc",
			limit=1,
		)
		return log.provider_id if log else False

	def get_ksef_report_template(self):
		"""Pobierz szablon raportu z providera KSeF lub użyj domyślnego"""
		self.ensure_one()

		provider = self.get_ksef_provider()
		report = "account.report_invoice_document"

		if provider and provider.provider_model and provider.provider_config_id:
			# provider.provider_config_id to u Ciebie INT (id rekordu konfiguracji)
			provider_config = self.env[provider.provider_model].sudo().browse(provider.provider_config_id)
			if provider_config and provider_config.exists():
				# qr_report_template_id jest ir.ui.view -> .key to technical name widoku
				if provider_config.qr_report_template_id:
					report = provider_config.qr_report_template_id.key

		_logger.info(f"[KSeF] get_ksef_report_template report = {report}")
		return report

	def action_print_ksef_invoice(self):
		"""Akcja do drukowania faktury z QR KSeF"""
		self.ensure_one()

		self.action_generate_ksef_qr()

		if not self.ksef_qr_invoice_url:
			raise UserError(
				"Ta faktura nie ma wygenerowanego kodu QR KSeF. "
				"Najpierw wygeneruj kod QR poprzez menu KSeF."
			)

		provider = self.get_ksef_provider()
		if not provider:
			raise UserError("Nie skonfigurowano providera KSeF dla tej faktury.")

		report_template = self.get_ksef_report_template()

		report_action = self.env["ir.actions.report"].search(
			[
				("report_name", "=", report_template),
			],
			limit=1
		)
		if report_action:
			return report_action.report_action(self)

		# fallback (jeśli raportu nie znaleziono)
		return self.env.ref("account.account_invoices").report_action(self)


	# ===============================================================================
	# TRYB OFFLINE
	# ===============================================================================
	def action_issue_ksef_offline(self):
		self.ensure_one()

		# ---------------------------------------------------------
		# 1. Tryb wystawienia
		# ---------------------------------------------------------
		if self.ksef_issue_mode != "online":
			raise UserError(
				_("Tryb OFFLINE można zastosować tylko dla faktury w trybie ONLINE.")
			)

		# ---------------------------------------------------------
		# 2. Sprawdź, czy OFFLINE już nie istnieje
		# ---------------------------------------------------------
		existing_offline = self.env["communication.log"].search(
			[
				('company_id', '=', self.company_id.id ),
				("document_model", "=", "account.move"),
				("document_id", "=", self.id),
				("provider_id.provider_type", "=", "ksef"),
				("state", "in", ("offline_pending", "error" )),
			],
			limit=1,
		)

		if existing_offline:
			raise UserError(
				_("Dla tej faktury istnieje już aktywny proces OFFLINE.")
			)

		# ---------------------------------------------------------
		# 3. Ostatnia próba ONLINE
		# ---------------------------------------------------------
		last_online_log = self.env["communication.log"].search(
			[
				("document_model", "=", "account.move"),
				("document_id", "=", self.id),
				("provider_id.provider_type", "=", "ksef"),
			],
			order="id desc",
			limit=1,
		)

		#if not last_online_log:
		#	raise UserError(
		#		_("Brak wcześniejszej próby wysyłki do KSeF. "
		#		  "Tryb OFFLINE można zastosować wyłącznie po nieudanej próbie ONLINE.")
		#	)

		if last_online_log.state in ("sent", "confirmed", "completed"):
			raise UserError(
				_("Faktura została już skutecznie wysłana do KSeF.")
			)

		# ---------------------------------------------------------
		# 4. Dane decyzji OFFLINE
		# ---------------------------------------------------------
		if not self.ksef_offline_mode:
			raise UserError(_("Wybierz rodzaj trybu OFFLINE (KSeF)."))

		if not self.ksef_offline_reason:
			raise UserError(_("Podaj uzasadnienie wystawienia w trybie OFFLINE."))

		# ---------------------------------------------------------
		# 5. Utrwalenie decyzji na fakturze
		# ---------------------------------------------------------
		self.write({
			"ksef_issue_mode": "offline",
		})

		# ---------------------------------------------------------
		# 6. Delegacja do procesu OFFLINE
		# ---------------------------------------------------------
		self.env["communication.provider.ksef.offline"].issue_offline(
			invoice=self,
			origin_log=last_online_log,
			offline_mode=self.ksef_offline_mode,
			reason=self.ksef_offline_reason,
		)

		# ---------------------------------------------------------
		# 7. Audyt (opcjonalny, ale polecany)
		# ---------------------------------------------------------
		self.message_post(
			body=_(
				"Użytkownik potwierdził wystawienie faktury w trybie OFFLINE (KSeF)."
			)
		)

		# ---------------------------------------------------------
		# 8. UX – odśwież formularz
		# ---------------------------------------------------------
		return {
			"type": "ir.actions.client",
			"tag": "reload",
		}



#EoF

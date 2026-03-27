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
"""
KSeF – OFFLINE MODE HANDLER (Model A)

Plik:
	communication_provider_ksef_offline.py

Zakres:
- wejście w tryb offline (nowy communication.log)
- stan offline_pending
- automatyczne przejście offline → online (Model A)
- monitorowanie dostępności KSeF + deadline

NIE:
- generuje XML
- nie wysyła dokumentów
- nie modyfikuje istniejących providerów
#################################################################################
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class CommunicationLog(models.Model):
	_inherit = 'communication.log'

	state = fields.Selection(
		selection_add=[
			("superseded", "Zastąpiony inną operacją"),
			("offline_pending", "Offline – oczekuje na dosłanie"),
		],
	)

class CommunicationProviderKsefOffline(models.AbstractModel):
	"""
	Warstwa logiczna OFFLINE dla KSeF.

	Celowo:
	- AbstractModel
	- bez provider_type
	- bez konfiguracji UI
	"""

	_name = "communication.provider.ksef.offline"
	_description = "KSeF Offline Logic (Overlay)"

	# -------------------------------------------------------------------------
	# 1. WEJŚCIE W TRYB OFFLINE (DECYZJA UŻYTKOWNIKA)
	# -------------------------------------------------------------------------

	@api.model
	def issue_offline(
		self,
		invoice,
		origin_log,
		offline_mode,
		reason,
		auto_resend=True,
	):
		"""
		Tworzy NOWY communication.log dla faktury w trybie OFFLINE.

		origin_log:
			- wcześniejsza, nieudana próba ONLINE
			- NIE jest modyfikowana (poza zamknięciem logicznym)
		"""

		if not origin_log:
			raise UserError(_("Brak logu źródłowego ONLINE."))

		if offline_mode not in ("mf", "taxpayer", "business"):
			raise UserError(_("Nieprawidłowy tryb offline."))

		now = fields.Datetime.now()

		# Wyliczenie deadline prawnego
		legal_deadline = self._compute_legal_deadline(invoice.invoice_date or now)

		# --- ODTWORZENIE XML ---
		file_data = origin_log.file_data  # kopia oryginalnego XML
		if not file_data:
			raise UserError("Brak XML w logu źródłowym — nie można wystawić faktury offline.")

		# --- HASH ZAŁĄCZANY DO LOGU ---
		xml_hash_b64 = invoice._compute_ksef_invoice_hash()

		# --- NOWY LOG OFFLINE ---
		offline_log = self.env["communication.log"].create({
			"document_model": "account.move",
			"document_id": invoice.id,
			"direction": "export",

			"provider_id": origin_log.provider_id.id,
			"template_id": origin_log.template_id.id if origin_log.template_id else False,
			"provider_status": "W wyniku błędu przełączono obsługę do trybu Offline",

			"state": "offline_pending",
			"status": "success",

			# KLUCZOWE
			"operation": origin_log.operation or "send_invoice",
			"file_name": origin_log.file_name,
			"file_data": file_data,
			"ksef_invoice_hash": xml_hash_b64,
			"ksef_next_execution": fields.Datetime.now(),

			# --- OFFLINE META ---
			"context_json": {
				#**(origin_log.context_json or {}),
				"offline_mode": offline_mode,
				"offline_issued_at": now.isoformat(),
				"legal_deadline_at": legal_deadline.isoformat(),
				"auto_resend": auto_resend,
				"origin_log_id": origin_log.id,
				"offline_reason": reason,
			},
		})

		origin_log.write({
			"state": "superseded",
			"status": "superseded",
			"provider_status": 'W wyniku błędu przełaczono obsługę do trybu Offline',
			"context_json": {
				"offline_switched": True,
				"offline_switched_at": fields.Datetime.now().isoformat(),
				"offline_switched_reason": reason,
				"offline_new_log_id": offline_log.id,   # powiązanie z nowym logiem
			}
		})

		# 🔴 KLUCZOWE DLA UI
		invoice.write({
			"ksef_log_id": offline_log.id
		})

		_logger.info(
			"[KSeF OFFLINE] Invoice %s issued in offline mode (%s)",
			invoice.id,
			offline_mode,
		)

		return offline_log

	# -------------------------------------------------------------------------
	# 2. CRON – MONITOR OFFLINE (MODEL A)
	# -------------------------------------------------------------------------

	@api.model
	def cron_ksef_offline_monitor(self):
		"""
		CRON:
		- NIE wysyła
		- NIE zmienia stanu na sent
		- tylko przełącza offline_pending → queued
		"""

		logs = self.env["communication.log"].search([
			("state", "=", "offline_pending"),
			("direction", "=", "export"),
			("provider_id.provider_type", "=", "ksef"),
		])

		for log in logs:
			ctx = log.context_json or {}
			auto_resend = ctx.get("auto_resend", True)

			if not auto_resend:
				continue

			if self._can_resend_now(ctx):
				_logger.info(
					"[KSeF OFFLINE] Auto-resend enabled, enqueue log %s",
					log.id,
				)
				log.queue_for_sending()

	# -------------------------------------------------------------------------
	# 3. WARUNKI WZNOWIENIA (DWA ZEGARY)
	# -------------------------------------------------------------------------

	def _can_resend_now(self, ctx):
		"""
		Model A:
		- jeśli KSeF technicznie dostępny → TRUE
		- deadline prawny = bezpiecznik
		"""

		# Zegar techniczny (24/7)
		if self._is_ksef_available():
			return True

		# Zegar prawny
		deadline = ctx.get("legal_deadline_at")
		if deadline:
			deadline_dt = fields.Datetime.from_string(deadline)
			if fields.Datetime.now() >= deadline_dt:
				return True

		return False

	# -------------------------------------------------------------------------
	# 4. PING KSeF (SOFT CHECK)
	# -------------------------------------------------------------------------

	def _is_ksef_available(self):
		"""
		Minimalny soft-check dostępności KSeF.

		Docelowo:
		- ping API
		- lub próba authenticate()
		"""
		try:
			provider = self.env["communication.provider"].search(
				[("provider_type", "=", "ksef")],
				limit=1,
			)
			if not provider:
				return False

			# Soft check – NIE wysyłamy dokumentu
			provider.authenticate()
			return True

		except Exception:
			return False

	# -------------------------------------------------------------------------
	# 5. DEADLINE – DZIEŃ ROBOCZY
	# -------------------------------------------------------------------------

	def _compute_legal_deadline(self, base_date):
		"""
		Następny dzień roboczy + 23:59:59
		(weekendy pomijane, święta można dodać później)
		"""
		if not base_date:
			base_date = fields.Date.today()

		d = base_date
		while True:
			d += timedelta(days=1)
			if d.weekday() < 5:  # pon-pt
				break

		return datetime.combine(d, datetime.max.time())


#EoF

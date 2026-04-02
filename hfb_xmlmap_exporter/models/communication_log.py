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
"""@version 17.2.3
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import re
import base64
import json
from odoo import release
import io
import uuid
from lxml import etree

import logging
_logger = logging.getLogger(__name__)

from odoo import models, fields

class CommunicationLog(models.Model):
	_name = "communication.log"
	_description = "Rejestr komunikacji z systemami zewnętrznymi"
	_inherit = ["mail.thread", "mail.activity.mixin"]
	_order = "create_date desc"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	document_model = fields.Char(string="Model dokumentu")
	document_id = fields.Integer(string="ID dokumentu")
	external_id = fields.Char(string="Zewnętrzne ID dokumentu", tracking=True)
	message = fields.Text(string="Opis zdarzenia", tracking=True)
	duration_ms = fields.Integer(string="Czas wykonania (ms)")
	executed_by = fields.Many2one("res.users", string="Użytkownik", default=lambda self: self.env.user, tracking=True)

	# ============================================================
	#  KIERUNEK PRZEPŁYWU DANYCH (BIZNESOWY)
	# ============================================================
	direction = fields.Selection([
		("export", "Eksport"),
		("import", "Import"),
	], 
		required=True,
		tracking=True,
		string="Kierunek biznesowy dokumentu",
		help="""
			Określa kierunek biznesowy dokumentu:
			- 'export': dokument wychodzi z Odoo do systemu zewnętrznego (np. KSeF, PEPPOL).
			- 'import': dokument został pobrany z systemu zewnętrznego do Odoo.

			Pole opisuje sens biznesowy rekordu — 
			NIE dotyczy operacji ani stanu, ale natury dokumentu.
		"""
	)

	# ============================================================
	#  OPIS WYKONANEJ OPERACJI (TRANSPORT / API)
	# ============================================================
	operation = fields.Selection([
		("send", "Wysłanie dokumentu"),
		("fetch", "Pobranie dokumentu"),
		("status", "Sprawdzenie statusu"),
		("auth", "Autoryzacja"),
	], 
		string="Operacja",
		copy=False,
		tracking=True,
		help="""
			Określa rodzaj operacji wykonanej przez providera lub kanał komunikacji:
			- 'send'   : dokument został wysłany do API.
			- 'fetch'  : dokument został pobrany z API (np. faktura zakupu).
			- 'status' : wykonano zapytanie o stan dokumentu (np. UPO, processing).
			- 'auth'   : wykonano operację autoryzacji lub pobrania tokenu.

			Pole opisuje TYLKO jedną operację techniczną,
			NIE stan całego procesu i NIE kierunek biznesowy.
		"""
	)

	# ============================================================
	#  STATUS WYNIKU OSTATNIEJ OPERACJI PROVIDERA
	# ============================================================
	status = fields.Selection([
		("success", "Sukces"),
		("warning", "Ostrzeżenie"),
		("error", "Błąd"),
	], 
		default="success",
		tracking=True,
		help="""
			Wynik ostatniej operacji wykonanej przez providera.
			Wskazuje rezultat techniczny, zwrócony przez API zewnętrzne:

			- 'success' : operacja wykonana poprawnie.
			- 'warning' : API zwróciło ostrzeżenie, wymagające uwagi.
			- 'error'   : operacja zakończyła się błędem (np. odrzucony dokument,
						  błąd HTTP, brak tokenu, timeout).

			Status NIE opisuje całego flow, a jedynie wynik
			ostatnio wykonanej operacji transportowej.
		"""
	)

	# ============================================================
	#  STAN PRZEPŁYWU KOMUNIKACJI (WORKFLOW REKORDU)
	# ============================================================

	state = fields.Selection([
		("draft", "Szkic"),
		("generated", "Wygenerowano"),
		("validated", "Zwalidowano"),
		("queued", "W kolejce"),
		("sent", "Wysłano"),
		("received", "Odebrano / Zaimportowano"),
		("superseded", "Zastąpiony inną operacją"),
		("error", "Błąd"),
	], 
		default="draft",
		tracking=True,
		copy=False,
		help="""
			Główny workflow komunikacji — opisuje etap przetwarzania logu:

			- 'draft'		: rekord utworzony, ale jeszcze nieprzetworzony.
			- 'generated'	: XML wygenerowany z szablonu.
			- 'validated'	: dokument przeszedł walidację (np. XSD).
			- 'queued'		: dokument oczekuje na wysyłkę przez provider CRON.
			- 'sent'		: dokument został wysłany do systemu zewnętrznego.
			- 'received'	: otrzymano odpowiedź, UPO lub zaimportowany dokument.
			- 'superseded'	: flow przerwano zastępując inną operacja.
			- 'error'		: błąd krytyczny procesu (nie: operacji API).

			'state' odzwierciedla przebieg całego procesu,
			a nie jednej konkretnej operacji — dlatego jest oddzielone od 'status'.
		"""
	)

	# -------------------------------------------------------------------------
	# Provider
	# -------------------------------------------------------------------------
	provider_id = fields.Many2one(
		"communication.provider",
		string="Provider",
		required=True,
		tracking=True,
	)

	provider_type = fields.Selection(
		related='provider_id.provider_type'
	)

	template_id = fields.Many2one(
		"xml.export.template",
		string="Szablon",
		tracking=True,
	)

	document_ref = fields.Reference(
		string="Dokument",
		selection=lambda self: [
			(m.model, m.name) for m in self.env["ir.model"].search([])
		],
		compute="_compute_document_ref",
		store=False,
	)

	def _compute_document_ref(self):
		for rec in self:
			if rec.document_model and rec.document_id:
				rec.document_ref = f"{rec.document_model},{rec.document_id}"
			else:
				rec.document_ref = False

	# Plik XML / JSON / dowolny
	file_name = fields.Char(string="Nazwa pliku", tracking=True)
	file_data = fields.Binary(string="Dane pliku")
	file_size = fields.Integer(
		string="Rozmiar [B]",
		compute="_compute_file_size",
		store=True,
	)

	@api.depends("file_data")
	def _compute_file_size(self):
		for rec in self:
			rec.file_size = len(base64.b64decode(rec.file_data)) if rec.file_data else 0

	# Walidacja XSD
	validated = fields.Boolean(string="Zwalidowany")
	validation_message = fields.Text(string="Wynik walidacji XSD")

	# Payload – dodatkowe dane (np. request/response JSON)
	payload_request = fields.Text(string="Treść żądania")
	payload_response = fields.Text(string="Treść odpowiedzi")

	# Wyniki providerów
	provider_status = fields.Char(string="Status providera")
	provider_message = fields.Text(string="Komunikat providera")

	# Obsługa czasu
	duration_ms = fields.Integer(string="Czas wykonania [ms]")
	send_date = fields.Datetime(string="Data wysłania")
	receive_date = fields.Datetime(string="Data importu")

	executed_by = fields.Many2one(
		"res.users",
		string="Wykonane przez",
		default=lambda self: self.env.user,
	)

	context_json = fields.Json(string="Kontekst")

	# -------------------------------------------------------------------------
	#  UJEDNOLICONY WORKFLOW COMMUNICATION.LOG
	#  ZGODNY Z POLAMI: direction, operation, status, state
	# -------------------------------------------------------------------------
	def mark_generated(self):
		"""
		Ustawia rekord w stan "generated".
		Wykorzystywane po wygenerowaniu XML z szablonu.
		"""
		self.write({
			"state": "generated",
			"status": "success",
			"operation": False,  # brak operacji transportowej
		})

	def mark_validated(self, msg="OK"):
		"""
		Ustawia stan po poprawnej walidacji XML (XSD).
		"""
		self.write({
			"validated": True,
			"validation_message": msg,
			"state": "validated",
			"status": "success",
			"operation": False,  # walidacja to nie operacja transportowa
		})

	def queue_for_sending(self):
		"""
		Ustawia rekord w stan 'queued', sygnalizując CRON-owi providera
		gotowość do wysyłki.
		"""
		self.write({
			"state": "queued",
			"status": "success",
			"operation": "send",  # planowana operacja
		})

	def mark_sent(self, external_id=None):
		"""
		Wykonywane WYŁĄCZNIE przez providera.
		Oznacza pomyślną wysyłkę dokumentu do systemu zewnętrznego.
		"""
		self.write({
			"state": "sent",
			"status": "success",
			"operation": "send",
			"send_date": fields.Datetime.now(),
			"external_id": external_id or self.external_id,
		})

	def mark_received(self, payload=None):
		"""
		Wykonywane przez providera po:
		- otrzymaniu UPO,
		- pobraniu dokumentu,
		- zakończeniu przetwarzania (KSeF Completed).

		Pole 'payload_response' może zawierać JSON z odpowiedzią API.
		"""
		vals = {
			"state": "received",
			"status": "success",
			"receive_date": fields.Datetime.now(),
		}

		# Jeżeli provider przekazuje payload → zapisz go
		if payload:
			vals["payload_response"] = payload

		# Jeśli odpowiedź pochodzi z FETCH → operation=fetch
		if self.direction == "import":
			vals["operation"] = "fetch"
		#else:
		#	vals["operation"] = "receive"

		self.write(vals)

	def mark_status_checked(self, payload=None):
		"""
		Wykonywane przez providera podczas sprawdzania statusu wysłanego dokumentu.
		Nie zmienia state (chyba że provider uzna status za finalny).
		"""
		vals = {
			"operation": "status",
			"status": "success",
		}
		if payload:
			vals["payload_response"] = payload

		self.write(vals)

	def mark_error(self, msg, operation=None):
		"""
		Ustawia rekord w stan błędu procesu.
		To NIE jest błąd API → ten sygnalizujemy w status='error'
		ale błąd samego procesu workflow.
		"""
		self.write({
			"state": "error",
			"status": "error",
			"operation": operation or self.operation or None,
			"provider_message": msg,
		})

	# -----------------------------------------------------------------------------
	# AKCJE FORMULARZA - opcjonalne
	# -----------------------------------------------------------------------------
	def action_send_manual(self):
		"""
		Ręczne wywołanie wysyłki dokumentu do providera (bez CRON).
		Używane gdy użytkownik chce natychmiast wykonać transmit.

		Różnica względem action_resend():
		- action_resend resetuje log do queued i wywołuje wysyłkę
		- action_send_manual nie zmienia stanu workflow, tylko natychmiast wysyła
		"""

		self.ensure_one()

		if self.direction not in  ["export","import"]:
			raise UserError("Ta akcja dostępna jest tylko dla dokumentów podlegających wysyłce.")

		if self.direction == "export" and (not self.file_data):
			raise UserError("Brak pliku XML do wysyłki.")

		provider = self.provider_id

		# oznaczamy operację jako wysyłkę manualną
		if self.direction == "export":
			self.operation = "send"

		ok = provider.send_document(self)

		if not ok:
			# provider mark_error już uzupełni state/status/message
			raise UserError("Komunikacja nie powiodła się – sprawdź szczegóły w logu.")

		# Odśwież konkretne pola w formularzu
		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"title": "Wysłano polecenie",
				"message": "Komunikat został wysłany do systemu zewnętrznego.",
				"type": "success",
				"sticky": False,
				"next": {
					"type": "ir.actions.client",
					"tag": "reload_context",  # Odświeża kontekst
				}
			}
		}

	def action_resend(self):
		self.ensure_one()
		provider = self.provider_id

		self.state = "queued"
		self.status = "success"
		self.operation = "send"

		provider.send_document(self)

	def action_check_status(self):
		self.ensure_one()
		provider = self.provider_id
		provider.get_status( self)


#EoF

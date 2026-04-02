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
"""@version 17.2.1
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
#################################################################################
#
# Odoo 18 – KSeF QR (ONLINE / KOD I)
#
# Moduł: hfb_xmlmap_exporter / communication.provider.ksef
#
# Zakres:
# - konfiguracja bazowego URL dla kodów QR KSeF
# - jedno źródło prawdy dla środowiska (test / demo / prod)
#
# Logika generowania QR:
# - WYŁĄCZNIE w account.move
# - WYŁĄCZNIE on-demand
#
#################################################################################

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CommunicationProviderKsef(models.Model):
	_inherit = "communication.provider.ksef"
	"""
	Rozszerzenie providera KSeF o konfigurację QR (ONLINE / KOD I).

	Ten model:
	- NIE generuje kodów QR
	- NIE zna faktur
	- NIE obsługuje OFFLINE / KOD II
	- udostępnia WYŁĄCZNIE konfigurację URL

	account.move korzysta z tej konfiguracji jako jedynego źródła prawdy.
	"""

	qr_code_url = fields.Char(
		string="URL dla QR KSeF",
		help=(
			"Bazowy adres URL dla kodów QR KSeF.\n"
			"Przykłady:\n"
			"• https://qr-test.ksef.mf.gov.pl\n"
			"• https://qr-demo.ksef.mf.gov.pl\n"
			"• https://qr.ksef.mf.gov.pl"
		),
		default="https://qr-test.ksef.mf.gov.pl",
		required=True,
	)

	# -------------------------------------------------------------------------
	# WALIDACJA
	# -------------------------------------------------------------------------

	@api.constrains("qr_code_url")
	def _check_qr_code_url(self):
		"""
		Walidacja bazowego URL QR.
		"""
		for provider in self:
			url = (provider.qr_code_url or "").strip()

			if not url:
				raise ValidationError(_("URL dla QR KSeF jest wymagany."))

			if not url.startswith(("http://", "https://")):
				raise ValidationError(
					_("URL dla QR KSeF musi zaczynać się od http:// lub https://")
				)

	# -------------------------------------------------------------------------
	# API PUBLICZNE (KONTRAKT DLA account.move)
	# -------------------------------------------------------------------------

	def get_qr_base_url(self):
		"""
		Zwraca bazowy URL QR bez końcowego slasha.

		Jest to JEDYNE publiczne API tego pliku,
		wykorzystywane przez account.move do budowy URL KOD I.

		Returns:
			str: np. https://qr-test.ksef.mf.gov.pl
		"""
		self.ensure_one()
		return self.qr_code_url.rstrip("/")

	# -------------------------------------------------------------------------
	# Rozszerzenie modelu Communication Provider KSeF
	# -------------------------------------------------------------------------

	qr_report_template_id = fields.Many2one(
		"ir.ui.view",
		string="Szablon wydruku faktury (QR)",
		domain="[('type','=','qweb')]",
		help=(
			"Szablon QWeb faktury, do którego zostanie "
			"doklejona sekcja QR KSeF."
		)
	)
	
	# Pole pomocnicze do przechowywania nazwy raportu
	qr_report_name = fields.Char(
		string="Nazwa raportu",
		compute="_compute_qr_report_name",
		store=True
	)
	
	@api.depends('qr_report_template_id')
	def _compute_qr_report_name(self):
		for record in self:
			if record.qr_report_template_id:
				# Pobierz nazwę szablonu z ir.ui.view
				record.qr_report_name = record.qr_report_template_id.key
			else:
				record.qr_report_name = False
	
	@api.onchange('qr_report_template_id')
	def _onchange_qr_report_template_id(self):
		if self.qr_report_template_id:
			# Sprawdź, czy szablon istnieje w ir.actions.report
			report = self.env['ir.actions.report'].search([
				('report_name', '=', self.qr_report_template_id.key),
				('company_id', '=', self.company_id.id),
			], limit=1)
			
			if not report:
				raise ValidationError(
					_("Szablon musi być powiązany z istniejącym raportem PDF. "
					  "Najpierw utwórz raport w menu Raporty.")
				)


#################################################################################
# EOF

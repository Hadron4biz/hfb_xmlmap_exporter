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
""" @version 16.1.2
	@owner  Hadron for Business
	@author andrzej wiśniewski warp3r
	@date   2025.10.15
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import re
from odoo import release
import io
import uuid
from lxml import etree

import logging
_logger = logging.getLogger(__name__)

class XmlValidationLog(models.Model):
	_name = "xml.validation.log"
	_description = "Raport walidacji XSD dokumentu"
	_order = "create_date desc"

	move_id = fields.Many2one("account.move", string="Faktura", ondelete="cascade", index=True)
	template_id = fields.Many2one("xml.export.template", string="Szablon", ondelete="set null")
	validation_date = fields.Datetime(string="Data walidacji", default=fields.Datetime.now)
	user_id = fields.Many2one("res.users", string="Użytkownik", default=lambda self: self.env.user)
	state = fields.Selection([
		("valid", "Poprawny"),
		("invalid", "Błędy"),
		("error", "Błąd przetwarzania"),
	], string="Wynik", default="error")
	error_log = fields.Text(string="Szczegóły błędów")
	xml_snapshot = fields.Binary(string="Zrzut XML")

	@api.model
	def create(self, vals):
		# wymuszenie automatycznej daty i użytkownika
		vals.setdefault("validation_date", fields.Datetime.now())
		vals.setdefault("user_id", self.env.uid)
		return super().create(vals)

	#def write(self, vals):
	#	raise UserError(_("Nie można edytować wpisu historii walidacji."))

	# Pole obliczeniowe do wyświetlania
	formatted_errors = fields.Html(
		string="Sformatowane błędy",
		compute="_compute_formatted_errors",
		store=False
	)
	
	def _compute_formatted_errors(self):
		for record in self:
			if not record.error_log:
				record.formatted_errors = "<p>Brak błędów</p>"
				continue
			
			errors = record.error_log.split('\n')
			html_errors = []
			
			for error in errors[:20]:  # Ogranicz do 20 błędów
				if error.strip():
					# Formatuj błąd
					html_error = f"""
					<div style="margin-bottom: 10px; padding: 10px; border-left: 4px solid #dc3545; background-color: #f8f9fa;">
						<div style="font-weight: bold; color: #dc3545;">{escape(error[:100])}</div>
					</div>
					"""
					html_errors.append(html_error)
			
			if not html_errors:
				record.formatted_errors = "<p>Brak błędów</p>"
			else:
				record.formatted_errors = Markup("".join(html_errors))


#EoF

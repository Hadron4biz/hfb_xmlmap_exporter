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
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

class XmlTemplateXsdUploadWizard(models.TransientModel):
	_name = "xml.template.xsd.upload.wizard"
	_description = "Wgraj schemę XSD i podepnij do szablonu"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=False,  # <-- opcjonalne
		default=lambda self: self.env.company,
		ondelete='set null'
	)

	template_id = fields.Many2one(
		"xml.export.template",
		required=True,
		ondelete="cascade",
		string="Szablon"
	)
	xsd_file = fields.Binary(string="Plik XSD", required=True)
	xsd_filename = fields.Char(string="Nazwa pliku", required=True)

	def action_apply(self):
		self.ensure_one()
		if not self.xsd_file or not self.xsd_filename:
			raise ValidationError(_("Wskaż plik XSD."))

		# Utwórz attachment
		attachment = self.env["ir.attachment"].with_company( self.company_id).create({
			'company_id': self.company_id.id,
			"name": self.xsd_filename,
			"datas": self.xsd_file,
			"res_model": "xml.export.template",
			"res_id": self.template_id.id,
			"mimetype": "application/xml",
		})

		# Podłącz do szablonu
		self.template_id._set_xsd_attachment(attachment)

		# Wróć do formularza szablonu
		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.export.template",
			"res_id": self.template_id.id,
			"view_mode": "form",
			"target": "current",
		}

#EoF

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

class XmlTemplateXsdUploadWizard(models.TransientModel):
    _name = "xml.template.xsd.upload.wizard"
    _description = "Wgraj schemę XSD i podepnij do szablonu"

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
        attachment = self.env["ir.attachment"].create({
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

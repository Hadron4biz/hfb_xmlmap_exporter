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
import json
import base64
import re
import logging
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import uuid
from markupsafe import Markup
from uuid import uuid4

_logger = logging.getLogger(__name__)

def safe_int(pattern):
	try:
		return int(pattern)
	except Exception:
		return 0

# ADD: regex walidujący format nazwy
_NAME_RE = re.compile(
	r"^odoo-\d+(?:\.\d+)?-[a-z0-9_]+-[a-z0-9._]+-[a-z][a-z0-9_]*-\d+\.\d+\.\d+$"
)
_XPATH_RE = re.compile(r"^/[^\s]*$")


class XmlExportTemplate(models.Model):
	_inherit = "xml.export.template"

	json_attachment_id = fields.Many2one(
		"ir.attachment",
		string="Plik szablonu JSON",
		help="Plik JSON eksportowany z innej instancji lub środowiska Odoo (XET)."
	)

	provider_id = fields.Many2one(
		"communication.provider",
		string="Provider",
		help="Dostawca lub kanał eksportu danych (np. KSeF, PEPPOL, LocalDir)."
	)

	def action_import_template_json(self):
		self.ensure_one()

		# --- Wczytanie JSON ---
		if not (self.json_attachment_id and self.json_attachment_id.datas):
			raise UserError("Brak załączonego pliku JSON.")

		json_bytes = base64.b64decode(self.json_attachment_id.datas)
		json_data = json.loads(json_bytes)

		tpl = json_data.get("template", json_data)
		nodes = json_data.get("nodes", [])

		# --- CREATE lub UPDATE po UUID ---
		existing = self.env["xml.export.template"].search([
			("uuid", "=", tpl.get("uuid"))
		], limit=1)

		if existing:
			existing.node_ids.unlink()
			target_template = existing
			target_template.write({
				"name": tpl.get("name"),
				"description": tpl.get("description"),
				"namespace": tpl.get("namespace"),
				"schema_location": tpl.get("schema_location"),
				"state": "imported",
			})
		else:
			model_id = self.env["ir.model"].search(
				[("model", "=", tpl.get("model", "account.move"))], limit=1
			)

			target_template = self.env["xml.export.template"].create({
				"uuid": tpl.get("uuid"),
				"name": tpl.get("name"),
				"description": tpl.get("description"),
				"namespace": tpl.get("namespace"),
				"schema_location": tpl.get("schema_location"),
				"model_id": model_id.id,
				"state": "imported",
				'company_id': self.company_id.id,
			})

		# ===========================================
		#   IMPORT WĘZŁÓW (ROOT → CHILDREN)
		# ===========================================

		IrModel = self.env['ir.model']
		IrField = self.env['ir.model.fields']

		def _import_node(node_data, parent_id=None):

			# src_model_id
			src_model_id = False
			src_model_name = node_data.get("src_model")
			if src_model_name:
				model_rec = IrModel.search([('model', '=', src_model_name)], limit=1)
				src_model_id = model_rec.id if model_rec else False

			# src_field_id
			src_field_id = False
			src_field_name = node_data.get("src_field")
			if src_field_name and src_model_id:
				field_rec = IrField.search([
					('model_id', '=', src_model_id),
					('name', '=', src_field_name)
				], limit=1)
				src_field_id = field_rec.id if field_rec else False

			node_vals = {
				"template_id": target_template.id,
				"parent_id": parent_id,
				"uuid": node_data.get("uuid"),
				"tag": node_data.get("tag"),
				"name": node_data.get("name") or node_data.get("tag"),
				"node_kind": node_data.get("node_kind", "element"),
				"value_source": node_data.get("value_source", "none"),
				"value_constant": node_data.get("value_constant"),
				"value_expr": node_data.get("value_expr"),
				"src_model_id": src_model_id,
				"src_field_id": src_field_id,
				"src_rel_path": node_data.get("src_rel_path"),
				"sequence": int(node_data.get("sequence") or 0),
				"export_if_empty": bool(node_data.get("export_if_empty")),
				"condition_expr": node_data.get("condition_expr"),
				"loop_mode": node_data.get("loop_mode") or "none",
				"loop_limit": node_data.get("loop_limit"),
				"xsd_type_name": node_data.get("xsd_type_name"),
				"xsd_min_occurs": int(node_data.get("xsd_min_occurs", 1)),
				"xsd_max_occurs": int(node_data.get("xsd_max_occurs", 1)),
				"xsd_nillable": bool(node_data.get("xsd_nillable")),
				'company_id': self.company_id.id,
			}

			new_node = self.env["xml.export.node"].create(node_vals)

			for child in node_data.get("children", []):
				_import_node(child, parent_id=new_node.id)

			return new_node

		# TU JEST KLUCZ:
		# --- START IMPORTU ---
		for root_node in nodes:
			_import_node(root_node, parent_id=None)

		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.export.template",
			"res_id": target_template.id,
			"view_mode": "form",
			"target": "current",
		}


#EoF

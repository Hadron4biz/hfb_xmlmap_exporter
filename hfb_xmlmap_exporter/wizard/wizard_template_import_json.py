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
from odoo import release
import io
import uuid
import base64
import re
from lxml import etree
import json
from markupsafe import Markup, escape
import logging
_logger = logging.getLogger(__name__)

class XmlTemplateImportJsonWizard(models.TransientModel):
	_name = "xml.template.import_json.wizard"
	_description = "Import JSON Template 2.0 → XML Template"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=False,  # <-- opcjonalne
		default=lambda self: self.env.company,
		ondelete='set null'
	)

	json_file = fields.Binary("Plik JSON")
	json_filename = fields.Char("Nazwa JSON")
	filename = fields.Char(related="json_filename")

	# ============================================================
	#  POMOCNICZE FUNKCJE
	# ============================================================
	def resolve_xsd_type(self, template, type_name):
		"""
		Znajdź xml.xsd.type po nazwie dla danego szablonu.
		Zwraca rekord lub False.
		"""
		if not type_name:
			return False

		XType = self.env["xml.xsd.type"]
		xsd_type = XType.search([
			("template_id", "=", template.id),
			("name", "=", type_name),
		], limit=1)

		return xsd_type or False

	def resolve_model(self, model_name):
		"""Znajdź ir.model po nazwie modelu."""
		IrModel = self.env["ir.model"]
		if not model_name:
			return False
		model = IrModel.search([('model', '=', model_name)], limit=1)
		if not model:
			_logger.warning(f"Nie znaleziono modelu: {model_name}")
			return False
		return model.id

	def resolve_field(self, model_id, field_name):
		"""Znajdź ir.model.fields po modelu i nazwie pola."""
		IrField = self.env["ir.model.fields"]
		if not model_id or not field_name:
			return False
		field = IrField.search([
			('model_id', '=', model_id),
			('name', '=', field_name)
		], limit=1)
		if not field:
			_logger.warning(f"Nie znaleziono pola {field_name} dla modelu ID {model_id}")
			return False
		return field.id

	def _build_xpath_to_parent_map(self, json_nodes):
		"""Buduje mapowanie xpath -> parent_xpath z JSON."""
		xpath_map = {}
		
		def process_node(node, parent_xpath=""):
			"""Rekurencyjnie przetwarza node'y i buduje mapę xpath."""
			# Pobierz xpath z JSON lub zbuduj z parent_xpath + tag
			tag = node.get('tag') or node.get('name') or 'unknown'  # ✅ NAJPIERW tag
			xpath = node.get('xpath')
			if not xpath:
				tag = node.get('tag') or node.get('name')
				xpath = f"{parent_xpath}/{tag}" if parent_xpath else tag
			
			# Zapisz w mapie
			xpath_map[xpath] = {
				'node': node,
				'parent_xpath': parent_xpath,
				'tag': tag,
			}
			
			# Przetwórz dzieci
			for child in node.get('children', []):
				process_node(child, xpath)
		
		# Przetwórz wszystkie root nodes
		for root in json_nodes:
			process_node(root, "")
		
		return xpath_map

	# =====================================================================
	#  POPRAWIONY IMPORTER - UŻYWA XPATH JAKO KLUCZA
	# =====================================================================
	def action_import_json(self):
		"""
		POPRAWIONY IMPORTER JSON - używa XPATH do poprawnego odtwarzania hierarchii
		"""
		if not self.json_file:
			raise UserError("Brak pliku JSON.")

		chatter = []

		# ============================================================
		# 1. Dekodowanie JSON
		# ============================================================
		try:
			raw = base64.b64decode(self.json_file)
			data = json.loads(raw)
		except Exception as e:
			raise UserError(f"Błąd dekodowania JSON: {e}")

		tpl = data.get("template")
		if not tpl:
			raise UserError("Brak sekcji 'template'.")

		Template = self.env["xml.export.template"]
		Namespace = self.env["xml.export.namespace"]
		XType = self.env["xml.xsd.type"]
		XElement = self.env["xml.xsd.element"]
		Node = self.env["xml.export.node"]

		# ============================================================
		# 2. Tworzenie szablonu
		# ============================================================
		template = Template.create({
			"name": tpl.get("name"),
			"description": tpl.get("description"),
			"version": tpl.get("version"),
			"root_tag": tpl.get("root_tag"),
			"namespace": tpl.get("namespace"),
			"xml_encoding": tpl.get("xml_encoding") or "UTF-8",
			"ns_prefix": tpl.get("ns_prefix"),
			"doc_direction": tpl.get("doc_direction"),
			"model_id": self.resolve_model(tpl.get("model")),
			"include_xsi": tpl.get("include_xsi", False),
			"xsd_target_namespace": tpl.get("xsd_target_namespace"),
			"xsd_version": tpl.get("xsd_version"),
			"xsd_summary": tpl.get("xsd_summary"),
			"include_xml_declaration": tpl.get("include_xml_declaration", True),
			"pretty_print": tpl.get("pretty_print", True),
			"schema_location": tpl.get("schema_location"),
			"validate_on_export": tpl.get("validate_on_export", False),
			"active": tpl.get("active", True),
			"state": "draft",
		})
		chatter.append(f"Utworzono szablon: {template.name}")

		# ============================================================
		# 3. Odtworzenie XSD
		# ============================================================
		if tpl.get("schema_b64") and tpl.get("schema_filename"):
			att = self.env["ir.attachment"].with_company( template.company_id).create({
				'company_id': template.company_id.id,
				"name": tpl["schema_filename"],
				"type": "binary",
				"datas": tpl["schema_b64"],
				"res_model": "xml.export.template",
				"res_id": template.id,
			})
			template.xsd_attachment_id = att.id
			chatter.append(f"Załączono schemę XSD: {tpl['schema_filename']}")

		# ============================================================
		# 4. Import namespace'ów
		# ============================================================
		for ns in data.get("namespaces", []):
			Namespace.create({
				"template_id": template.id,
				"prefix": ns.get("prefix"),
				"uri": ns.get("uri"),
				"sequence": ns.get("sequence") or 10,
			})
		chatter.append(f"Odtworzono {len(data.get('namespaces', []))} namespace'ów.")

		# ============================================================
		# 5. Import typów XSD
		# ============================================================
		xsd_map = {}
		xsd_types = data.get("xsd_types", [])

		for t in xsd_types:
			rec = XType.create({
				"template_id": template.id,
				"name": t.get("name"),
				"category": t.get("category"),
				"base_type": t.get("base_type"),
				"pattern": t.get("pattern"),
				"min_length": t.get("min_length"),
				"max_length": t.get("max_length"),
				"enumeration": json.dumps(t.get("enumeration")) if t.get("enumeration") else None,
				"documentation": t.get("documentation"),
			})
			xsd_map[t["name"]] = rec

		# Elementy typów
		for t in xsd_types:
			parent = xsd_map.get(t["name"])
			if not parent:
				continue
			for el in t.get("elements", []):
				XElement.create({
					"type_id": parent.id,
					"name": el.get("name"),
					"type": el.get("type"),
					"min_occurs": el.get("min_occurs"),
					"max_occurs": el.get("max_occurs"),
					"is_attribute": el.get("is_attribute"),
				})

		chatter.append(f"Odtworzono {len(xsd_types)} typów XSD.")

		# ============================================================
		# 6. BUDOWANIE MAPY XPATH Z JSON
		# ============================================================
		json_nodes = data.get("nodes", [])
		xpath_map = self._build_xpath_to_parent_map(json_nodes)
		_logger.info(f"Zbudowano mapę xpath dla {len(xpath_map)} node'ów")

		# ============================================================
		# 7. TWORZENIE NODE'ÓW W PRAWDZIWEJ KOLEJNOŚCI (od root do liści)
		# ============================================================
		node_by_xpath = {}  # xpath -> created node record
		created_nodes = []  # lista utworzonych node'ów w kolejności
		
		# Sortuj xpath po głębokości (najpierw root, potem dzieci)
		sorted_xpaths = sorted(
			xpath_map.keys(),
			key=lambda x: x.count('/')  # mniej / = wyższy w hierarchii
		)
		
		for xpath in sorted_xpaths:
			node_data = xpath_map[xpath]
			json_node = node_data['node']
			parent_xpath = node_data['parent_xpath']
			
			# Znajdź parent_id
			parent_id = False
			if parent_xpath:
				parent_node = node_by_xpath.get(parent_xpath)
				if parent_node:
					parent_id = parent_node.id
				else:
					_logger.warning(f"Nie znaleziono parenta dla xpath: {xpath}, parent_xpath: {parent_xpath}")
			
			# Rozwiąż relacje Many2one
			src_model_id = False
			src_field_id = False
			loop_model_id = False
			loop_rel_field_id = False
			
			# Rozwiąż src_model i src_field
			src_model_name = json_node.get("src_model")
			src_field_name = json_node.get("src_field")
			
			if src_model_name:
				src_model_id = self.resolve_model(src_model_name)
				if src_field_name and src_model_id:
					src_field_id = self.resolve_field(src_model_id, src_field_name)
			
			# Rozwiąż loop_model i loop_rel_field
			loop_model_name = json_node.get("loop_model")
			loop_rel_field_name = json_node.get("loop_rel_field")
			
			if loop_model_name:
				loop_model_id = self.resolve_model(loop_model_name)
				if loop_rel_field_name and loop_model_id:
					loop_rel_field_id = self.resolve_field(loop_model_id, loop_rel_field_name)
			
			# Rozwiąż type_id
			xname = json_node.get("xsd_type_name")
			type_id = xsd_map.get(xname).id if xname in xsd_map else False

			xname = json_node.get("xsd_type_name")
			type_id = False
			if xname:
				xsd_type = xsd_map.get(xname)
				if xsd_type:
					type_id = xsd_type.id
				else:
					chatter.append(
						f"Ostrzeżenie: Nie znaleziono typu XSD '{xname}' "
						f"dla węzła '{json_node.get('name')}'."
					)
			
			# Utwórz node
			node = Node.create({
				"template_id": template.id,
				"name": json_node.get("tag") or json_node.get("name"),
				"xpath": xpath,  # ZACHOWUJEMY ORYGINALNY XPATH
				"sequence": json_node.get("sequence", 10),
				"node_kind": json_node.get("node_kind", "element"),
				"parent_id": parent_id,
				
				# XSD metadata
				#"xsd_type_name": xname or False,
				"xsd_type_kind": json_node.get("xsd_type_kind"),
				"type_id": type_id,
				"xsd_min_occurs": json_node.get("xsd_min_occurs"),
				"xsd_max_occurs": json_node.get("xsd_max_occurs"),
				"xsd_nillable": json_node.get("xsd_nillable"),
				"xsd_default": json_node.get("xsd_default"),
				"xsd_fixed": json_node.get("xsd_fixed"),
				"xsd_enumeration": json_node.get("xsd_enumeration"),
				
				# Źródło wartości
				"value_source": json_node.get("value_source", "none"),
				"value_constant": json_node.get("value_constant"),
				"value_literal": json_node.get("value_literal"),
				"value_expr": json_node.get("value_expr"),
				"value_fixed": json_node.get("value_fixed"),
				"src_rel_path": json_node.get("src_rel_path"),
				
				# Relacje Many2one
				"src_model_id": src_model_id,
				"src_field_id": src_field_id,
				"src_field_type": json_node.get("src_field_type"),
				
				# Pętle
				"loop_mode": json_node.get("loop_mode", "none"),
				"loop_model_id": loop_model_id,
				"loop_rel_field_id": loop_rel_field_id,
				"loop_domain": json_node.get("loop_domain"),
				"loop_order": json_node.get("loop_order"),
				"loop_limit": json_node.get("loop_limit"),
				
				# Emisja i formatowanie
				"emit_empty": json_node.get("emit_empty", "if-required"),
				"zero_policy": json_node.get("zero_policy", "emit"),
				"as_cdata": json_node.get("as_cdata", False),
				"required_flag": json_node.get("required_flag", False),
				"condition_expr": json_node.get("condition_expr"),
				
				# Formatowanie
				"fmt_date": json_node.get("fmt_date"),
				"fmt_datetime": json_node.get("fmt_datetime"),
				"fmt_bool_true": json_node.get("fmt_bool_true"),
				"fmt_bool_false": json_node.get("fmt_bool_false"),
				"fmt_decimal_precision": json_node.get("fmt_decimal_precision"),
				"fmt_strip": json_node.get("fmt_strip", True),
				"fmt_upper": json_node.get("fmt_upper", False),
				"fmt_lower": json_node.get("fmt_lower", False),
				"fmt_pad_left": json_node.get("fmt_pad_left"),
				"fmt_pad_char": json_node.get("fmt_pad_char", "0"),
				
				# Notatki
				"notes": json_node.get("notes"),
				
				# UUID
				"uuid": json_node.get("uuid"),
			})
			
			# Zapisz w mapach
			node_by_xpath[xpath] = node
			created_nodes.append(node)
		
		# ============================================================
		# 8. AUTOMATYCZNE PORZĄDKOWANIE SEKWENCJI WEDŁUG XSD
		# ============================================================
		try:
			# Teraz zawsze wywołujemy auto_sequence_nodes() - ona sama wybiera metodę
			template.auto_sequence_nodes()
			chatter.append("🔧 Automatycznie uporządkowano sekwencje węzłów")
			
		except Exception as e:
			_logger.error(f"Błąd podczas porządkowania sekwencji: {e}")
			chatter.append(f"⚠️  Błąd sortowania: {str(e)[:100]}")
		
		# ============================================================
		# 9. Ustaw template_model_id
		# ============================================================
		model_name = tpl.get("model")
		if model_name:
			main_model_id = self.resolve_model(model_name)
			if main_model_id:
				template.model_id = main_model_id
				for node in template.node_ids:
					if not node.template_model_id:
						node.template_model_id = main_model_id

		# ============================================================
		# 10. SPRAWDŹ POPRAWNOŚĆ
		# ============================================================
		node_count = len(template.node_ids)
		chatter.append(f"Odtworzono {node_count} node'ów XML.")
		
		# Sprawdź czy są duplikaty xpath
		xpaths = [n.xpath for n in template.node_ids if n.xpath]
		unique_xpaths = set(xpaths)
		if len(xpaths) != len(unique_xpaths):
			duplicates = [x for x in xpaths if xpaths.count(x) > 1]
			chatter.append(f"⚠️  Znaleziono duplikaty xpath: {set(duplicates)}")
		
		# Sprawdź brakujące parenty
		missing_parents = template.node_ids.filtered(
			lambda n: n.parent_id and n.parent_id.id not in template.node_ids.ids
		)
		if missing_parents:
			chatter.append(f"⚠️  {len(missing_parents)} node'ów ma brakujących parentów")
		
		# Sprawdź loop_mode bez model_id
		missing_loop_models = template.node_ids.filtered(
			lambda n: n.loop_mode != "none" and not n.loop_model_id
		)
		if missing_loop_models:
			chatter.append(f"⚠️  {len(missing_loop_models)} node'ów ma brakujące loop_model_id")

		# ============================================================
		# 11. CHATTER I POWRÓT
		# ============================================================
		template.message_post(body="<br/>".join(chatter))

		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.export.template",
			"view_mode": "form",
			"res_id": template.id,
			"target": "current",
		}

#EoF

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
import json
import base64
import re
import logging
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import uuid
from markupsafe import Markup

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

class XmlTemplateExporter(models.AbstractModel):
	_name = "xml.template.exporter"
	_description = "Exporter: XML Template → JSON 2.0"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	# =================================================================
	#  PUBLICZNA METODA EKSPORTU
	# =================================================================
	def export_template_json(self, template):
		"""
		Eksportuje kompletny szablon XML do JSON 2.0 (pełna struktura).
		"""
		#self.ensure_one()

		data = {
			"template": self._export_template_metadata(template),
			"namespaces": self._export_namespaces(template),
			"xsd_types": self._export_xsd_types(template),
			"nodes": self._export_nodes_tree(template),
		}

		return json.dumps(data, indent=2, ensure_ascii=False)

	# =================================================================
	#  TEMPLATE METADATA
	# =================================================================
	def _export_template_metadata(self, template):
		res = {
			# Identyfikacja
			"uuid": template.uuid,
			"name": template.name,
			"description": template.description,
			"version": template.version,
			"state": template.state,
			"doc_direction": template.doc_direction,
			
			# Model źródłowy
			"model": template.model_id.model if template.model_id else None,
			"model_name": template.model_id.name if template.model_id else None,
			
			# Root XML + namespace
			"root_tag": template.root_tag,
			"namespace": template.namespace,
			"ns_prefix": template.ns_prefix,
			"xml_namespace": template.xml_namespace,  # alias
			
			# XSD info
			"xsd_target_namespace": template.xsd_target_namespace,
			"xsd_version": template.xsd_version,
			"xsd_summary": template.xsd_summary,
			
			# Ustawienia XML
			"encoding": template.encoding,  # alias
			"xml_encoding": template.xml_encoding,
			"include_xml_declaration": template.include_xml_declaration,
			"pretty_print": template.pretty_print,
			"include_xsi": template.include_xsi,
			"schema_location": template.schema_location,
			"validate_on_export": template.validate_on_export,
			
			# Status
			"active": template.active,
		}

		# Główny schema w base64
		if template.xsd_attachment_id:
			raw = template.xsd_attachment_id.datas
			if isinstance(raw, bytes):
				raw = raw.decode("ascii")
			res["schema_b64"] = raw
			res["schema_filename"] = template.xsd_attachment_id.name
		else:
			res["schema_b64"] = None
			res["schema_filename"] = None

		# Dodatkowe XSD attachments - DODAJ TO!
		res["xsd_type_attachments"] = []
		for att in template.xsd_type_attachment_ids:
			raw = att.datas
			if isinstance(raw, bytes):
				raw = raw.decode("ascii")
			res["xsd_type_attachments"].append({
				"filename": att.name,
				"data": raw,
				"mimetype": att.mimetype or "application/xml",
			})

		return res

	# =================================================================
	#  NAMESPACE’Y
	# =================================================================
	def _export_namespaces(self, template):
		return [
			{
				"prefix": ns.prefix,
				"uri": ns.uri,
				"sequence": ns.sequence,
				"is_default": ns.is_default,
			}
			for ns in template.namespace_ids
		]

	# =================================================================
	#  XSD TYPES
	# =================================================================
	def _export_xsd_types(self, template):
		"""
		Eksportuje pełne dane typów XSD wraz z elementami.
		"""
		xsd_types = self.env["xml.xsd.type"].search([
			("template_id", "=", template.id)
		])

		result = []
		for t in xsd_types:
			# Finałowa walidacja enumeracji (odpowiednik SQL REPLACE)
			enum_val = None
			if t.enumeration:
				fixed = t.enumeration.replace("'", '"')   # dokładnie to robi Twój SQL
				try:
					enum_val = json.loads(fixed)		  # udana konwersja → poprawna lista
				except Exception:
					enum_val = fixed					  # nieudana → eksportuj raw string

			entry = {
				"name": t.name,
				"category": t.category,
				"base_type": t.base_type,
				"pattern": t.pattern,
				"min_length": t.min_length,
				"max_length": t.max_length,
				#"enumeration": json.loads(t.enumeration) if t.enumeration else None,
				"enumeration": enum_val,
				"documentation": t.documentation,
				"elements": [],
			}

			# ELEMENTY ZAGNIEŻDŻONE
			for el in t.element_ids:
				entry["elements"].append({
					"name": el.name,
					"type": el.type,
					"min_occurs": el.min_occurs,
					"max_occurs": el.max_occurs,
					"is_attribute": el.is_attribute,
				})

			result.append(entry)

		return result

	# =================================================================
	#  DRZEWO NODE’ÓW
	# =================================================================
	def _export_nodes_tree(self, template):
		# Kolejność według XSD dla KSeF FA(3)
		XSD_ORDER = ['Naglowek', 'Podmiot1', 'Podmiot2', 'Fa']

		roots = self.env["xml.export.node"].search([
			("template_id", "=", template.id),
			("parent_id", "=", False)
		], order="sequence")

		# Posortuj według XSD
		def get_sort_key(node):
			try:
				return XSD_ORDER.index(node.name)
			except ValueError:
				return len(XSD_ORDER)
		
		sorted_roots = sorted(roots, key=get_sort_key)

		def export_node(node):
			# Jeśli loop_mode jest ustawiony, ale loop_model_id jest pusty, użyj src_model
			loop_model = None
			if node.loop_mode not in [None, "none"]:
				if node.loop_model_id:
					loop_model = node.loop_model_id.model
				elif node.src_model_id:  # ✅ DODAJ FALLBACK
					loop_model = node.src_model_id.model
					_logger.info(f"⚠️  Eksport: Używam src_model jako loop_model dla {node.name}")

			data = {
				# Podstawowe dane
				"uuid": node.uuid,
				"tag": node.name,
				"sequence": node.sequence,
				"node_kind": node.node_kind,
				"ns_prefix": node.ns_prefix,
				"namespace_uri": node.namespace_uri,
				"state": node.state,
				"parent_uuid": node.parent_id.uuid if node.parent_id else None,
				"xpath": node.xpath,
				
				# XSD metadata - KOMPLETNE
				"xsd_type_name": node.xsd_type_name,
				"xsd_type_kind": node.xsd_type_kind,
				"xsd_min_occurs": node.xsd_min_occurs,
				"xsd_max_occurs": node.xsd_max_occurs,
				"xsd_nillable": node.xsd_nillable,
				"xsd_default": node.xsd_default,
				"xsd_fixed": node.xsd_fixed,
				"xsd_enumeration": node.xsd_enumeration,
				
				# Emisja/wartości
				"emit_empty": node.emit_empty,
				"export_if_empty": node.export_if_empty,  # alias dla kompatybilności
				"zero_policy": node.zero_policy,
				"as_cdata": node.as_cdata,
				
				# Źródło wartości - KOMPLETNE
				"value_source": node.value_source,
				"value_constant": node.value_constant,
				"value_literal": node.value_literal,
				"value_expr": node.value_expr,
				"value_fixed": node.value_fixed,
				
				# Mapping do modeli - KOMPLETNE
				"src_model": node.src_model_id.model if node.src_model_id else None,
				"src_field": node.src_field_id.name if node.src_field_id else None,
				"src_field_type": node.src_field_type,
				"src_rel_path": node.src_rel_path,
				
				# Formatowanie
				"fmt_date": node.fmt_date,
				"fmt_datetime": node.fmt_datetime,
				"fmt_bool_true": node.fmt_bool_true,
				"fmt_bool_false": node.fmt_bool_false,
				"fmt_upper": node.fmt_upper,
				"fmt_lower": node.fmt_lower,
				"fmt_strip": node.fmt_strip,
				"fmt_decimal_precision": node.fmt_decimal_precision,
				"fmt_pad_left": node.fmt_pad_left,
				"fmt_pad_char": node.fmt_pad_char,
				
				# Pętle
				"loop_mode": node.loop_mode,
				"loop_domain": node.loop_domain,
				"loop_order": node.loop_order,
				"loop_limit": node.loop_limit,
				"loop_model": loop_model, 
				"loop_rel_field": node.loop_rel_field_id.name if node.loop_rel_field_id else None,
				
				# Warunki
				"condition_expr": node.condition_expr,
				"required_flag": node.required_flag,
				
				# Notatki
				"notes": node.notes,
				
				# children rekurencyjnie
				"children": []
			}

			# dzieci
			for child in self.env["xml.export.node"].search([
				("parent_id", "=", node.id),
				('company_id', '=', node.company_id.id),
			], order="sequence"):
				data["children"].append(export_node(child))

			return data

		return [export_node(r) for r in sorted_roots]

class XmlExportTemplate(models.Model):
	_inherit = "xml.export.template"

	def action_export_json(self):
		self.ensure_one()

		# ✅ ZABEZPIECZENIE 1: Sprawdź czy rekord należy do bieżącej firmy
		if self.company_id and self.company_id != self.env.company:
			raise UserError(_("You can only export templates from your own company."))

		json_str = self.env["xml.template.exporter"].export_template_json(self)

		json_b64 = base64.b64encode(json_str.encode("utf-8"))
		filename = f"{(self.name or 'template').replace(' ', '_')}.xet.json"

		attachment = self.env['ir.attachment'].with_company( self.company_id).create({
			'name': filename,
			'datas': json_b64,
			'res_model': 'xml.export.template',
			'res_id': self.id,
			'mimetype': 'application/json',
			'company_id': self.company_id.id,
		})

		self.message_post(
			body=f"📤 Eksport JSON zapisany jako załącznik <b>{filename}</b>",
			attachment_ids=[attachment.id],
			subtype_xmlid="mail.mt_note",
		)

		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.export.template",
			"res_id": self.id,
			"view_mode": "form",
			"target": "current",
		}


	def action_validate_template_full(self):
		"""
		Pełna walidacja struktury szablonu + aktualizacja state na node'ach.
		Uwzględnia rzeczywisty model używany w Twojej implementacji.
		"""
		self.ensure_one()
		
		errors = []
		warnings = []
		node_issues = {}
		
		# ------------------------------------------------------------
		# RESET state wszystkich node'ów
		# ------------------------------------------------------------
		for node in self.node_ids:
			node.state = "draft"
		
		# ------------------------------------------------------------
		# WALIDACJA GŁÓWNYCH USTAWIEŃ
		# ------------------------------------------------------------
		if not self.name:
			errors.append("Brak nazwy szablonu.")
		
		if not self.root_tag:
			warnings.append("Brak wartości root_tag.")
		
		if not self.namespace:
			warnings.append("Brak głównej przestrzeni nazw.")
		
		# ------------------------------------------------------------
		# WALIDACJA STRUKTURY DRZEWA
		# ------------------------------------------------------------
		# Sprawdź czy jest root node
		root_nodes = self.node_ids.filtered(lambda n: not n.parent_id)
		if not root_nodes:
			errors.append("Brak węzła głównego (root node).")
		elif len(root_nodes) > 1:
			warnings.append(f"Znaleziono {len(root_nodes)} root nodes, powinien być jeden.")
		
		# ------------------------------------------------------------
		# WALIDACJA POSZCZEGÓLNYCH NODE'ÓW
		# ------------------------------------------------------------
		for node in self.node_ids:
			node_errors = []
			node_warnings = []

			### XXX ToDo: weryfikacja występowania i zgodności w XSD

			
			# 1) Sprawdź źródło wartości
			if node.value_source == "field":
				if not node.src_rel_path:
					node_errors.append("Brak src_rel_path dla źródła 'field'")
				else:
					# Sprawdź czy ścieżka nie jest pusta
					if node.src_rel_path.strip() == "":
						node_errors.append("Pusty src_rel_path")
			
			elif node.value_source == "constant":
				if not node.value_constant:
					node_warnings.append("Pusta wartość constant")
			
			elif node.value_source == "expression":
				if not node.value_expr:
					node_errors.append("Brak expression dla źródła 'expression'")
			
			# 2) Sprawdź konfigurację pętli
			if node.loop_mode != "none":
				if node.loop_mode in ["one2many", "many2many"]:
					if not node.loop_rel_field_id:
						node_errors.append(f"Brak loop_rel_field_id dla pętli {node.loop_mode}")
				elif node.loop_mode == "domain":
					if not node.loop_model_id:
						node_errors.append("Brak loop_model_id dla pętli domain")
					if not node.loop_domain:
						node_warnings.append("Brak loop_domain dla pętli domain")
			
			# 3) Sprawdź czy node ma tag/name
			if not node.name or node.name.strip() == "":
				node_errors.append("Brak nazwy (tag) node'a")
			
			# Zapisz problemy dla tego node'a
			if node_errors or node_warnings:
				node_issues[node.id] = {
					'node': node,
					'errors': node_errors,
					'warnings': node_warnings
				}
			
			# Ustaw stan node'a
			if node_errors:
				node.state = "error"
				errors.extend([f"{node.name}: {e}" for e in node_errors])
			elif node_warnings:
				node.state = "warning"
				warnings.extend([f"{node.name}: {w}" for w in node_warnings])
			else:
				node.state = "validated"
		
		# ------------------------------------------------------------
		# DODATKOWA WALIDACJA: Sprawdź czy można wygenerować XML
		# ------------------------------------------------------------
		try:
			# Spróbuj wygenerować przykładowy XML z testowym rekordem
			test_model = self.env['account.move']
			test_record = test_model.search([], limit=1)
			
			if test_record:
				try:
					xml_bytes = self.generate_xml(test_record, in_memory=True)
					_logger.info(f"✅ Testowe generowanie XML udane ({len(xml_bytes)} bajtów)")
				except Exception as e:
					errors.append(f"Błąd podczas testowego generowania XML: {str(e)}")
		except Exception as e:
			warnings.append(f"Nie udało się przeprowadzić testu generowania XML: {str(e)}")
		
		# ------------------------------------------------------------
		# BUDOWANIE RAPORTU
		# ------------------------------------------------------------
		from markupsafe import Markup
		
		html = "<b>Raport pełnej walidacji szablonu XML</b><br><br>"
		
		# Podsumowanie
		validated_nodes = len(self.node_ids.filtered(lambda n: n.state == 'validated'))
		error_nodes = len(self.node_ids.filtered(lambda n: n.state == 'error'))
		warning_nodes = len(self.node_ids.filtered(lambda n: n.state == 'warning'))
		
		html += f"""
		<b>📊 Podsumowanie:</b><br>
		• Węzły poprawne: {validated_nodes}<br>
		• Węzły z błędami: {error_nodes}<br>
		• Węzły z ostrzeżeniami: {warning_nodes}<br>
		• Łącznie węzłów: {len(self.node_ids)}<br><br>
		"""
		
		if errors:
			html += "<b style='color:red;'>❌ Błędy krytyczne:</b><br>"
			for error in errors[:20]:  # Ogranicz do 20 błędów
				html += f"- {error}<br>"
			if len(errors) > 20:
				html += f"... i jeszcze {len(errors) - 20} błędów<br>"
			html += "<br>"
		
		if warnings:
			html += "<b style='color:orange;'>⚠️ Ostrzeżenia:</b><br>"
			for warning in warnings[:10]:  # Ogranicz do 10 ostrzeżeń
				html += f"- {warning}<br>"
			if len(warnings) > 10:
				html += f"... i jeszcze {len(warnings) - 10} ostrzeżeń<br>"
			html += "<br>"
		
		# Szczegółowe problemy per node
		if node_issues:
			html += "<b>🔍 Szczegóły problemów węzłów:</b><br>"
			for node_id, issue in list(node_issues.items())[:10]:  # Pierwsze 10 node'ów
				node = issue['node']
				html += f"<br><b>{node.name} (id={node.id}):</b><br>"
				if issue['errors']:
					html += "  Błędy:<br>"
					for err in issue['errors']:
						html += f"	• {err}<br>"
				if issue['warnings']:
					html += "  Ostrzeżenia:<br>"
					for warn in issue['warnings']:
						html += f"	• {warn}<br>"
		
		if not errors and not warnings:
			html += "<b style='color:green;'>✅ Walidacja zakończona pomyślnie!</b><br>"
			html += "Szablon jest poprawny i gotowy do użycia."
		
		# Zapisz do chatter
		self.message_post(
			body=Markup(html),
			subject="Walidacja szablonu XML",
			message_type="comment",
			subtype_xmlid="mail.mt_note",
		)
		
		# Notyfikacja
		notification_type = "success" if not errors else "danger"
		notification_message = f"Znaleziono {len(errors)} błędów i {len(warnings)} ostrzeżeń."
		
		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"title": "Walidacja szablonu",
				"message": notification_message,
				"type": notification_type,
				"sticky": True,
			},
		}


#EoF

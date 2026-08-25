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
"""@version 18.1.7
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
from markupsafe import Markup, escape

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

	def _validate_nodes_against_xsd(self):
		"""
		Porównuje typy przypisane do node'ów XET z deklaracjami w XSD.

		Metoda jest wyłącznie informacyjna:
		- nie zmienia node.type_id,
		- nie zmienia state node'ów.

		Źródłem prawdy jest rzeczywiste drzewo XSD rozwijane od globalnego
		elementu wskazanego w root_tag. Wynik jest słownikiem używanym do
		zbudowania osobnej sekcji raportu w chatterze.
		"""
		self.ensure_one()

		result = {
			"total": len(self.node_ids),
			"located": 0,
			"matching": 0,
			"mismatches": [],
			"not_found": [],
			"unresolved": [],
			"errors": [],
		}

		if not self.xsd_attachment_id:
			result["errors"].append("Brak głównego pliku XSD.")
			return result

		try:
			from lxml import etree
		except ImportError:
			result["errors"].append("Brak biblioteki lxml wymaganej do analizy XSD.")
			return result

		xsd_ns = "http://www.w3.org/2001/XMLSchema"
		component_tags = {
			"element": "element",
			"attribute": "attribute",
			"complex_type": "complexType",
			"simple_type": "simpleType",
			"group": "group",
			"attribute_group": "attributeGroup",
		}
		components = {
			key: {}
			for key in component_tags
		}
		components_by_local_name = {
			key: {}
			for key in component_tags
		}
		parsed_roots = {}

		def local_name(value):
			if not value:
				return None
			if not isinstance(value, str):
				return None
			if value.startswith("{"):
				return value.rsplit("}", 1)[-1]
			return value.split(":")[-1]

		def schema_root(xml_node):
			return xml_node.getroottree().getroot()

		def schema_target_namespace(xml_node):
			return schema_root(xml_node).get("targetNamespace") or ""

		def register_component(kind, namespace, name, xml_node):
			if not name:
				return

			key = (namespace or "", name)
			components[kind].setdefault(key, []).append(xml_node)
			components_by_local_name[kind].setdefault(name, []).append(xml_node)

		def resolve_qname(value, context_node):
			if not value:
				return "", None

			if ":" in value:
				prefix, name = value.split(":", 1)
				namespace = context_node.nsmap.get(prefix, "")
				return namespace or "", name

			# W większości schem XSD komponenty lokalne są wskazywane przez
			# tns:Name. Obsługujemy również zapis bez prefiksu.
			namespace = (
				context_node.nsmap.get(None)
				or schema_target_namespace(context_node)
				or ""
			)
			return namespace, value

		def lookup_component(kind, value, context_node):
			namespace, name = resolve_qname(value, context_node)
			if not name:
				return None, "Brak nazwy komponentu XSD."

			exact = components[kind].get((namespace, name), [])
			if len(exact) == 1:
				return exact[0], None
			if len(exact) > 1:
				return None, (
					f"Niejednoznaczna definicja XSD: {value} "
					f"({len(exact)} wystąpienia)."
				)

			# Fallback po nazwie lokalnej jest potrzebny dla schem, które
			# odwołują się do komponentów bez jawnego prefiksu namespace.
			by_name = components_by_local_name[kind].get(name, [])
			if len(by_name) == 1:
				return by_name[0], None
			if len(by_name) > 1:
				return None, (
					f"Niejednoznaczna nazwa lokalna XSD: {name} "
					f"({len(by_name)} definicje)."
				)

			return None, f"Nie znaleziono komponentu XSD: {value}."

		attachments = []
		seen_attachment_ids = set()
		for attachment in (
			self.xsd_attachment_id | self.xsd_type_attachment_ids
		):
			if attachment.id in seen_attachment_ids:
				continue
			seen_attachment_ids.add(attachment.id)
			attachments.append(attachment)

		# Najpierw parsujemy wszystkie pliki, aby później móc rozwiązywać
		# importy, include, ref, type, group i dziedziczenie typów.
		for attachment in attachments:
			try:
				xml_data = attachment.raw
				if not xml_data and attachment.datas:
					xml_data = base64.b64decode(attachment.datas)
				root = etree.fromstring(xml_data)
			except Exception as exc:
				result["errors"].append(
					f"Nie można odczytać XSD „{attachment.name}”: {exc}"
				)
				continue

			if etree.QName(root).namespace != xsd_ns:
				result["errors"].append(
					f"Załącznik „{attachment.name}” nie jest schematem XSD."
				)
				continue

			parsed_roots[attachment.id] = root
			target_namespace = root.get("targetNamespace") or ""

			# Rejestrujemy wyłącznie komponenty globalne. Elementy lokalne
			# będą odnajdywane przez przejście po rzeczywistym drzewie typów.
			for kind, tag_name in component_tags.items():
				for xml_node in root.findall(f"{{{xsd_ns}}}{tag_name}"):
					register_component(
						kind,
						target_namespace,
						xml_node.get("name"),
						xml_node,
					)

		main_root = parsed_roots.get(self.xsd_attachment_id.id)
		if main_root is None:
			return result

		def resolve_element_declaration(declaration):
			ref = declaration.get("ref")
			if not ref:
				return declaration, None
			return lookup_component("element", ref, declaration)

		def resolve_attribute_declaration(declaration):
			ref = declaration.get("ref")
			if not ref:
				return declaration, None
			return lookup_component("attribute", ref, declaration)

		def declared_type(declaration, node_kind="element"):
			if node_kind == "attribute":
				resolved, error = resolve_attribute_declaration(declaration)
			else:
				resolved, error = resolve_element_declaration(declaration)

			if error:
				return None, None, error

			type_value = resolved.get("type")
			if type_value:
				namespace, name = resolve_qname(type_value, resolved)
				if namespace == xsd_ns:
					return f"xs:{name}", "builtin", None
				return name, "named", None

			inline_simple = resolved.find(f"{{{xsd_ns}}}simpleType")
			if inline_simple is not None:
				restriction = inline_simple.find(
					f"{{{xsd_ns}}}restriction"
				)
				if restriction is not None and restriction.get("base"):
					namespace, name = resolve_qname(
						restriction.get("base"),
						restriction,
					)
					if namespace == xsd_ns:
						return f"xs:{name}", "builtin", None
					return name, "named_base", None

				list_node = inline_simple.find(f"{{{xsd_ns}}}list")
				if list_node is not None and list_node.get("itemType"):
					namespace, name = resolve_qname(
						list_node.get("itemType"),
						list_node,
					)
					if namespace == xsd_ns:
						return f"xs:{name}", "builtin", None
					return name, "named_base", None

				return None, "anonymous_simple", None

			inline_complex = resolved.find(f"{{{xsd_ns}}}complexType")
			if inline_complex is not None:
				for content_name in ("simpleContent", "complexContent"):
					content = inline_complex.find(
						f"{{{xsd_ns}}}{content_name}"
					)
					if content is None:
						continue
					derivation = content.find(f"{{{xsd_ns}}}extension")
					if derivation is None:
						derivation = content.find(
							f"{{{xsd_ns}}}restriction"
						)
					if derivation is None or not derivation.get("base"):
						continue

					namespace, name = resolve_qname(
						derivation.get("base"),
						derivation,
					)
					if namespace == xsd_ns:
						return f"xs:{name}", "builtin", None
					return name, "named_base", None

				return None, "anonymous_complex", None

			return None, None, "Element XSD nie posiada deklaracji typu."

		def resolve_complex_type(declaration):
			resolved, error = resolve_element_declaration(declaration)
			if error:
				return None, error

			inline_complex = resolved.find(f"{{{xsd_ns}}}complexType")
			if inline_complex is not None:
				return inline_complex, None

			type_value = resolved.get("type")
			if not type_value:
				return None, None

			namespace, name = resolve_qname(type_value, resolved)
			if namespace == xsd_ns:
				return None, None

			return lookup_component("complex_type", type_value, resolved)

		def particle_elements(container, visited_groups=None):
			visited_groups = set(visited_groups or ())
			found = []

			for child in container:
				tag = local_name(child.tag)

				if tag == "element":
					found.append(child)
				elif tag in ("sequence", "all", "choice"):
					found.extend(particle_elements(child, visited_groups))
				elif tag == "group":
					ref = child.get("ref")
					if not ref:
						found.extend(particle_elements(child, visited_groups))
						continue

					namespace, name = resolve_qname(ref, child)
					group_key = (namespace, name)
					if group_key in visited_groups:
						continue

					group, error = lookup_component("group", ref, child)
					if group is not None and not error:
						found.extend(
							particle_elements(
								group,
								visited_groups | {group_key},
							)
						)

			return found

		def type_attributes(container, visited_groups=None):
			visited_groups = set(visited_groups or ())
			found = []

			for child in container:
				tag = local_name(child.tag)
				if tag == "attribute":
					found.append(child)
				elif tag == "attributeGroup":
					ref = child.get("ref")
					if not ref:
						found.extend(type_attributes(child, visited_groups))
						continue

					namespace, name = resolve_qname(ref, child)
					group_key = (namespace, name)
					if group_key in visited_groups:
						continue

					group, error = lookup_component(
						"attribute_group",
						ref,
						child,
					)
					if group is not None and not error:
						found.extend(
							type_attributes(
								group,
								visited_groups | {group_key},
							)
						)

			return found

		def complex_type_members(complex_type, visited_types=None):
			visited_types = set(visited_types or ())
			elements = []
			attributes = []

			type_name = complex_type.get("name")
			type_key = (
				schema_target_namespace(complex_type),
				type_name or f"anonymous:{id(complex_type)}",
			)
			if type_key in visited_types:
				return elements, attributes
			visited_types.add(type_key)

			content = complex_type.find(f"{{{xsd_ns}}}complexContent")
			if content is None:
				content = complex_type.find(f"{{{xsd_ns}}}simpleContent")
			if content is not None:
				derivation = content.find(f"{{{xsd_ns}}}extension")
				if derivation is None:
					derivation = content.find(f"{{{xsd_ns}}}restriction")
				if derivation is not None:
					base = derivation.get("base")
					if base:
						base_type, error = lookup_component(
							"complex_type",
							base,
							derivation,
						)
						if base_type is not None and not error:
							base_elements, base_attributes = complex_type_members(
								base_type,
								visited_types,
							)
							elements.extend(base_elements)
							attributes.extend(base_attributes)

					elements.extend(particle_elements(derivation))
					attributes.extend(type_attributes(derivation))
					return elements, attributes

			elements.extend(particle_elements(complex_type))
			attributes.extend(type_attributes(complex_type))
			return elements, attributes

		def declaration_name(declaration, node_kind):
			if node_kind == "attribute":
				resolved, error = resolve_attribute_declaration(declaration)
			else:
				resolved, error = resolve_element_declaration(declaration)
			if error or resolved is None:
				return local_name(declaration.get("ref"))
			return resolved.get("name")

		def add_not_found(node, reason):
			result["not_found"].append({
				"path": node.xpath or node.name,
				"reason": reason,
			})
			for child in node.child_ids.sorted(key=lambda rec: (rec.sequence, rec.id)):
				add_not_found(
					child,
					"Nie można ustalić deklaracji, ponieważ nie odnaleziono rodzica.",
				)

		def validate_node(node, declaration, node_kind="element"):
			result["located"] += 1

			expected_type, type_kind, type_error = declared_type(
				declaration,
				node_kind=node_kind,
			)
			actual_type = node.type_id.name if node.type_id else None

			if type_error:
				result["unresolved"].append({
					"path": node.xpath or node.name,
					"reason": type_error,
				})
			elif type_kind in ("anonymous_simple", "anonymous_complex"):
				result["unresolved"].append({
					"path": node.xpath or node.name,
					"reason": (
						"Typ anonimowy zdefiniowany bezpośrednio przy elemencie "
						"XSD — brak nazwy pozwalającej na porównanie type_id."
					),
				})
			elif type_kind == "builtin":
				if actual_type:
					result["mismatches"].append({
						"path": node.xpath or node.name,
						"actual": actual_type,
						"expected": expected_type,
					})
				else:
					# Typy xs:* są częścią XML Schema i nie wymagają
					# rekordu xml.xsd.type ani relacji type_id.
					result["matching"] += 1
			elif expected_type:
				expected_comparable = expected_type.split(":")[-1]
				if actual_type == expected_comparable:
					result["matching"] += 1
				else:
					result["mismatches"].append({
						"path": node.xpath or node.name,
						"actual": actual_type or "brak",
						"expected": expected_type,
					})

			if node_kind != "element":
				return

			complex_type, complex_error = resolve_complex_type(declaration)
			children = node.child_ids.sorted(key=lambda rec: (rec.sequence, rec.id))

			if complex_error:
				for child in children:
					add_not_found(child, complex_error)
				return

			if complex_type is None:
				for child in children:
					add_not_found(
						child,
						"Typ rodzica w XSD nie jest typem złożonym.",
					)
				return

			element_declarations, attribute_declarations = complex_type_members(
				complex_type
			)
			declarations_by_key = {}

			for child_declaration in element_declarations:
				name = declaration_name(child_declaration, "element")
				if name:
					declarations_by_key.setdefault(
						("element", name),
						[],
					).append(child_declaration)

			for child_declaration in attribute_declarations:
				name = declaration_name(child_declaration, "attribute")
				if name:
					declarations_by_key.setdefault(
						("attribute", name),
						[],
					).append(child_declaration)

			for child in children:
				child_kind = (
					"attribute"
					if child.node_kind == "attribute"
					else "element"
				)
				candidates = declarations_by_key.get(
					(child_kind, local_name(child.name)),
					[],
				)

				if not candidates:
					add_not_found(
						child,
						"Brak elementu pod wskazanym rodzicem w XSD.",
					)
					continue

				if len(candidates) > 1:
					candidate_types = {
						declared_type(candidate, child_kind)[0]
						for candidate in candidates
					}
					if len(candidate_types) > 1:
						result["unresolved"].append({
							"path": child.xpath or child.name,
							"reason": (
								"Niejednoznaczna deklaracja elementu w XSD; "
								"pod tym samym rodzicem występuje kilka "
								"deklaracji o różnych typach."
							),
						})
						continue

				validate_node(child, candidates[0], child_kind)

		root_declarations = [
			xml_node
			for xml_node in main_root.findall(f"{{{xsd_ns}}}element")
			if xml_node.get("name") == self.root_tag
		]
		if not root_declarations:
			result["errors"].append(
				f"Nie znaleziono globalnego elementu root_tag „{self.root_tag}” "
				"w głównym XSD."
			)
			return result
		if len(root_declarations) > 1:
			result["errors"].append(
				f"Globalny element root_tag „{self.root_tag}” "
				"nie jest jednoznaczny."
			)
			return result

		root_nodes = self.node_ids.filtered(lambda node: not node.parent_id)
		for root_node in root_nodes.sorted(key=lambda rec: (rec.sequence, rec.id)):
			if local_name(root_node.name) != self.root_tag:
				add_not_found(
					root_node,
					f"Root node nie odpowiada root_tag „{self.root_tag}”.",
				)
				continue
			validate_node(root_node, root_declarations[0])

		return result


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
		# WALIDACJA INFORMACYJNA WZGLĘDEM RZECZYWISTEGO XSD
		# ------------------------------------------------------------
		xsd_report = self._validate_nodes_against_xsd()
		
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

		xsd_issue_count = (
			len(xsd_report["mismatches"])
			+ len(xsd_report["not_found"])
			+ len(xsd_report["unresolved"])
			+ len(xsd_report["errors"])
		)
		html += """
		<b>📐 Zgodność node'ów XET ze schematem XSD:</b><br>
		"""
		html += (
			f"• Węzły w szablonie: {xsd_report['total']}<br>"
			f"• Odnalezione w drzewie XSD: {xsd_report['located']}<br>"
			f"• Typ zgodny z XSD: {xsd_report['matching']}<br>"
			f"• Niezgodny lub nieprzypisany typ: "
			f"{len(xsd_report['mismatches'])}<br>"
			f"• Węzeł niewystępujący pod wskazanym rodzicem: "
			f"{len(xsd_report['not_found'])}<br>"
			f"• Niejednoznaczne lub niemożliwe do porównania: "
			f"{len(xsd_report['unresolved'])}<br><br>"
		)

		if xsd_report["errors"]:
			html += "<b style='color:red;'>Błędy odczytu schemy:</b><br>"
			for issue in xsd_report["errors"]:
				html += f"• {escape(issue)}<br>"
			html += "<br>"

		if xsd_report["mismatches"]:
			html += "<b style='color:red;'>Niezgodności typów XET ↔ XSD:</b><br>"
			for issue in xsd_report["mismatches"]:
				html += (
					f"• <b>{escape(issue['path'])}</b>: "
					f"XET = <code>{escape(issue['actual'])}</code>, "
					f"XSD = <code>{escape(issue['expected'])}</code><br>"
				)
			html += "<br>"

		if xsd_report["not_found"]:
			html += "<b style='color:orange;'>Węzły nieodnalezione w XSD:</b><br>"
			for issue in xsd_report["not_found"]:
				html += (
					f"• <b>{escape(issue['path'])}</b>: "
					f"{escape(issue['reason'])}<br>"
				)
			html += "<br>"

		if xsd_report["unresolved"]:
			html += (
				"<b style='color:orange;'>Węzły z anonimowym typem XSD (informacyjnie):</b><br>"
			)
			for issue in xsd_report["unresolved"]:
				html += (
					f"• <b>{escape(issue['path'])}</b>: "
					f"{escape(issue['reason'])}<br>"
				)
			html += "<br>"

		if not xsd_issue_count:
			html += (
				"<span style='color:green;'>"
				"✅ Wszystkie porównywalne węzły mają typ zgodny z XSD."
				"</span><br><br>"
			)
		
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
		if errors:
			notification_type = "danger"
		elif xsd_issue_count or warnings:
			notification_type = "warning"
		else:
			notification_type = "success"
		notification_message = (
			f"Znaleziono {len(errors)} błędów, {len(warnings)} ostrzeżeń "
			f"oraz {xsd_issue_count} uwag wynikających z porównania z XSD."
		)
		
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

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
"""@version 19.0.1.12.7
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval
import re
from odoo import release
import io
import uuid
from lxml import etree
from datetime import datetime, date
import json
import base64
from markupsafe import Markup, escape
from decimal import Decimal, ROUND_HALF_UP
import logging
_logger = logging.getLogger(__name__)

def safe_int(pattern):
	try:
		return int(pattern)
	except:
		return 0

# ADD: regex walidujący format nazwy
_NAME_RE = re.compile(
	r"^odoo-\d+(?:\.\d+)?-[a-z0-9_]+-[a-z0-9._]+-[a-z][a-z0-9_]*-\d+\.\d+\.\d+$"
)
_XPATH_RE = re.compile(r"^/[^\s]*$")

# ==============
# GŁÓWNY SZABLON
# ==============
class XmlExportTemplate(models.Model):
	_name = "xml.export.template"
	_inherit = ['mail.thread' ]
	_description = "Szablon eksportu XML (mapowanie pól do XSD)"
	_order = "name"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	# Identyfikacja
	name = fields.Char(required=True)
	uuid = fields.Char(string='UUID', translate=False, store=True)
	version = fields.Char(string='Version', translate=False, store=True)

	description = fields.Text()
	state = fields.Selection(
		selection=[
			("draft", "Draft"),
			("imported", "Imported"),
			("ready", "Ready"),
			("error", "Error"),
			("cancel", "Cancelled"),
		],
		string="Status",
		default="draft",
		index=True,
		required=True,
		help="Prosty cykl życia konfiguracji szablonu."
	)

	# ADD: kierunek dokumentu (na potrzeby doc_type w nazwie)
	doc_direction = fields.Selection(
		selection=[
			("out_invoice", "Customer Invoice"),
			("in_invoice", "Vendor Bill"),
			("out_refund", "Customer Credit Note"),
			("in_refund", "Vendor Debit Note"),
		],
		string="Kierunek dokumentu",
		default="out_invoice",
		help="Używane do złożenia segmentu <doc_type> w nazwie szablonu."
	)
	# Provider i kanał komunikacji
	provider_id = fields.Many2one(
		"communication.provider",
		string="Provider",
		help="Provider obsługujący wysyłkę dokumentów wygenerowanych z tego szablonu.",
		ondelete="restrict",
		tracking=True,
	)

	@api.model_create_multi
	def create(self, vals_list):
		# kompatybilność wsteczna: create(dict)
		if isinstance(vals_list, dict):
			vals_list = [vals_list]

		for vals in vals_list:
			if not vals.get("uuid"):
				vals["uuid"] = str(uuid.uuid4())

		return super().create(vals_list)

	@api.onchange("doc_direction", "root_tag", "namespace")
	def _onchange_recompose_name(self):
		for rec in self:
			#if not rec._is_valid_template_name(rec.name):
			rec.name = rec._compose_template_name()

	@api.onchange("xsd_attachment_id")
	def _onchange_xsd_attachment(self):
		"""Po podpięciu XSD — jeżeli nazwa jest pusta/niepoprawna — złóż ją automatycznie.
		(Nie parsujemy XSD; używamy istniejącej heurystyki na podstawie namespace/doc_direction)."""
		for rec in self:
			# Jeżeli masz już _ensure_name_after_xsd_and_direction – użyj jej:
			if hasattr(rec, "_ensure_name_after_xsd_and_direction"):
				rec._ensure_name_after_xsd_and_direction()
			# w przeciwnym razie nic nie rób (bezpieczny no-op)

	# Model źródłowy (rekord startowy eksportu)
	model_id = fields.Many2one(
		"ir.model",
		string="Model źródłowy",
		required=False,
		ondelete="cascade",
		index=True,
	)

	# Root XML + przestrzenie nazw
	root_tag = fields.Char(string="Root tag", required=False, help="Nazwa elementu głównego (bez prefiksu).")
	namespace = fields.Char(string="Główny XMLNS (URI)", help="Domyślny URI, używany gdy węzeł nie nadpisuje prefiksu.")
	ns_prefix = fields.Char(string="Domyślny prefiks", default="ns", help="Prefiks używany dla root i elementów bez lokalnego prefiksu.")
	namespace_ids = fields.One2many("xml.export.namespace", "template_id", string="Przestrzenie nazw (prefiksy)")

	# XSD (do walidacji i podglądu metadanych)
	xsd_attachment_id = fields.Many2one("ir.attachment", string="XSD", ondelete="restrict")
	xsd_target_namespace = fields.Char(string="XSD targetNamespace")
	xsd_version = fields.Char(string="Wersja schemy (np. 1-0E)")
	xsd_summary = fields.Text(string="Podsumowanie XSD", help="Pole informacyjne: liczba elementów/typów itp.")

	# ===== Alias fields for JSON export compatibility =====
	xml_namespace = fields.Char(related="namespace", string="XML Namespace", store=False)
	encoding = fields.Char(related="xml_encoding", string="Kodowanie XML", store=False)
	schema_filename = fields.Char(compute="_compute_schema_filename", store=False)

	def _compute_schema_filename(self):
		"""Zwraca nazwę pliku XSD z attachmentu, jeśli dostępna."""
		for rec in self:
			rec.schema_filename = rec.xsd_attachment_id.name or "schema.xsd"

	# Ustawienia generacji XML
	xml_encoding = fields.Char(default="UTF-8")
	include_xml_declaration = fields.Boolean(string="Deklaracja XML", default=True)
	pretty_print = fields.Boolean(string="Formatowanie (pretty print)", default=True)
	include_xsi = fields.Boolean(string="Dołącz xmlns:xsi", default=True)
	schema_location = fields.Char(string="xsi:schemaLocation", help="Jeśli wymagane przez odbiorcę.")
	validate_on_export = fields.Boolean(default=True, string="Waliduj wg XSD")

	# Węzły/XPath
	node_ids = fields.One2many("xml.export.node", "template_id", string="Węzły/XPath", copy=True)

	xsd_type_ids = fields.One2many(
		"xml.xsd.type", "template_id",
		string="Zdefiniowane typy XSD",
		help="Typy proste i złożone wczytane z pliku XSD DefinicjeTypy."
	)

	# Status
	active = fields.Boolean(default=True)

	# Stats: Przyciski i liczniki
	xsd_type_count = fields.Integer(
		string="Liczba typów XSD",
		compute="_compute_xsd_type_count",
		store=False
	)

	def _compute_xsd_type_count(self):
		for rec in self:
			rec.xsd_type_count = len(rec.xsd_type_ids)

	def action_show_xsd_types(self):
		"""Otwiera widok listy typów XSD powiązanych z tym szablonem."""
		self.ensure_one()
		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.xsd.type",
			"view_mode": "list,form",
			"domain": [("template_id", "=", self.id)],
			"name": _("Typy XSD powiązane z szablonem"),
		}

	# Sequence: SNAPSHOT — zapis aktualnej sekwencji
	def action_snapshot_sequence(self):
		for template in self:
			for node in template.node_ids:
				node.snapshot_sequence = node.sequence

	# Sequence: Restore SNAPSHOT
	def action_restore_selected(self):
		for template in self:
			for node in template.node_ids:
				if node.snapshot_sequence:
					node.sequence = node.snapshot_sequence

	# Sequence: Increment (ORM-safe)
	def action_increment_sequence(self):
		step=10
		for template in self:
			for node in template.node_ids:
				node.sequence = (node.sequence or 0) + step

	node_count = fields.Integer(
		string="Liczba węzłów",
		compute="_compute_node_count",
		store=False
	)

	def _compute_node_count(self):
		for rec in self:
			rec.node_count = len(rec.node_ids)

	def action_show_nodes(self):
		"""Otwiera widok listy węzłów powiązanych z tym szablonem."""
		self.ensure_one()
		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.export.node",
			"view_mode": "list,form",
			"domain": [("template_id", "=", self.id)],
			"name": _("Węzły XML dla szablonu"),
			"context": {
				"default_template_id": self.id,
				"search_default_group_by_parent": 1,  # jeśli chcesz grupować wg parenta
			},
			"target": "current",
		}

	def auto_sequence_nodes(self):
		pass


	# ============================================================
	# 💡 Mapowanie XSD na NODE
	# ============================================================
	def action_import_from_schema(self):
		self.ensure_one()

		if not self.xsd_attachment_id:
			raise UserError("Brak pliku XSD")

		# ------------------------------------------------------------
		# Parse main XSD
		# ------------------------------------------------------------
		try:
			schema_root = etree.fromstring(self.xsd_attachment_id.raw)
		except Exception as e:
			raise UserError(f"Błąd parsowania XSD: {e}")

		ns = {"xsd": "http://www.w3.org/2001/XMLSchema"}
		Type = self.env["xml.xsd.type"]

		# ------------------------------------------------------------
		# Clear existing nodes
		# ------------------------------------------------------------
		self.node_ids.unlink()

		# ------------------------------------------------------------
		# Build XSD lookup maps (local only)
		# ------------------------------------------------------------
		elements_by_name = {
			el.get("name"): el
			for el in schema_root.findall(".//xsd:element", ns)
			if el.get("name")
		}

		complex_types = {
			t.get("name"): t
			for t in schema_root.findall(".//xsd:complexType", ns)
			if t.get("name")
		}

		simple_types = {
			t.get("name"): t
			for t in schema_root.findall(".//xsd:simpleType", ns)
			if t.get("name")
		}

		groups = {
			g.get("name"): g
			for g in schema_root.findall(".//xsd:group", ns)
			if g.get("name")
		}

		attribute_groups = {
			g.get("name"): g
			for g in schema_root.findall(".//xsd:attributeGroup", ns)
			if g.get("name")
		}

		# ------------------------------------------------------------
		# Sequence generator (flat, deterministic)
		# ------------------------------------------------------------
		seq = {"val": 0}

		def next_seq():
			seq["val"] += 10
			return seq["val"]

		# ------------------------------------------------------------
		# Choice generator
		# ------------------------------------------------------------
		choice_seq = {"val": 0}

		def next_choice_key():
			choice_seq["val"] += 1
			return f"choice_{choice_seq['val']}"

		# ------------------------------------------------------------
		# Helpers
		# ------------------------------------------------------------
		def schema_target_namespace(xml_node):
			return (
				xml_node.getroottree().getroot().get("targetNamespace")
				or ""
			)

		def resolve_qname(value, context_node):
			"""Rozwiązuje QName do pary (namespace_uri, nazwa lokalna)."""
			if not value:
				return "", None

			if ":" in value:
				prefix, local_type_name = value.split(":", 1)
				return (
					context_node.nsmap.get(prefix) or "",
					local_type_name,
				)

			return (
				context_node.nsmap.get(None)
				or schema_target_namespace(context_node),
				value,
			)

		def find_xsd_type(type_name, context_node):
			"""
			Wyszukuje typ XSD dla bieżącego szablonu.

			Kolejność:
			1. Dokładna zgodność namespace_uri + name.
			2. Jeśli brak dokładnego wyniku, dopuszcza typ po samej nazwie,
			   ale wyłącznie wtedy, gdy istnieje dokładnie jeden kandydat.
			3. Nie tworzy relacji dla wbudowanych typów XML Schema.
			"""
			namespace_uri, local_type_name = resolve_qname(
				type_name,
				context_node,
			)

			if not local_type_name or namespace_uri == ns["xsd"]:
				return Type.browse()

			base_domain = [
				("template_id", "=", self.id),
				("company_id", "=", self.company_id.id),
				("name", "=", local_type_name),
			]

			# Najpierw dokładne dopasowanie QName.
			if "namespace_uri" in Type._fields and namespace_uri:
				exact_type = Type.search(
					base_domain + [
						("namespace_uri", "=", namespace_uri),
					],
					limit=1,
				)
				if exact_type:
					return exact_type

			# Katalog utworzony przez aktualny importer ma namespace_uri=NULL.
			# Fallback jest bezpieczny tylko przy dokładnie jednym kandydacie.
			candidates = Type.search(base_domain, limit=2)

			if len(candidates) == 1:
				return candidates

			return Type.browse()

		def effective_type_name(declaration):
			"""
			Zwraca nazwany typ elementu albo nazwaną bazę jego lokalnej
			definicji. Nie tworzy nazw dla typów anonimowych.
			"""
			type_name = declaration.get("type")
			if type_name:
				return type_name

			paths = (
				"xsd:simpleType/xsd:restriction",
				"xsd:simpleType/xsd:list",
				"xsd:complexType/xsd:simpleContent/xsd:extension",
				"xsd:complexType/xsd:simpleContent/xsd:restriction",
				"xsd:complexType/xsd:complexContent/xsd:extension",
				"xsd:complexType/xsd:complexContent/xsd:restriction",
			)
			for path in paths:
				derivation = declaration.find(path, ns)
				if derivation is None:
					continue
				base = (
					derivation.get("base")
					or derivation.get("itemType")
				)
				if base:
					return base

			return None

		def fallback_type_kind(type_name, default="complex"):
			"""Rozpoznaje typy wbudowane xs:/xsd:, gdy brak type_id."""
			if (
				type_name
				and ":" in type_name
				and type_name.split(":", 1)[0] in ("xs", "xsd")
			):
				return "builtin"
			return default

		def walk_attributes(container, parent_id):
			for attr in container.findall("xsd:attribute", ns):
				name = attr.get("name")
				if not name:
					continue

				type_name = effective_type_name(attr)
				xsd_type_rec = find_xsd_type(type_name, attr)

				self.env["xml.export.node"].create({
					"template_id": self.id,
					"parent_id": parent_id,
					"sequence": next_seq(),
					"name": name,
					"node_kind": "attribute",
					"type_id": xsd_type_rec.id or False,
					"xsd_type_kind": (
						xsd_type_rec.category
						if xsd_type_rec
						else fallback_type_kind(type_name, default="simple")
					),
					"xsd_min_occurs": 0 if attr.get("use") != "required" else 1,
					"xsd_max_occurs": 1,
					'company_id': self.company_id.id,
				})

			for grp in container.findall("xsd:attributeGroup", ns):
				ref = grp.get("ref")
				if ref:
					g = attribute_groups.get(ref.split(":")[-1])
					if g:
						walk_attributes(g, parent_id)

		def walk_complex_children(container, parent_id, depth):
			def handle_choice(choice_node, parent_id, depth):
				choice_key = next_choice_key()

				for child in choice_node:
					# wariant prosty: <xsd:element>
					if child.tag.endswith("element"):
						walk_element(
							child,
							parent_id,
							depth + 1,
							choice_meta={
								"choice": choice_key,
								"variant": child.get("name") or child.get("ref"),
								"role": "single",
							}
						)

					# wariant złożony: <xsd:sequence> lub <xsd:all>
					elif child.tag.endswith("sequence") or child.tag.endswith("all"):
						variant_key = f"{choice_key}_seq"

						# UWAGA: sekwencja w choice może zawierać elementy, grupy i (czasem) kolejne choice
						for sub in child:
							if sub.tag.endswith("element"):
								walk_element(
									sub,
									parent_id,
									depth + 1,
									choice_meta={
										"choice": choice_key,
										"variant": variant_key,
										"role": "sequence",
									}
								)
							elif sub.tag.endswith("group"):
								ref = sub.get("ref")
								if ref:
									g = groups.get(ref.split(":")[-1])
									if g:
										walk_complex_children(g, parent_id, depth + 1)
							elif sub.tag.endswith("choice"):
								# bardzo rzadkie, ale bezpieczne
								handle_choice(sub, parent_id, depth + 1)

			# 1) Obsłuż sequence/all – ale iteruj po WSZYSTKICH dzieciach, nie tylko po elementach
			for block in ("sequence", "all"):
				node = container.find(f"xsd:{block}", ns)
				if node is not None:
					for child in node:
						if child.tag.endswith("element"):
							walk_element(child, parent_id, depth + 1)

						elif child.tag.endswith("group"):
							ref = child.get("ref")
							if ref:
								g = groups.get(ref.split(":")[-1])
								if g:
									walk_complex_children(g, parent_id, depth + 1)

						elif child.tag.endswith("choice"):
							# TO JEST KLUCZ: choice w środku sequence (TPodmiot3)
							handle_choice(child, parent_id, depth + 1)

					# po przetworzeniu sequence/all nie kończ – bo container może mieć jeszcze inne bloki
					# (w praktyce rzadko, ale to bezpieczniejsze niż return)

			# 2) Obsłuż choice bezpośrednio pod complexType/extension (Twoja poprzednia ścieżka)
			choice = container.find("xsd:choice", ns)
			if choice is not None:
				handle_choice(choice, parent_id, depth)

			# 3) Obsłuż grupy bezpośrednio (jeżeli są)
			for grp in container.findall("xsd:group", ns):
				ref = grp.get("ref")
				if ref:
					g = groups.get(ref.split(":")[-1])
					if g:
						walk_complex_children(g, parent_id, depth + 1)



		# ------------------------------------------------------------
		# CORE – new walk_element (KSeF incoming)
		# ------------------------------------------------------------
		def walk_element(el, parent_id=None, depth=0, choice_meta=None):
			if depth > 50:
				return

			# resolve ref
			if el.get("ref"):
				ref_name = el.get("ref").split(":")[-1]
				el = elements_by_name.get(ref_name)
				if not el:
					return

			name = el.get("name")
			if not name:
				return

			declared_type_name = el.get("type")
			effective_type = effective_type_name(el)
			node_vals = {
				"template_id": self.id,
				"parent_id": parent_id,
				"sequence": next_seq(),
				"name": name,
				"node_kind": "element",
				"xsd_min_occurs": int(el.get("minOccurs", "1")),
				"xsd_max_occurs": (
					0 if el.get("maxOccurs") == "unbounded"
					else int(el.get("maxOccurs", "1"))
				),
				"xsd_nillable": el.get("nillable") == "true",
				'company_id': self.company_id.id,
			}

			# -----------------------------
			# TYPE resolution (xml.xsd.type first)
			# -----------------------------
			xsd_type_rec = find_xsd_type(effective_type, el)

			if xsd_type_rec:
				node_vals["type_id"] = xsd_type_rec.id
				node_vals["xsd_type_kind"] = xsd_type_rec.category
			else:
				node_vals["type_id"] = False
				node_vals["xsd_type_kind"] = fallback_type_kind(
					effective_type,
					default="complex",
				)

			node = self.env["xml.export.node"].create(node_vals)

			# -----------------------------
			# Inline simpleType
			# -----------------------------
			inline_simple = el.find("xsd:simpleType", ns)
			if inline_simple is not None:
				restriction = inline_simple.find("xsd:restriction", ns)
				if restriction is not None:
					enums = [
						e.get("value")
						for e in restriction.findall("xsd:enumeration", ns)
						if e.get("value")
					]
					if enums:
						node.write({"xsd_enumeration": ",".join(enums)})
				return

			# -----------------------------
			# Resolve type definition
			# -----------------------------
			type_def = None

			if declared_type_name:
				clean = declared_type_name.split(":")[-1]
				type_def = complex_types.get(clean)
				if type_def is None:
					type_def = simple_types.get(clean)

			if type_def is None:
				type_def = el.find("xsd:complexType", ns)

			if type_def is None:
				return

			# -----------------------------
			# simpleType
			# -----------------------------
			if type_def.tag.endswith("simpleType"):
				restriction = type_def.find("xsd:restriction", ns)
				if restriction is not None:
					enums = [
						e.get("value")
						for e in restriction.findall("xsd:enumeration", ns)
						if e.get("value")
					]
					if enums:
						node.write({"xsd_enumeration": ",".join(enums)})
				return

			# -----------------------------
			# complexContent / extension
			# -----------------------------
			complex_content = type_def.find("xsd:complexContent", ns)
			if complex_content is not None:
				extension = complex_content.find("xsd:extension", ns)
				if extension is not None:
					base = extension.get("base")
					if base:
						base_name = base.split(":")[-1]
						base_type = complex_types.get(base_name)
						if base_type is not None:
							walk_complex_children(base_type, node.id, depth + 1)
					walk_complex_children(extension, node.id, depth + 1)
					walk_attributes(extension, node.id)
					return

			# -----------------------------
			# regular complexType
			# -----------------------------
			walk_complex_children(type_def, node.id, depth + 1)
			walk_attributes(type_def, node.id)

		# ------------------------------------------------------------
		# Determine root element
		# ------------------------------------------------------------
		if not self.root_tag:
			roots = [
				el.get("name")
				for el in schema_root.findall("xsd:element", ns)
				if el.get("name")
			]
			if not roots:
				raise UserError("Nie znaleziono elementu root w XSD")
			self.root_tag = roots[0]

		root_el = elements_by_name.get(self.root_tag)
		if root_el is None:
			raise UserError(f"Nie znaleziono root elementu: {self.root_tag}")

		# ------------------------------------------------------------
		# Start import
		# ------------------------------------------------------------
		walk_element(root_el)

		return True
	# ============================================================

	# ============================================================
	# Pomocnicze - walidacja - formatowanie
	# ============================================================

	def _format_xsd_value(self, node, value, record=None):
		"""
		Steruje formatowaniem wartości node'a.

		Zasady:
		1. Wartość wejściowa jest jednocześnie wartością domyślną wyniku.
		2. Jeżeli node posiada typ XSD:
		   a) pierwszeństwo ma pattern typu,
		   b) przy braku pattern stosowane jest formatowanie według typu.
		3. Jeżeli node nie posiada typu XSD, sprawdzane są ustawienia
		   formatowania zapisane bezpośrednio na node.
		4. Jeżeli żadna reguła nie zostanie dopasowana, zwracana jest
		   wartość wejściowa bez zmian.
		"""

		result = value

		if result is None:
			return result

		_logger.info(
			"🔧 FORMAT_XSD: node=%s, value=%r, type=%s",
			node.name,
			result,
			type(result),
		)

		xsd_type = node.type_id

		# ============================================================
		# 1. FORMATOWANIE NA PODSTAWIE TYPU XSD
		# ============================================================
		if xsd_type:

			# Pattern ma pierwszeństwo przed pozostałymi informacjami typu.
			if xsd_type.pattern:
				result = self._format_value_by_xsd_pattern(
					node=node,
					xsd_type=xsd_type,
					result=result,
					record=record,
				)

				_logger.info(
					"🔧 FORMAT_XSD: result after pattern processing: %r",
					result,
				)
				return result

			# Brak pattern — próba formatowania według typu lub base_type.
			result = self._format_value_by_xsd_type(
				node=node,
				xsd_type=xsd_type,
				result=result,
				record=record,
			)

			_logger.info(
				"🔧 FORMAT_XSD: result after type processing: %r",
				result,
			)
			return result

		# ============================================================
		# 2. FORMATOWANIE NA PODSTAWIE USTAWIEŃ NODE
		# ============================================================
		result = self._format_value_by_node_options(
			node=node,
			result=result,
			record=record,
		)

		_logger.info(
			"🔧 FORMAT_XSD: result after node options processing: %r",
			result,
		)

		return result



	# ============================================================
	# PUBLIC API – główny punkt wejścia
	# ============================================================
	def generate_xml(self, record, in_memory=False):
		"""
		Generuje finalny dokument XML na podstawie mapowania `xml.export.node`
		dla bieżącego szablonu (`xml.export.template`) i wskazanego rekordu źródłowego
		(np. `account.move`, `res.partner`, itp.).

		🔹 Etapy działania:

		1) Ustalenie przestrzeni nazw (`namespace`, `ns_prefix`) i przygotowanie mapy `nsmap`.

		2) Odszukanie węzła głównego (root node):
		   - wybierany jest pierwszy node bez `parent_id`,
		   - jeżeli brak takiego node — rzuca wyjątek `UserError`,
		   - jeżeli jest więcej niż jeden root — używa pierwszego i loguje ostrzeżenie.

		3) Utworzenie elementu ROOT w lxml (`etree.Element(...)`) na podstawie `root_node.tag`.

		4) Jeśli do szablonu podpięty jest `xsd_attachment_id`:
		   - dodaje atrybut `xsi:schemaLocation` zawierający nazwę pliku XSD.

		5) Renderowanie XML:
		   - uruchamiane przez metodę `_render_node(...)`, która rekurencyjnie buduje XML,
		   - renderowanie bazuje na hierarchii `xml.export.node` powiązanych z szablonem,
		   - każdy node może mieć źródło wartości (pole Odoo, stała, wyrażenie itd.),
		   - w przypadku błędu logowana jest struktura node'ów i wyjątek jest propagowany.

		6) Serializacja:
		   - konwersja elementu XML do bajtów (`etree.tostring(...)`),
		   - uwzględnia deklarację `<?xml ...?>` i `pretty_print` jeśli zaznaczono.

		7) Zwrócenie wyniku:
		   - jeśli `in_memory=True` → zwracane są bajty XML (`bytes`),
		   - w przeciwnym wypadku tworzony jest załącznik `ir.attachment`, powiązany z rekordem.

		🔒 Uwagi bezpieczeństwa:
		- XML jest budowany w całości po stronie serwera i nie korzysta z eval lub exec,
		- źródła danych są weryfikowane zgodnie z definicją node'ów,
		- węzły są przetwarzane tylko w zakresie tego szablonu.

		:param record: rekord źródłowy (np. `account.move`) dla którego ma zostać wygenerowany XML
		:param in_memory: jeśli True, wynik nie jest zapisywany jako załącznik tylko zwracany jako bytes
		:return: bajty XML (`bytes`) lub `ir.attachment` w zależności od `in_memory`
		"""
		self.ensure_one()

		_logger.info(
			f"\n👉 Generuje finalny XML dla rekordu {record}."
			f"\n👉 XMLGEN: Szablon={self.name}, root_tag={self.root_tag}"
			f"\n👉 XMLGEN: Węzły razem={len(self.node_ids)}")
		
		# DEBUG: Pokaż strukturę drzewa
		_logger.info("=== DEBUG NODE STRUCTURE ===")
		self._debug_node_structure()
		_logger.info("=== END DEBUG ===")

		# 1. Namespace
		ns_uri = self.namespace or ""
		nsmap = {
			None: ns_uri,
			"xsi": "http://www.w3.org/2001/XMLSchema-instance",
		}
		if self.ns_prefix:
			nsmap[self.ns_prefix] = ns_uri

		# 2. Pobierz root node
		root_nodes = self.node_ids.filtered(lambda n: not n.parent_id)
		if not root_nodes:
			raise UserError("Nie znaleziono węzła głównego w szablonie (brak node bez parent_id).")
		
		if len(root_nodes) > 1:
			_logger.warning("Multiple root nodes found, using first one")
		
		root_node = root_nodes[0]
		_logger.info(f"Using root node: id={root_node.id}, tag={root_node.tag}")

		# 3. Utworzenie ROOT elementu z tagiem root_node
		root_elem = etree.Element(
			f"{{{ns_uri}}}{root_node.tag}", 
			nsmap=nsmap
		)
		_logger.info(f"Created root element: {root_elem.tag}")

		# 4. schemaLocation (jeśli jest)
		if self.xsd_attachment_id:
			filename = self.xsd_attachment_id.name or "schema.xsd"
			xsl = f"{ns_uri} {filename}"
			root_elem.set(
				"{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
				xsl
			)

		# 5. Renderowanie - przekazujemy root_node, który obsłuży swoje dzieci
		try:
			self._render_node(root_node, record, root_elem)
		except Exception as e:
			_logger.error(f"Error during XML rendering: {e}")
			# Dump struktury dla debugowania
			_logger.error("Current node structure:")
			for n in self.node_ids.filtered(lambda n: not n.parent_id):
				self._log_node_structure(n, 0)
			raise

		# 6. Serializacja
		xml_bytes = etree.tostring(
			root_elem,
			encoding="utf-8",
			xml_declaration=True,
			pretty_print=True,
		)

		_logger.info(f"✅ Generated XML size: {len(xml_bytes)} bytes")

		if in_memory:
			return xml_bytes

		# 7. Zapis jako załącznik
		attachment = self.env['ir.attachment'].with_company( record.company_id).create({
			'company_id': record.company_id.id,
			'name': f"{self.name}-{record.id}.xml",
			'type': 'binary',
			'datas': base64.b64encode(xml_bytes),
			'mimetype': 'application/xml',
			'res_model': record._name,
			'res_id': record.id,
		})

		return attachment

	def _debug_node_structure(self, node_id=None, level=0):
		"""Debugowanie struktury drzewa."""
		if node_id is None:
			# Znajdź root node
			root_nodes = self.node_ids.filtered(lambda n: not n.parent_id)
			if root_nodes:
				node_id = root_nodes[0].id
			else:
				_logger.error("No root node found!")
				return
		
		node = self.node_ids.filtered(lambda n: n.id == node_id)
		if not node:
			return
			
		node = node[0]
		indent = "  " * level
		loop_info = f", LOOP: {node.loop_mode}" if node.loop_mode != "none" else ""
		kind_info = f", KIND: {node.node_kind}" if node.node_kind != "element" else ""
		_logger.info(f"{indent}{node.tag} (id={node.id}{loop_info}{kind_info})")
		
		children = self.node_ids.filtered(
			lambda c: c.parent_id and c.parent_id.id == node.id
		)
		children = children.sorted(key=lambda c: (c.sequence or 0, c.id))
		
		for child in children:
			self._debug_node_structure(child.id, level + 1)

	def _log_node_structure(self, node, level=0):
		"""Pomocnicza metoda do logowania struktury drzewa."""
		indent = "  " * level
		loop_info = f", loop_mode={node.loop_mode}" if node.loop_mode != "none" else ""
		kind_info = f", kind={node.node_kind}" if node.node_kind != "element" else ""
		_logger.error(f"{indent}- {node.tag} (id={node.id}{loop_info}{kind_info})")
		children = self.node_ids.filtered(lambda c: c.parent_id and c.parent_id.id == node.id)
		for child in children.sorted(key=lambda c: c.sequence or 0):
			self._log_node_structure(child, level + 1)


	def _resolve_loop_collection(self, node, record):
		"""Rozwiązuje kolekcję dla węzła w trybie pętli."""
		_logger.info(f"🔁 RESOLVE_LOOP: node={node.name}, mode={node.loop_mode}")
		
		if node.loop_mode == "none":
			return None
			
		try:
			if node.loop_mode in ["one2many", "many2many"]:
				if not node.loop_rel_field_id:
					_logger.error(f"Missing loop_rel_field_id for node {node.name}")
					return None
					
				field_name = node.loop_rel_field_id.name
				_logger.info(f"RESOLVE_LOOP: Accessing field {field_name} on record {record}")
				
				###collection = getattr(record, field_name)
				# 🔁 Obsługa specjalna: korekta KSeF → linie przed i po
				if (
					field_name == "invoice_line_ids"
					and record._name == "account.move"
					and record.ksef_rodzaj_faktury == "KOR"
					and record.move_type == "out_invoice"
					and record.ksef_correction_type in ("1", "2", "3")
				):
					collection = record._prepare_ksef_correction_lines()
				else:
					collection = getattr(record, field_name)

				# 💡 FILTRACJA: pomiń linie typu 'line_section', 'line_note'
				#if field_name == "invoice_line_ids":
				#	collection = collection.filtered(lambda line: line.display_type not in ('line_section', 'line_note'))

				# ✅ FILTRACJA: pomiń linie sekcji/notatek ORAZ zaliczki
				if field_name == "invoice_line_ids":
					collection = collection.filtered(
						lambda line: (
							line.display_type not in ('line_section', 'line_note')
							and not line.is_downpayment
						)
					)
					_logger.info(f"📋 Filtered out section/note/downpayment lines, {len(collection)} remain")
				
				# Apply ordering
				if node.loop_order:
					collection = collection.sorted(node.loop_order)
					
				# Apply limit
				if node.loop_limit:
					collection = collection[:node.loop_limit]
					
				_logger.info(f"RESOLVE_LOOP: Found {len(collection)} records: {collection.ids}")
				return collection
				
			elif node.loop_mode == "domain":
				if not node.loop_model_id or not node.loop_domain:
					_logger.error(f"Missing loop_model_id or loop_domain for node {node.name}")
					return None
					
				model_name = node.loop_model_id.model
				try:
					domain = safe_eval(node.loop_domain) if node.loop_domain else []
				except:
					domain = []
				
				_logger.info(f"RESOLVE_LOOP: Searching {model_name} with domain {domain}")
				collection = self.env[model_name].with_company(self.company_id).search(domain, order=node.loop_order, limit=node.loop_limit)
				_logger.info(f"RESOLVE_LOOP: Found {len(collection)} records via domain")
				return collection
				
		except Exception as e:
			_logger.error(f"RESOLVE_LOOP: Error for node {node.name}: {e}")
			return None
			
		return None
	# ============================================================
	# REKURENCYJNE BUDOWANIE DRZEWA
	# ============================================================
	def _render_node(self, node, record, parent_elem, visited=None, skip_xpath_prefixes=None):
		"""
		Rekurencyjnie renderuje strukturę XML od danego `node`, tworząc poddrzewo XML
		dla pojedynczego elementu lub kolekcji elementów na podstawie `xml.export.node`.

		🔹 Parametry:
		- `node`: pojedynczy węzeł XML (`xml.export.node`) do renderowania
		- `record`: rekord Odoo (np. `account.move`, `res.partner`), z którego pobierane są dane
		- `parent_elem`: element nadrzędny w drzewie lxml (`etree.Element`)
		- `visited`: zbiór ID przetworzonych node'ów (ochrona przed cyklami)

		🔹 Obsługiwane tryby node'ów:
		1) Węzeł główny (`root`):
		   - rozpoznawany po `node.parent_id == False`,
		   - jego dzieci są przetwarzane bezpośrednio i przypinane do `parent_elem`,
		   - sam root nie tworzy nowego elementu — tylko dzieci są renderowane.

		2) Atrybut (`node_kind == 'attribute'`):
		   - uzyskana wartość `value` jest dodawana jako atrybut do `parent_elem`,
		   - nie generuje osobnego elementu XML.

		3) Tekst (`node_kind == 'text'`):
		   - wynik renderowania jest dodany jako `.text` wewnątrz `parent_elem`,
		   - obsługuje dołączanie do istniejącego tekstu.

		4) Pętla (`loop_mode != 'none'`):
		   - obsługiwane tryby: `one2many`, `many2many`, `domain`,
		   - metoda `_resolve_loop_collection()` pobiera kolekcję rekordów,
		   - dla każdego elementu w kolekcji tworzony jest osobny XML element (SubElement),
		   - dzieci są renderowane względem konkretnego `item` z kolekcji (nie `record` główny),
		   - brak kolekcji logowany jako ostrzeżenie, ale nie przerywa renderowania.

		5) Normalny element (`element` bez pętli):
		   - tworzony jest nowy element XML (z tagiem `node.tag` i kwalifikatorem namespace),
		   - wartość uzyskana z `_get_node_value()` trafia do `.text`,
		   - przetwarzane są wszystkie dzieci, rekurencyjnie.

		🔁 Wariant rekurencji:
		- każde wywołanie `_render_node` przekazuje kopię `visited` — ochrona przed cyklami.
		- dzieci sortowane po `sequence`, aby zachować kolejność eksportu.

		🔐 Zabezpieczenia:
		- jeśli `value` jest puste (`None`, `False`, `""`, `[]`, `{}`) → nie renderuje treści,
		- jeśli `node.id` jest już w `visited` → pomija renderowanie (cykl),
		- każde przetwarzanie node'a logowane do `_logger.info(...)`.

		:return: element XML (`etree.Element`) zawierający zrenderowane dane
		"""
		if visited is None:
			visited = set()

		if skip_xpath_prefixes is None:
			skip_xpath_prefixes = set()


		# ❌ SKIP if xpath matches a skipped parent prefix
		for prefix in skip_xpath_prefixes:
			if node.xpath == prefix or node.xpath.startswith(prefix + "/"):
				_logger.warning(f"⛔ SKIPPED due to parent exclusion: {node.xpath}")
				return parent_elem
		
		if node.id in visited:
			_logger.warning(f"Cycle detected at node {node.tag}")
			return parent_elem
		visited.add(node.id)

		_logger.info(f"RENDER: node={node.tag}, kind={node.node_kind}, loop_mode={node.loop_mode}")

		# ✅ LOGIKA WARUNKOWEGO PRZETWARZANIA NODE'A
		if node.condition_expr:
			try:
				_logger.info(f"🔍 CONDITION: evaluating '{node.condition_expr}'")
				condition_result = safe_eval(
					node.condition_expr,
					{
						"record": record,
						"env": record.env,
						"datetime": datetime,
						"date": date,
					}
				)
				_logger.info(f"🔍 CONDITION: result → {condition_result}")
				if not condition_result:
					skip_xpath_prefixes.add(node.xpath) # ✅ ZAPAMIĘTUJEMY prefix xpath
					_logger.warning(f"⛔ NODE {node.name} skipped due to failed condition.")
					return parent_elem  # ❌ pomiń ten węzeł i dzieci
			except Exception as e:
				_logger.error(f"❌ ERROR in condition_expr for node {node.name}: {e}")
				raise UserError(f"Błąd w condition_expr node {node.name}: {str(e)}")
		else:
			_logger.info(f"🔍 CONDITION: no condition_expr → allowed")

		# SPECIAL CASE: ROOT NODE
		if not node.parent_id:
			_logger.info(f"Processing root node children for {node.tag}")
			children = self.node_ids.filtered(
				lambda c: c.parent_id and c.parent_id.id == node.id
			)
			children = children.sorted(key=lambda c: (c.sequence or 0, c.id))
			
			for child in children:
				self._render_node(child, record, parent_elem, visited.copy(), skip_xpath_prefixes)
			return parent_elem

		# 1. ATRYBUT
		if node.node_kind == "attribute":
			value = self._get_node_value(node, record)
			if value not in (None, False, "", [], {}):
				parent_elem.set(node.tag, str(value))
			return parent_elem

		# 2. TEKST
		if node.node_kind == "text":
			value = self._get_node_value(node, record)
			if value not in (None, False, "", [], {}):
				if parent_elem.text:
					parent_elem.text += str(value)
				else:
					parent_elem.text = str(value)
			return parent_elem


		# 3. PĘTLA (loop_mode)
		if node.loop_mode != "none":
			_logger.info(f"LOOP: node={node.name}, mode={node.loop_mode}")
			
			collection = self._resolve_loop_collection(node, record)
			
			if collection:
				for item in collection:
					# 🔥 KLUCZOWA ZMIANA: resetuj skip_xpath_prefixes dla każdej iteracji
					iter_skip_prefixes = set()  # Nowy, pusty zbiór dla każdej iteracji
					
					elem = etree.SubElement(parent_elem, self._qualify_tag(node))
					
					# wartość węzła
					value = self._get_node_value(node, item)
					if value not in (None, False, "", [], {}):
						elem.text = str(value)
					
					# Renderuj dzieci z NOWYM, PUSTYM zbiorem skip_xpath_prefixes
					children = self.node_ids.filtered(
						lambda c: c.parent_id and c.parent_id.id == node.id
					)
					children = children.sorted(key=lambda c: (c.sequence or 0, c.id))
					
					for child in children:
						self._render_node(child, item, elem, visited.copy(), iter_skip_prefixes)
			else:
				_logger.warning(f"LOOP: Empty collection for {node.name}")
			
			return parent_elem

		"""# 3. PĘTLA (loop_mode) - TYMCZASOWE WYŁĄCZENIE!
		if node.loop_mode != "none":
			_logger.info(f"LOOP: node={node.name}, mode={node.loop_mode}")
			
			# UŻYJ NOWEJ METODY do rozwiązania kolekcji
			collection = self._resolve_loop_collection(node, record)
			_logger.info(f"LOOP: collection={collection}, count={len(collection) if collection else 0}")
			
			if collection:
				for item in collection:
					# Tworzymy element dla każdego item w kolekcji
					elem = etree.SubElement(parent_elem, self._qualify_tag(node))

					# 🔥 NAJPIERW WARTOŚĆ WĘZŁA (jeśli ma)
					value = self._get_node_value(node, item)
					if value not in (None, False, "", [], {}):
						_logger.info(f"\n🔥 NAJPIERW WARTOŚĆ WĘZŁA value = {value}")
						elem.text = str(value)
					
					# Renderujemy dzieci dla KONKRETNEGO ITEM, nie głównego rekordu!
					children = self.node_ids.filtered(
						lambda c: c.parent_id and c.parent_id.id == node.id
					)
					children = children.sorted(key=lambda c: (c.sequence or 0, c.id))
					
					for child in children:
						# KLUCZOWA ZMIANA: przekazujemy 'item' zamiast 'record'
						self._render_node(child, item, elem, visited.copy(), skip_xpath_prefixes)
			else:
				_logger.warning(f"LOOP: Empty collection for {node.name}")
			
			return parent_elem
		"""
		# 4. ELEMENT NORMALNY (bez pętli)
		elem = etree.SubElement(parent_elem, self._qualify_tag(node))

		value = self._get_node_value(node, record)
		_logger.info(f"📝 RENDER VALUE for {node.name}: '{value}' (type: {type(value)})")
		if value not in (None, False, "", [], {}):
			elem.text = str(value)
			_logger.info(f"Set value for node {node.tag}: {value}")
		else:
			_logger.warning(f"❌ SKIP VALUE for {node.name}: value is empty")

		children = self.node_ids.filtered(
			lambda c: c.parent_id and c.parent_id.id == node.id
		)
		children = children.sorted(key=lambda c: (c.sequence or 0, c.id))
		
		_logger.info(f"Węzeł {node.tag} posiada {len(children)} potomnych")
		
		for child in children:
			self._render_node(child, record, elem, visited.copy(), skip_xpath_prefixes)

		return elem	

	# ============================================================
	# WARTOŚĆ NODE'U
	# ============================================================
	def _get_node_value(self, node, record):
		"""Zwraca wartość node'a zgodnie z value_source."""
		_logger.info(f"🔍 GET_VALUE: node={node.name}, source={node.value_source}")
		
		raw_value = None
		
		# NONE
		if not node.value_source or node.value_source == "none":
			_logger.info(f"  → NONE: returning None")
			return None

		# CONSTANT
		if node.value_source == "constant":
			raw_value = node.value_constant or None
			_logger.info(f"  → CONSTANT raw: '{raw_value}'")

		# LITERAL
		elif node.value_source == "literal_xml":
			raw_value = node.value_literal or None
			_logger.info(f"  → LITERAL raw: '{raw_value}'")

		# FIELD (relpath)
		elif node.value_source == "field":
			_logger.info(f"  → FIELD: resolving path '{node.src_rel_path}'")
			raw_value = self._resolve_relpath(record, node.src_rel_path)
			_logger.info(f"  → FIELD raw: '{raw_value}'")

		# EXPRESSION
		elif node.value_source == "expression":
			try:
				_logger.info(f"  → EXPRESSION: evaluating '{node.value_expr}'")
				raw_value = safe_eval(
					node.value_expr,
					{
						"record": record,
						"env": record.env,
						"datetime": datetime,
						"date": date,
					}
				)
				_logger.info(f"  → EXPRESSION raw: '{raw_value}'")
			except Exception as e:
				_logger.error(f"  → EXPRESSION error: {e}")
				raise UserError(f"Błąd w expression node {node.name}: {str(e)}")

		# Formatuj wartość przed zwróceniem
		if raw_value is not None and raw_value is not False:
			# Sprawdź czy to liczba (int, float) lub string zawierający liczbę
			is_numeric_zero = False
			try:
				if isinstance(raw_value, (int, float)) and raw_value == 0:
					is_numeric_zero = True
				elif isinstance(raw_value, str) and raw_value.strip() and float(raw_value) == 0:
					is_numeric_zero = True
			except (ValueError, TypeError):
				pass
			
			if is_numeric_zero or raw_value not in ("", [], {}):
				formatted_value = self._format_xsd_value(node, raw_value, record)
				_logger.info(f"  → FINAL formatted: '{formatted_value}'")
				return formatted_value

	# ============================================================
	# ROZWIĄZANIE RELPATH
	# ============================================================
	def _resolve_relpath(self, record, rel_path):
		"""Rozwiązuje ścieżkę względną do rekordu."""
		_logger.info(f"🔍 RESOLVE_PATH: record={record._name}[{record.id}], path='{rel_path}'")
		
		if not rel_path or rel_path.strip() == "":
			_logger.warning("🚨 RESOLVE_PATH: Empty path, returning None")
			return None
			
		try:
			result = record
			for field in rel_path.split('.'):
				_logger.info(f"  → accessing field '{field}' on {result}")
				
				if not hasattr(result, field):
					_logger.error(f"  → Field '{field}' not found on {result}")
					return None
					
				result = getattr(result, field)
				
				# Jeśli wynik to False, None lub pusty string - zwróć None
				if result is None:
					_logger.warning(f"  → None value for field '{field}': {result}")
					return None
				elif isinstance(result, (int, float)) and result == 0:
					_logger.info(f"  → Numeric zero value for field '{field}': {result}")
				elif result in (False, None, ""):
					_logger.warning(f"  → Empty/False value for field '{field}': {result}")
					return None
					
				_logger.info(f"  → result: {result}")
			
			_logger.info(f"✅ RESOLVE_PATH: Success - {result}")
			return result
			
		except Exception as e:
			_logger.error(f"❌ RESOLVE_PATH: Error resolving path '{rel_path}': {e}")
			return None

	# ============================================================
	# NAMESPACE TAG
	# ============================================================
	def _qualify_tag(self, node):
		"""Zwraca kwalifikowany tag z namespace."""
		ns_uri = self.namespace or ""
		return f"{{{ns_uri}}}{node.tag}"


	## pomocnicze
	# ADD: regex walidujący format nazwy
	_NAME_RE = re.compile(
		r"^odoo-\d+(?:\.\d+)?-[a-z0-9_]+-[a-z0-9._]+-[a-z][a-z0-9_]*-\d+\.\d+\.\d+$"
	)

	def _is_valid_template_name(self, name):
		return bool(name and _NAME_RE.match(name))

	def _get_odoo_version_token(self):
		"""Zwraca token wersji Odoo w formacie <major> lub <major>.<minor>."""
		ver = (getattr(release, "version", "") or "").strip()
		# oczekujemy '19.0+e' / '18.0' / '16.0' itp.
		# bierzemy pierwsze dwa segmenty numeryczne
		parts = []
		for ch in ver:
			if ch.isdigit() or ch == '.':
				parts.append(ch)
			else:
				break
		token = "".join(parts) or "19.0"
		# uprość do major.minor
		seg = token.split(".")
		if len(seg) >= 2:
			return f"{seg[0]}.{seg[1]}"
		return seg[0] if seg else "19.0"

	def _map_direction_to_doc_type(self):
		"""Proste mapowanie kierunku na <doc_type> w nazwie."""
		mapping = {
			"out_invoice": "invoice",
			"in_invoice": "bill",
			"out_refund": "creditnote",
			"in_refund": "debitnote",
		}
		return mapping.get(self.doc_direction or "out_invoice", "bill")

	def _guess_system_from_xsd(self):
		"""Lekka heurystyka z XSD: (system, system_ver).
		Jeśli nieznane – zwraca ('custom', '1.0')."""
		# Minimalizm: patrzymy tylko w targetNamespace, jeśli mamy skrót w modelu
		ns = (self.namespace or "").lower()
		if "peppol" in ns:
			return ("peppol", "bis3")
		if "oasis" in ns or "ubl" in ns:
			return ("ubl", "2.3")
		if "x12" in ns:
			return ("x12", "4010")
		# brak jednoznacznych wskazówek
		return ("custom", "1.0")

	def _default_tpl_semver(self):
		return "1.0.0"

	def _compose_template_name(self):
		"""Składa nazwę wg formatu. Nie zapisuje, zwraca string."""
		odoo_ver = self._get_odoo_version_token()
		system, system_ver = self._guess_system_from_xsd()
		doc_type = self._map_direction_to_doc_type()
		tpl_semver = self._default_tpl_semver()
		return f"odoo-{odoo_ver}-{system}-{system_ver}-{doc_type}-{tpl_semver}"

	def _ensure_name_after_xsd_and_direction(self):
		"""Jeśli nazwa pusta lub niepoprawna – składa nową i ustawia."""
		for rec in self:
			if not rec._is_valid_template_name(rec.name):
				rec.name = rec._compose_template_name()
	## End pomocnicze

	def action_cancel(self):
		pass

	def _clear_existing_nodes(self):
		"""Usuwa wszystkie węzły xml.export.node powiązane z tym szablonem.
		Nie rzuca wyjątków – loguje i kończy cicho, jeśli nie ma nic do usunięcia.
		"""
		self.ensure_one()
		try:
			Node = self.env["xml.export.node"]
			existing = Node.search([("template_id", "=", self.id)])
			count = len(existing)
			if count:
				_logger.info("🧹 Czyszczenie %s węzłów XML (template_id=%s)", count, self.id)
				existing.unlink()
			else:
				_logger.info("🧹 Brak istniejących węzłów do usunięcia (template_id=%s)", self.id)
			# resetuj stan po czyszczeniu
			self.state = 'draft'
		except Exception as e:
			# żadnych błędów krytycznych – tylko log, żeby nie blokować importu
			_logger.warning("⚠️ Błąd podczas czyszczenia węzłów dla template_id=%s: %s", self.id, e)

	xsd_type_attachment_ids = fields.Many2many(
		'ir.attachment',
		'xml_template_xsd_type_rel',
		'template_id', 'attachment_id',
		string="Pliki definicji typów XSD",
		help="Załączniki zawierające definicje typów (np. schema.xsd, StrukturyDanych_v10-0E.xsd, dodatkowe include/import)."
	)

	def action_import_xsd_types(self):
		self.ensure_one()
		from lxml import etree
		ns = {"xsd": "http://www.w3.org/2001/XMLSchema"}

		xml_data = self.xsd_attachment_id.raw
		_logger.info(f'\n🚩🚩🚩 action_import_xsd_types\nxml_data')
		root = etree.fromstring(xml_data)
		imports = root.findall(".//xsd:import", ns) + root.findall(".//xsd:include", ns)
		urls = [x.attrib.get("schemaLocation") for x in imports if x.attrib.get("schemaLocation")]

		if urls:
			return {
				"type": "ir.actions.act_window",
				"res_model": "xml.xsd.import.wizard",
				"view_mode": "form",
				"target": "new",
				"context": {"active_id": self.id},
			}

		# jeśli nie ma importów → normalny import lokalny
		return self._import_xsd_types_from_attachments()

	################################################################################################################ NEW Inline
	def _import_xsd_types_from_attachments(self):
		"""
		Importuje katalog nazwanych typów XSD i ich elementów.

		Zasady:
		- xml.xsd.type powstaje wyłącznie dla globalnego, nazwanego
		  xs:simpleType albo xs:complexType;
		- anonimowe typy inline nie otrzymują sztucznych nazw i nie tworzą
		  rekordów xml.xsd.type;
		- dla anonimowego xs:simpleType element przechowuje rzeczywisty typ
		  bazowy restriction/list/union, jeżeli został podany;
		- brak definicji zależnej nie blokuje importu dostępnych typów;
		  nierozwiązane odwołanie zachowuje oryginalny QName i trafia
		  do raportu;
		- metoda nie tworzy, nie usuwa i nie modyfikuje xml.export.node;
		- ponowny import aktualizuje typy i odbudowuje ich element_ids.

		Model xml.xsd.type identyfikuje obecnie rekord nazwą lokalną.
		Jeżeli ta sama nazwa występuje w kilku namespace, pierwszeństwo ma
		definicja z głównego XSD, a pozostałe wystąpienia są raportowane.
		"""
		self.ensure_one()

		if not self.xsd_attachment_id:
			raise UserError(_("Brak głównego pliku XSD."))

		Type = self.env["xml.xsd.type"]
		Element = self.env["xml.xsd.element"]
		xsd_ns = "http://www.w3.org/2001/XMLSchema"
		xsd_tag = f"{{{xsd_ns}}}"

		parser = etree.XMLParser(
			resolve_entities=False,
			no_network=True,
			recover=False,
		)

		# Główny XSD zawsze jest pierwszy. Kolejność dodatkowych załączników
		# pozostaje stabilna według ID.
		attachments = [self.xsd_attachment_id]
		seen_attachment_ids = {self.xsd_attachment_id.id}
		for attachment in self.xsd_type_attachment_ids.sorted("id"):
			if attachment.id in seen_attachment_ids:
				continue
			seen_attachment_ids.add(attachment.id)
			attachments.append(attachment)

		schemas = []
		import_warnings = []
		for attachment in attachments:
			xml_data = attachment.raw
			if not xml_data and attachment.datas:
				xml_data = base64.b64decode(attachment.datas)
			if not xml_data:
				message = _(
					"Załącznik XSD „%s” nie zawiera danych.",
					attachment.name,
				)
				if attachment == self.xsd_attachment_id:
					raise UserError(message)
				import_warnings.append(message)
				continue

			try:
				root = etree.fromstring(xml_data, parser=parser)
			except Exception as error:
				message = _(
					"Nie można sparsować XSD „%(name)s”: %(error)s",
					name=attachment.name,
					error=error,
				)
				if attachment == self.xsd_attachment_id:
					raise UserError(message) from error
				import_warnings.append(message)
				continue

			if etree.QName(root).namespace != xsd_ns:
				message = _(
					"Załącznik „%s” nie jest schematem XSD.",
					attachment.name,
				)
				if attachment == self.xsd_attachment_id:
					raise UserError(message)
				import_warnings.append(message)
				continue

			schemas.append({
				"attachment": attachment,
				"root": root,
				"namespace": root.get("targetNamespace") or "",
			})

		main_namespace = schemas[0]["namespace"]

		def schema_namespace(xml_node):
			return (
				xml_node.getroottree().getroot().get("targetNamespace")
				or ""
			)

		def local_name(value):
			if not value or not isinstance(value, str):
				return None
			if value.startswith("{"):
				return value.rsplit("}", 1)[-1]
			return value.split(":")[-1]

		def resolve_qname(value, context_node):
			if not value:
				return "", None
			if ":" in value:
				prefix, name = value.split(":", 1)
				namespace = context_node.nsmap.get(prefix)
				if namespace is None:
					return None, name
				return namespace or "", name
			return (
				context_node.nsmap.get(None)
				or schema_namespace(context_node),
				value,
			)

		# Rejestry przechowują wyłącznie komponenty globalne, czyli
		# bezpośrednie dzieci xs:schema.
		component_tags = {
			"type": ("simpleType", "complexType"),
			"simple_type": ("simpleType",),
			"complex_type": ("complexType",),
			"element": ("element",),
			"attribute": ("attribute",),
			"group": ("group",),
			"attribute_group": ("attributeGroup",),
		}
		components = {
			kind: {}
			for kind in component_tags
		}

		for schema in schemas:
			root = schema["root"]
			namespace = schema["namespace"]
			for kind, tag_names in component_tags.items():
				for tag_name in tag_names:
					for definition in root.findall(f"{xsd_tag}{tag_name}"):
						name = definition.get("name")
						if not name:
							continue
						key = (namespace, name)
						components[kind].setdefault(key, []).append({
							"definition": definition,
							"attachment": schema["attachment"],
							"namespace": namespace,
						})

		duplicate_component_errors = []
		for kind in (
			"simple_type",
			"complex_type",
			"element",
			"attribute",
			"group",
			"attribute_group",
		):
			for (namespace, name), definitions in components[kind].items():
				serialized = {
					etree.tostring(item["definition"])
					for item in definitions
				}
				if len(serialized) > 1:
					duplicate_component_errors.append(
						_(
							"%(kind)s „%(name)s” ma kilka różnych definicji "
							"w namespace „%(namespace)s”.",
							kind=kind,
							name=name,
							namespace=namespace or "(brak)",
						)
					)

		import_warnings.extend(duplicate_component_errors)

		def get_component(kind, qname, context_node):
			namespace, name = resolve_qname(qname, context_node)
			if namespace is None:
				return None, _(
					"Nieznany prefiks w QName „%s”.", qname
				)
			definitions = components[kind].get((namespace, name), [])
			if not definitions:
				return None, _(
					"Brak definicji %(kind)s „%(qname)s” "
					"(namespace „%(namespace)s”).",
					kind=kind,
					qname=qname,
					namespace=namespace or "(brak)",
				)
			return definitions[0]["definition"], None

		# ----------------------------------------------------------
		# Inwentaryzacja brakujących odwołań. Nie blokuje importu.
		# ----------------------------------------------------------
		missing_definitions = set()

		def check_reference(kind, value, context_node):
			if not value:
				return
			namespace, name = resolve_qname(value, context_node)
			if namespace is None:
				missing_definitions.add(
					_("Nieznany prefiks w QName „%s”.", value)
				)
				return
			if kind == "type" and namespace == xsd_ns:
				return
			if (namespace, name) not in components[kind]:
				missing_definitions.add(
					_(
						"Brak %(kind)s „%(value)s” "
						"(namespace „%(namespace)s”).",
						kind=kind,
						value=value,
						namespace=namespace or "(brak)",
					)
				)

		for schema in schemas:
			for xml_node in schema["root"].iter():
				if not isinstance(xml_node.tag, str):
					continue

				tag = local_name(xml_node.tag)

				check_reference(
					"type",
					xml_node.get("type"),
					xml_node,
				)
				check_reference(
					"type",
					xml_node.get("base"),
					xml_node,
				)
				check_reference(
					"type",
					xml_node.get("itemType"),
					xml_node,
				)
				for member_type in (
					xml_node.get("memberTypes") or ""
				).split():
					check_reference("type", member_type, xml_node)

				ref = xml_node.get("ref")
				if not ref:
					continue
				if tag == "element":
					check_reference("element", ref, xml_node)
				elif tag == "attribute":
					check_reference("attribute", ref, xml_node)
				elif tag == "group":
					check_reference("group", ref, xml_node)
				elif tag == "attributeGroup":
					check_reference("attribute_group", ref, xml_node)

		import_warnings.extend(sorted(missing_definitions))

		# ----------------------------------------------------------
		# Wybór nazwanych typów do obecnego modelu xml.xsd.type.
		# Nazwa rekordu zawsze jest oryginalnym @name z XSD.
		# ----------------------------------------------------------
		type_candidates_by_name = {}
		for component_kind, category in (
			("simple_type", "simple"),
			("complex_type", "complex"),
		):
			for (namespace, name), definitions in components[
				component_kind
			].items():
				type_candidates_by_name.setdefault(name, []).append({
					"name": name,
					"namespace": namespace,
					"category": category,
					"definition": definitions[0]["definition"],
					"attachment": definitions[0]["attachment"],
				})

		selected_types = {}
		for name, candidates in sorted(type_candidates_by_name.items()):
			if len(candidates) == 1:
				selected_types[name] = candidates[0]
				continue

			main_candidates = [
				candidate
				for candidate in candidates
				if candidate["namespace"] == main_namespace
			]
			if len(main_candidates) == 1:
				selected = main_candidates[0]
			else:
				# Obecny model nie przechowuje namespace typu. Nie tworzymy
				# sztucznych nazw; wybór jest stabilny według kolejności
				# załączników, a konflikt zostaje jawnie zaraportowany.
				attachment_positions = {
					schema["attachment"].id: position
					for position, schema in enumerate(schemas)
				}
				selected = sorted(
					candidates,
					key=lambda candidate: (
						attachment_positions[candidate["attachment"].id],
						candidate["namespace"],
					),
				)[0]

			selected_types[name] = selected
			import_warnings.append(
				_(
					"Typ „%(name)s” występuje w kilku namespace. "
					"Użyto definicji z „%(selected)s”; pominięto: %(other)s.",
					name=name,
					selected=selected["namespace"] or "(brak)",
					other=", ".join(
						sorted({
							candidate["namespace"] or "(brak)"
							for candidate in candidates
							if candidate is not selected
						})
					),
				)
			)

		def documentation(definition):
			doc = definition.find(
				f"{xsd_tag}annotation/{xsd_tag}documentation"
			)
			if doc is None:
				return False
			return " ".join("".join(doc.itertext()).split()) or False

		def integer_facet(restriction, tag_name, default=False):
			facet = restriction.find(f"{xsd_tag}{tag_name}")
			if facet is None:
				return default
			try:
				return int(facet.get("value"))
			except (TypeError, ValueError):
				return default

		def simple_type_values(definition):
			values = {
				"base_type": False,
				"pattern": False,
				"min_length": False,
				"max_length": False,
				"enumeration": False,
				"documentation": documentation(definition),
			}
			restriction = definition.find(f"{xsd_tag}restriction")
			if restriction is not None:
				values["base_type"] = restriction.get("base") or False
				patterns = [
					item.get("value")
					for item in restriction.findall(f"{xsd_tag}pattern")
					if item.get("value") is not None
				]
				if len(patterns) == 1:
					values["pattern"] = patterns[0]
				elif len(patterns) > 1:
					import_warnings.append(
						_(
							"Typ „%(name)s” zawiera %(count)s facety pattern. "
							"Pole xml.xsd.type.pattern nie pozwala zapisać ich "
							"bez utraty semantyki; pattern pozostawiono pusty.",
							name=definition.get("name"),
							count=len(patterns),
						)
					)

				enumerations = [
					item.get("value")
					for item in restriction.findall(f"{xsd_tag}enumeration")
					if item.get("value") is not None
				]
				if enumerations:
					values["enumeration"] = json.dumps(
						enumerations,
						ensure_ascii=False,
					)

				values["min_length"] = integer_facet(
					restriction,
					"minLength",
				)
				values["max_length"] = integer_facet(
					restriction,
					"maxLength",
				)

				optional_facets = {
					"length": ("length", -1),
					"total_digits": ("totalDigits", -1),
					"fraction_digits": ("fractionDigits", -1),
					"min_inclusive": ("minInclusive", False),
					"max_inclusive": ("maxInclusive", False),
					"min_exclusive": ("minExclusive", False),
					"max_exclusive": ("maxExclusive", False),
					"white_space": ("whiteSpace", False),
				}
				for field_name, (tag_name, default) in optional_facets.items():
					if field_name not in Type._fields:
						continue
					facet = restriction.find(f"{xsd_tag}{tag_name}")
					value = facet.get("value") if facet is not None else default
					if field_name in {
						"length",
						"total_digits",
						"fraction_digits",
					} and value not in (False, None):
						try:
							value = int(value)
						except (TypeError, ValueError):
							value = default
					values[field_name] = value
				return values

			list_node = definition.find(f"{xsd_tag}list")
			if list_node is not None:
				values["base_type"] = list_node.get("itemType") or False
				return values

			union_node = definition.find(f"{xsd_tag}union")
			if union_node is not None:
				values["base_type"] = union_node.get("memberTypes") or False
			return values

		# Duplikaty istniejących rekordów dotyczące rzeczywistych nazw typów
		# uniemożliwiają bezpieczną aktualizację.
		existing_types = Type.search([
			("template_id", "=", self.id),
			("name", "in", list(selected_types)),
		])
		existing_by_name = {}
		for xsd_type in existing_types:
			existing_by_name.setdefault(xsd_type.name, Type.browse())
			existing_by_name[xsd_type.name] |= xsd_type

		duplicate_existing = {
			name: records.ids
			for name, records in existing_by_name.items()
			if len(records) > 1
		}
		if duplicate_existing:
			for name, record_ids in sorted(duplicate_existing.items()):
				import_warnings.append(
					_(
						"Szablon zawiera kilka rekordów typu „%(name)s”: "
						"%(ids)s. Zaktualizowano rekord o najniższym ID; "
						"pozostałych nie zmieniono.",
						name=name,
						ids=record_ids,
					)
				)
				existing_by_name[name] = existing_by_name[name].sorted("id")[:1]

		created_types = 0
		updated_types = 0
		type_records = {}

		for name, specification in selected_types.items():
			values = {
				"name": name,
				"category": specification["category"],
				"template_id": self.id,
				"company_id": self.company_id.id,
				"base_type": False,
				"pattern": False,
				"min_length": False,
				"max_length": False,
				"enumeration": False,
				"documentation": documentation(
					specification["definition"]
				),
			}
			if specification["category"] == "simple":
				values.update(
					simple_type_values(specification["definition"])
				)

			xsd_type = existing_by_name.get(name)
			if xsd_type:
				xsd_type.write(values)
				updated_types += 1
			else:
				xsd_type = Type.with_company(self.company_id).create(values)
				created_types += 1
			type_records[name] = xsd_type

		# ----------------------------------------------------------
		# Efektywne elementy i atrybuty typów złożonych.
		# ----------------------------------------------------------
		def resolve_declaration(declaration, kind):
			ref = declaration.get("ref")
			if not ref:
				return declaration
			component, error = get_component(kind, ref, declaration)
			if error:
				import_warnings.append(error)
				return declaration
			return component

		def collect_particle(container, visited_groups=None):
			visited_groups = set(visited_groups or ())
			result = []
			for child in container:
				tag = local_name(child.tag)
				if tag == "element":
					result.append(child)
				elif tag in ("sequence", "choice", "all"):
					result.extend(
						collect_particle(child, visited_groups)
					)
				elif tag == "group":
					ref = child.get("ref")
					if not ref:
						result.extend(
							collect_particle(child, visited_groups)
						)
						continue
					namespace, name = resolve_qname(ref, child)
					group_key = (namespace, name)
					if group_key in visited_groups:
						continue
					group, error = get_component("group", ref, child)
					if error:
						import_warnings.append(error)
						continue
					result.extend(
						collect_particle(
							group,
							visited_groups | {group_key},
						)
					)
			return result

		def collect_attributes(container, visited_groups=None):
			visited_groups = set(visited_groups or ())
			result = []
			for child in container:
				tag = local_name(child.tag)
				if tag == "attribute":
					result.append(child)
				elif tag == "attributeGroup":
					ref = child.get("ref")
					if not ref:
						result.extend(
							collect_attributes(child, visited_groups)
						)
						continue
					namespace, name = resolve_qname(ref, child)
					group_key = (namespace, name)
					if group_key in visited_groups:
						continue
					group, error = get_component(
						"attribute_group",
						ref,
						child,
					)
					if error:
						import_warnings.append(error)
						continue
					result.extend(
						collect_attributes(
							group,
							visited_groups | {group_key},
						)
					)
			return result

		def complex_members(definition, visited_types=None):
			visited_types = set(visited_types or ())
			type_key = (
				schema_namespace(definition),
				definition.get("name"),
			)
			if type_key in visited_types:
				return [], []
			visited_types.add(type_key)

			content = definition.find(f"{xsd_tag}complexContent")
			if content is None:
				content = definition.find(f"{xsd_tag}simpleContent")
			if content is None:
				return (
					collect_particle(definition),
					collect_attributes(definition),
				)

			extension = content.find(f"{xsd_tag}extension")
			restriction = content.find(f"{xsd_tag}restriction")
			derivation = extension if extension is not None else restriction
			if derivation is None:
				return [], []

			base_elements = []
			base_attributes = []
			base = derivation.get("base")
			if base:
				namespace, base_name = resolve_qname(base, derivation)
				if namespace != xsd_ns:
					base_definition = components["complex_type"].get(
						(namespace, base_name),
						[],
					)
					if base_definition:
						base_elements, base_attributes = complex_members(
							base_definition[0]["definition"],
							visited_types,
						)

			own_elements = collect_particle(derivation)
			own_attributes = collect_attributes(derivation)
			if extension is not None:
				return (
					base_elements + own_elements,
					base_attributes + own_attributes,
				)
			return own_elements, own_attributes

		def inline_base_type(declaration):
			inline_simple = declaration.find(f"{xsd_tag}simpleType")
			if inline_simple is not None:
				restriction = inline_simple.find(f"{xsd_tag}restriction")
				if restriction is not None:
					return restriction.get("base") or False
				list_node = inline_simple.find(f"{xsd_tag}list")
				if list_node is not None:
					return list_node.get("itemType") or False
				union_node = inline_simple.find(f"{xsd_tag}union")
				if union_node is not None:
					return union_node.get("memberTypes") or False

			inline_complex = declaration.find(f"{xsd_tag}complexType")
			if inline_complex is not None:
				content = inline_complex.find(f"{xsd_tag}simpleContent")
				if content is not None:
					derivation = content.find(f"{xsd_tag}extension")
					if derivation is None:
						derivation = content.find(f"{xsd_tag}restriction")
					if derivation is not None:
						return derivation.get("base") or False
			return False

		def declaration_values(declaration, kind):
			resolved = resolve_declaration(declaration, kind)
			name = resolved.get("name") or local_name(
				declaration.get("ref")
			)
			declared_type = resolved.get("type")
			if not declared_type:
				declared_type = inline_base_type(resolved)

			if kind == "attribute":
				min_occurs = (
					1
					if declaration.get("use", resolved.get("use")) == "required"
					else 0
				)
				max_occurs = "1"
			else:
				try:
					min_occurs = int(declaration.get("minOccurs", "1"))
				except (TypeError, ValueError):
					min_occurs = 1
				max_occurs = declaration.get("maxOccurs", "1")

			return {
				"name": name,
				"type": declared_type or False,
				"min_occurs": min_occurs,
				"max_occurs": max_occurs,
				"is_attribute": kind == "attribute",
			}

		# Rebuild wyłącznie elementów należących do typów synchronizowanych
		# przez tę metodę. Rekordy typów zachowują swoje ID.
		synchronized_type_ids = [
			type_records[name].id
			for name, specification in selected_types.items()
			if specification["category"] == "complex"
		]
		if synchronized_type_ids:
			Element.search([
				("type_id", "in", synchronized_type_ids),
			]).unlink()

		created_elements = 0
		for name, specification in selected_types.items():
			if specification["category"] != "complex":
				continue

			owner_type = type_records[name]
			element_declarations, attribute_declarations = complex_members(
				specification["definition"]
			)
			seen_elements = set()

			for kind, declarations in (
				("element", element_declarations),
				("attribute", attribute_declarations),
			):
				for declaration in declarations:
					values = declaration_values(declaration, kind)
					if not values["name"]:
						continue
					key = (
						values["name"],
						values["type"],
						values["min_occurs"],
						values["max_occurs"],
						values["is_attribute"],
					)
					if key in seen_elements:
						continue
					seen_elements.add(key)

					Element.with_company(self.company_id).create({
						**values,
						"type_id": owner_type.id,
						"company_id": self.company_id.id,
					})
					created_elements += 1

		html = (
			"<b>Import typów XSD</b><br><br>"
			f"• Przetworzone pliki: {len(schemas)}<br>"
			f"• Typy utworzone: {created_types}<br>"
			f"• Typy zaktualizowane: {updated_types}<br>"
			f"• Elementy i atrybuty typów: {created_elements}<br>"
			"• Sztuczne typy Inline: 0<br>"
		)
		if import_warnings:
			html += "<br><b>Ostrzeżenia:</b><br>"
			for warning in dict.fromkeys(import_warnings):
				html += f"• {escape(warning)}<br>"

		self.message_post(
			body=Markup(html),
			subject=_("Import typów XSD"),
			message_type="comment",
			subtype_xmlid="mail.mt_note",
		)

		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.xsd.type",
			"view_mode": "list,form",
			"domain": [("template_id", "=", self.id)],
			"name": _("Typy XSD"),
		}

	################################################################################################################ END Inline
	def action_open_xsd_upload_wizard(self):
		"""Otwiera wizard do wgrania pliku XSD i podpięcia jako attachment.
		Widoczny/wywoływany, gdy xsd_attachment_id jest puste."""
		self.ensure_one()
		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.template.xsd.upload.wizard",
			"view_mode": "form",
			"target": "new",
			"context": {
				"default_template_id": self.id,
			},
		}

	def _set_xsd_attachment(self, attachment):
		"""Ustawia pole xsd_attachment_id wskazując istniejący ir.attachment."""
		self.ensure_one()
		if not attachment or attachment._name != "ir.attachment":
			raise UserError(_("Oczekiwano rekordu ir.attachment."))
		self.xsd_attachment_id = attachment.id
		return True


	def action_reset_nodes(self):
		"""Usuwa wszystkie węzły XML przypisane do szablonu, zachowując jego konfigurację."""
		self.ensure_one()
		count = self.env["xml.export.node"].search_count([("template_id", "=", self.id)])
		if not count:
			self.message_post(body=_("Brak węzłów do usunięcia."))
			return
		self._clear_existing_nodes()
		self.message_post(body=_("Wyczyszczono %s węzłów XML z szablonu.") % count)
		_logger.info("🧹 Resetowano %s węzłów w szablonie '%s'", count, self.name)

	def generate_preview_xml(self, record):
		"""
		Generuje przykładowy XML na podstawie mapowania z tego szablonu,
		dla przekazanego rekordu (np. faktury account.move),
		bez zapisu pliku na dysk lub w załącznikach.
		"""
		self.ensure_one()
		xml_str = self.generate_xml(record, in_memory=True)
		return xml_str

# ==========================
# LISTA PRZESTRZENI NAZW XML
# ==========================
class XmlExportNamespace(models.Model):
	_name = "xml.export.namespace"
	_description = "Przestrzeń nazw XML (prefiks ↔ URI)"
	_order = "sequence, id"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=False,  # <-- opcjonalne
		default=lambda self: self.env.company,
		ondelete='set null'
	)

	template_id = fields.Many2one("xml.export.template", required=True, ondelete="cascade", index=True)
	sequence = fields.Integer(default=10)
	prefix = fields.Char(required=True, help="Nazwa prefiksu, np. 'tns', 'xsi'.")
	uri = fields.Char(required=True, help="Pełny URI przestrzeni nazw.")
	is_default = fields.Boolean(string="Domyślna", help="Jeśli zaznaczone, używana dla elementów bez prefiksu.")


# ==========================
# WĘZEŁ / GAŁĄŹŹ XML (XPATH)
# ==========================
class XmlExportNode(models.Model):
	_name = "xml.export.node"
	_description = "Węzeł eksportu XML / XPath"
	_inherit = ['mail.thread']
	_order = "sequence, id"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	# Powiązanie z szablonem i hierarchią
	template_id = fields.Many2one("xml.export.template", required=True, ondelete="cascade", index=True)

	# WAŻNE: używaj w kodzie: nodes = template.node_ids.sorted(key=lambda n: n.sequence)
	sequence = fields.Integer(
		string="Sequence",
		default=10,
		index=True,
		help="Kolejność generowania węzłów XML"
	)
	_sql_constraints = [
		('sequence_positive', 'CHECK(sequence >= 0)', 'Sequence musi być >= 0')
	]
	snapshot_sequence = fields.Integer(
		string="Snapshot Sequence",
		copy=False,
		help="Zapamiętana wartość sequence do przywrócenia"
	)

	parent_id = fields.Many2one("xml.export.node", string="Rodzic", ondelete="cascade", index=True, domain="[('template_id', '=', template_id)]")
	child_ids = fields.One2many("xml.export.node", "parent_id", string="Dzieci")
	template_model_id = fields.Many2one(
		"ir.model",
		related="template_id.model_id",
		store=True,
		readonly=True,
		string="Model z szablonu"
	)

	# Status węzła
	state = fields.Selection([
		('draft', 'W przygotowaniu'),
		('validated', 'Zweryfikowany'),
		('warning', 'Ostrzeżenie'),
		('error', 'Błędny'),
	], string="Status", default="draft", tracking=True)

	# Rodzaj węzła
	node_kind = fields.Selection([
		("element", "Element"),
		("attribute", "Atrybut"),
		("text", "Tekst (#text)"),
	], required=True, default="element", help="Typ węzła w drzewie XML.")

	# Nazwa i namespace
	xpath = fields.Char(
		compute="_compute_xpath",
		string="XPath (pełna ścieżka)",
		index=True,
		store=True,
		help="Pełna ścieżka do węzła w strukturze XML (np. Faktura/Fa/Adnotacje/P_23)."
	)
	name = fields.Char(required=True, help="Nazwa węzła w XML (bez prefiksu). Dla atrybutu: nazwa atrybutu.")
	ns_prefix = fields.Char(string="Prefiks", help="Nadpisuje prefiks z szablonu (opcjonalnie).")
	namespace_uri = fields.Char(string="URI NS", help="Nadpisuje URI przestrzeni nazw (opcjonalnie).")
	uuid = fields.Char(string='UUID', translate=False, store=True)
	version = fields.Char(string='Version', translate=False, store=True)

	as_cdata = fields.Boolean(default=False)

	# Porządek i opcje emisji
	emit_empty = fields.Selection([
		("always", "Zawsze"),
		("never", "Nigdy"),
		("if-required", "Jeśli wymagane (XSD)"),
	], default="if-required", string="Emisja pustych")
	zero_policy = fields.Selection([
		("emit", "Emituj 0"),
		("omit", "Pomiń, jeśli 0"),
	], default="emit", string="Zachowanie wartości 0")

	# ----------------------
	# METADANE XSD (STATYCZNE)
	# ----------------------
	type_id = fields.Many2one('xml.xsd.type', string="XSD Type", domain="[('template_id', '=', template_id)]")
	def get_type_constraints(self):
		self.ensure_one()
		if self.type_id:
			return {
				"pattern": self.type_id.pattern,
				"enumeration": self.type_id.enumeration,
				"base_type": self.type_id.base_type,
			}
		return {}

	xsd_type_name = fields.Char( related="type_id.name", string="Typ XSD (nazwa)")
	xsd_type_kind = fields.Selection([
		("simple", "SimpleType"),
		("complex", "ComplexType"),
		("builtin", "Wbudowany (xs:string itd.)"),
	], string="Kategoria typu")
	xsd_min_occurs = fields.Char(string="minOccurs")
	xsd_max_occurs = fields.Char(string="maxOccurs")
	xsd_nillable = fields.Boolean(string="nillable")
	xsd_default = fields.Char(string="default")
	xsd_fixed = fields.Char(string="fixed")
	xsd_documentation = fields.Text(string="Dokumentacja XSD")
	xsd_enumeration = fields.Text(string="Dopuszczalne wartości (enum)", help="Lista/JSON/CSV – do walidacji biznesowej.")

	# ----------------------
	# ŹRÓDŁO WARTOŚCI (ODOO)
	# ----------------------
	value_source = fields.Selection([
		("field", "Pole Odoo"),
		("related", "Ścieżka relacji (dot-path)"),
		("constant", "Stała"),
		("expression", "Wyrażenie (safe_eval)"),
		("context", "Z kontekstu"),
		("sequence", "Licznik/sekwencja"),
		("attachment_b64", "Załącznik (base64)"),
		("literal_xml", "Literal XML (bez escape)"),
		("none", "Brak (tylko kontener)"),
	], default="none", required=True, string="Źródło wartości")

	value_fixed = fields.Char(string="Stała wartość")
	value_sequence_name = fields.Char(string="Sekwencja (nazwa w ir.sequence)")
	value_attachment_field = fields.Char(string="Pole binarne (base64)")
	value_literal = fields.Text(string="Literal XML (bez escape)")

	# Model/pole bezpośrednie
	# Ścieżka przez relacje (np. partner_id.bank_ids[0].acc_number)
	src_rel_path = fields.Char(string="RelPath (dot)", help="Np. partner_id.vat lub move_id.invoice_date. Indeksy w nawiasach [].")

	# Źródło danych Odoo (bezpieczne mapowanie)
	src_field_id = fields.Many2one(
		"ir.model.fields",
		string="Pole bazowe",
		required=False,
		domain="[('model_id', '=', template_model_id)]",
		help="Pole z głównego modelu szablonu. Dla relacyjnych typów można określić dalsze szczegóły poniżej."
	)

	src_field_type = fields.Selection(
		selection=[
			("char", "Char"),
			("boolean", "Boolean"),
			("integer", "Integer"),
			("float", "Float"),
			("monetary", "Monetary"),
			("date", "Date"),
			("datetime", "Datetime"),
			("many2one", "Many2one"),
			("one2many", "One2many"),
			("many2many", "Many2many"),
			("binary", "Binary"),
			("text", "Text"),
		],
		string="Typ pola",
		help="Określony typ pola źródłowego (pomocniczo do walidacji formatu i konwersji)."
	)

	# Relacje – tylko dla pól relacyjnych
	src_model_id = fields.Many2one(
		"ir.model",
		string="Model relacji",
		help="Model docelowy, jeśli pole jest relacyjne (np. partner_id → res.partner)."
	)

	src_model_field_id = fields.Many2one(
		"ir.model.fields",
		string="Pole w modelu relacji",
		domain="[('model_id', '=', src_model_id)]",
		help="Pole w modelu relacji, z którego ma być pobrana wartość (np. vat, name, street...)."
	)

	# Stała / wyrażenie / kontekst
	value_constant = fields.Text(string="Stała (tekst/liczba)")
	value_expr = fields.Text(string="Wyrażenie (safe_eval)", help="Bez metod – samo przechowywanie.")
	context_key = fields.Char(string="Klucz z context", help="Jeśli źródło = context.")

	# PĘTLE / KOLEKCJE (dla maxOccurs>1)
	loop_mode = fields.Selection([
		("none", "Brak (pojedynczy węzeł)"),
		("one2many", "Po 1..n z pola one2many"),
		("many2many", "Po 1..n z pola many2many"),
		("domain", "Po rekordach z domeny"),
	], default="none", string="Iteracja")
	loop_model_id = fields.Many2one("ir.model", string="Model iteracji")
	loop_rel_field_id = fields.Many2one(
		"ir.model.fields",
		string="Pole kolekcji (o2m/m2m)",
		domain="[('model_id', '=', loop_model_id)]",
		help="Dla loop_mode = one2many/many2many"
	)
	loop_domain = fields.Text(string="Domena (tekst/JSON)", help="Dla loop_mode=domain")
	loop_order = fields.Char(string="Sortowanie", help="Np. 'sequence asc, id asc'")
	loop_limit = fields.Integer(string="Limit")

	# WARUNKI / FILTRY
	condition_expr = fields.Text(string="Warunek emisji (safe_eval)", help="Gdy False – węzeł pomijany.")
	required_flag = fields.Boolean(string="Wymagany (biznesowo)", help="Dodatkowo względem XSD.")

	# FORMATOWANIE WARTOŚCI
	fmt_date = fields.Char(string="Format daty", help="np. %Y-%m-%d")
	fmt_datetime = fields.Char(string="Format datetime", help="np. %Y-%m-%dT%H:%M:%S")
	fmt_bool_true = fields.Char(string="Bool TRUE", default="true")
	fmt_bool_false = fields.Char(string="Bool FALSE", default="false")
	fmt_decimal_precision = fields.Integer(string="Precyzja dziesiętna")
	fmt_strip = fields.Boolean(string="Strip whitespace", default=True)
	fmt_upper = fields.Boolean(string="Uppercase", default=False)
	fmt_lower = fields.Boolean(string="Lowercase", default=False)
	fmt_pad_left = fields.Integer(string="Pad left (szerokość)")
	fmt_pad_char = fields.Char(string="Pad char", default="0")

	# Info
	notes = fields.Char("Notatki")

	@api.depends('parent_id', 'name')
	def _compute_xpath(self):
		for node in self:
			if node.parent_id:
				node.xpath = f"{node.parent_id.xpath}/{node.name}"
			else:
				node.xpath = node.name or ''

	@api.onchange("src_field_id", "src_model_field_id")
	def _onchange_compose_rel_path(self):
		for rec in self:
			if rec.src_field_id and rec.src_model_field_id:
				rec.src_rel_path = f"{rec.src_field_id.name}.{rec.src_model_field_id.name}"
			elif rec.src_field_id:
				rec.src_rel_path = rec.src_field_id.name
			else:
				rec.src_rel_path = False

	def action_open_node_form_edit(self):
		"""Otwiera formularz edycyjny węzła z dedykowanym widokiem."""
		self.ensure_one()

		view = self.env.ref("hfb_xmlmap_exporter.view_xml_export_node_form_edit", raise_if_not_found=False)

		return {
			"type": "ir.actions.act_window",
			"name": _("Edytuj węzeł XML"),
			"res_model": "xml.export.node",
			"res_id": self.id,
			"view_mode": "form",
			"views": [(view.id if view else False, "form")],
			"view_id": view.id if view else False,
			"target": "new",
			"context": dict(self.env.context),
		}

	def action_open_node_form(self):
		return {
			"type": "ir.actions.act_window",
			"name": "Edytuj węzeł XML",
			"res_model": "xml.export.node",
			"view_mode": "form",
			"view_id": self.env.ref("hfb_xmlmap_exporter.view_xml_export_node_form").id,
			"target": "new",
			"res_id": self.id,
		}


	# ===== Alias fields for JSON export compatibility =====
	tag = fields.Char(related="name", string="Tag XML", store=False)

	export_if_empty = fields.Boolean(
		string="Eksportuj jeśli puste (alias emit_empty)",
		compute="_compute_export_if_empty",
		store=False,
	)

	@api.depends("emit_empty")
	def _compute_export_if_empty(self):
		"""Mapuje emit_empty -> export_if_empty (bool dla JSON)."""
		for node in self:
			node.export_if_empty = node.emit_empty == "always"

	# zabezpieczenie przed uszkadzaniem danych
	@api.constrains("parent_id", "template_id")
	def _check_parent_template_consistency(self):
		for node in self:
			if node.parent_id and node.parent_id.template_id != node.template_id:
				raise ValidationError(
					f"Node '{node.name}' (id={node.id}) "
					f"has parent from another template "
					f"(parent.template_id={node.parent_id.template_id.id}, "
					f"node.template_id={node.template_id.id})"
				)


# ======================================================
#  DEFINICJE TYPÓW XSD (NOWA WARSTWA)
# ======================================================

class XmlXsdType(models.Model):
	_name = "xml.xsd.type"
	_description = "XSD Type Definition"
	_order = "name, namespace_uri, id"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	name = fields.Char(required=True)
	category = fields.Selection([
		('simple', 'Simple Type'),
		('complex', 'Complex Type'),
	], default='simple', required=True)
	base_type = fields.Char(string="Base Type")
	pattern = fields.Char(string="Pattern")
	min_length = fields.Integer()
	max_length = fields.Integer()
	enumeration = fields.Text(string="Enumerations (JSON)")
	documentation = fields.Text()
	template_id = fields.Many2one('xml.export.template', ondelete='cascade')
	element_ids = fields.One2many('xml.xsd.element', 'type_id', string="Child Elements")

	namespace_uri = fields.Char(
		string="Namespace URI",
		index=True,
		help="Przestrzeń nazw, w której zdefiniowano typ XSD.",
	)

class XmlXsdElement(models.Model):
	_name = "xml.xsd.element"
	_description = "XSD Element Definition"
	_order = "id"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	name = fields.Char(required=True)
	type = fields.Char(string="Rodzaj")
	type_id = fields.Many2one('xml.xsd.type', ondelete='cascade', string="typy XSD")
	min_occurs = fields.Integer(default=1)
	max_occurs = fields.Char(default='1')
	is_attribute = fields.Boolean(default=False)


#EoF

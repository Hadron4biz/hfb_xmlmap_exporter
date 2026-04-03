# -*- coding: utf-8 -*-
#####################################################################################
#   XML XSD Import Wizard for Hadron XMLMap Exporter
#   Author: Andrzej Wiśniewski / Hadron for Business
#####################################################################################

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import requests
import logging
from markupsafe import Markup, escape
import json
_logger = logging.getLogger(__name__)


class XmlXsdImportWizard(models.TransientModel):
	_name = "xml.xsd.import.wizard"
	_description = "Wizard: Import plików XSD (import/include)"

	template_id = fields.Many2one(
		"xml.export.template",
		string="Szablon",
		required=True,
		ondelete="cascade"
	)

	import_line_ids = fields.One2many(
		"xml.xsd.import.line",
		"wizard_id",
		string="Pliki XSD do pobrania"
	)

	@api.model
	def default_get(self, fields_list):
		"""Analizuje schemę główną i tworzy listę linków import/include."""
		res = super().default_get(fields_list)
		active_id = self.env.context.get("active_id")
		if not active_id:
			return res

		template = self.env["xml.export.template"].browse(active_id)
		if not template.xsd_attachment_id:
			raise UserError(_("Brak załączonej głównej schemy XSD."))

		from lxml import etree
		xml_data = template.xsd_attachment_id.raw
		ns = {"xsd": "http://www.w3.org/2001/XMLSchema"}
		root = etree.fromstring(xml_data)

		urls = []
		for tag in root.findall(".//xsd:import", ns) + root.findall(".//xsd:include", ns):
			loc = tag.attrib.get("schemaLocation")
			if loc:
				urls.append(loc)

		lines = []
		for url in sorted(set(urls)):
			lines.append((0, 0, {"url": url, "download": True}))

		res.update({
			"template_id": active_id,
			"import_line_ids": lines,
		})
		return res

	# --------------------------------------------------------------
	#  Akcje
	# --------------------------------------------------------------
	def action_confirm(self):
		"""Pobiera wybrane pliki XSD i dodaje je jako załączniki."""
		self.ensure_one()
		Template = self.template_id
		Attachment = self.env["ir.attachment"]

		if not self.import_line_ids:
			raise UserError(_("Brak plików do przetworzenia."))

		downloaded = 0
		for line in self.import_line_ids.filtered("download"):
			url = line.url.strip()
			_logger.info("🌐 Pobieranie XSD: %s", url)
			try:
				response = requests.get(url, timeout=15)
				if not response.ok:
					_logger.warning("❌ Nie udało się pobrać: %s [%s]", url, response.status_code)
					continue
				att_name = url.split("/")[-1] or "plik.xsd"
				# Nie pobieraj ponownie tego samego pliku
				existing = self.env["ir.attachment"].search([
					("res_model", "=", "xml.export.template"),
					("res_id", "=", Template.id),
					("name", "=", att_name),
				], limit=1)
				if existing:
					_logger.info("↩️  Plik %s już istnieje, pomijam pobieranie", att_name)
					continue

				att = Attachment.create({
					"name": att_name,
					"datas": base64.b64encode(response.content),
					"res_model": "xml.export.template",
					"res_id": Template.id,
					"mimetype": "application/xml",
				})
				Template.xsd_type_attachment_ids = [(4, att.id)]
				downloaded += 1
			except Exception as e:
				_logger.error("⚠️ Błąd pobierania %s: %s", url, e)

		if not downloaded:
			raise UserError(_("Nie udało się pobrać żadnego pliku XSD."))

		else:
			urls_html = "".join(f"<li>{escape(line.url)}</li>" for line in self.import_line_ids.filtered("download"))
			
			Template.message_post(
				body=Markup(
					"🌐 Zaimportowano <b>%d</b> plików XSD z import/include."
					"<br/><ul>%s</ul>" % (downloaded, urls_html)
				),
				subject=_("Import plików XSD"),
				message_type="comment",
			)

		_logger.info("✅ Pobrano %d plików XSD dla szablonu %s", downloaded, Template.name)
		#return Template.action_import_xsd_types()
		return Template._import_xsd_types_from_attachments()


class XmlXsdImportLine(models.TransientModel):
	_name = "xml.xsd.import.line"
	_description = "Pozycja pliku XSD do importu"

	wizard_id = fields.Many2one("xml.xsd.import.wizard", ondelete="cascade")
	url = fields.Char(string="Adres pliku XSD", required=True)
	download = fields.Boolean(string="Pobierz", default=True)


#EoF

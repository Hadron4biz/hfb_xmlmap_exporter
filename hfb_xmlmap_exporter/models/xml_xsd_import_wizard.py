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
"""@version 19.0.1.12.8
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
#####################################################################################
#   XML XSD Import Wizard for Hadron XMLMap Exporter
#   Author: Andrzej Wiśniewski / Hadron for Business
#####################################################################################

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
import ipaddress
import requests
import socket
import logging
from urllib.parse import urljoin, urlparse
from lxml import etree
from markupsafe import Markup, escape
_logger = logging.getLogger(__name__)


class XmlXsdImportWizard(models.TransientModel):
	_name = "xml.xsd.import.wizard"
	_description = "Wizard: Import plików XSD (import/include)"

	_MAX_XSD_SIZE = 10 * 1024 * 1024
	_MAX_REDIRECTS = 3
	_MAX_DEPENDENCY_DEPTH = 10
	_MAX_DEPENDENCY_FILES = 64
	_XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=False,  # <-- opcjonalne
		default=lambda self: self.env.company,
		ondelete='set null'
	)

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

		xml_data = template.xsd_attachment_id.raw
		ns = {"xsd": "http://www.w3.org/2001/XMLSchema"}
		parser = etree.XMLParser(
			resolve_entities=False,
			no_network=True,
			recover=False,
		)
		try:
			root = etree.fromstring(xml_data, parser=parser)
		except Exception as error:
			raise UserError(
				_("Nie można odczytać głównego XSD: %s", error)
			) from error

		urls = []
		dependency_nodes = (
			root.findall(".//xsd:import", ns)
			+ root.findall(".//xsd:include", ns)
			+ root.findall(".//xsd:redefine", ns)
		)
		for tag in dependency_nodes:
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

	def _validate_public_url(self, url):
		"""Dopuszcza wyłącznie publiczne adresy HTTP(S)."""
		parsed = urlparse(url)
		if parsed.scheme not in ("http", "https"):
			raise UserError(
				_("Schema XSD musi używać adresu http:// lub https://: %s", url)
			)
		if not parsed.hostname:
			raise UserError(_("Nieprawidłowy adres schemy XSD: %s", url))
		if parsed.username or parsed.password:
			raise UserError(
				_("Adres schemy XSD nie może zawierać danych logowania.")
			)

		try:
			addresses = socket.getaddrinfo(
				parsed.hostname,
				parsed.port or (443 if parsed.scheme == "https" else 80),
				type=socket.SOCK_STREAM,
			)
		except OSError as error:
			raise UserError(
				_(
					"Nie można rozwiązać adresu %(host)s: %(error)s",
					host=parsed.hostname,
					error=error,
				)
			) from error

		for address in addresses:
			ip = ipaddress.ip_address(address[4][0])
			if (
				ip.is_private
				or ip.is_loopback
				or ip.is_link_local
				or ip.is_multicast
				or ip.is_reserved
				or ip.is_unspecified
			):
				raise UserError(
					_("Adres schemy XSD prowadzi do niedozwolonej sieci: %s", ip)
				)
		return url

	def _parse_xsd_content(self, content, source):
		"""Waliduje XML i zwraca element xs:schema."""
		parser = etree.XMLParser(
			resolve_entities=False,
			no_network=True,
			recover=False,
		)
		try:
			root = etree.fromstring(content, parser=parser)
		except Exception as error:
			raise UserError(
				_(
					"Plik „%(source)s” nie jest poprawnym XML: %(error)s",
					source=source,
					error=error,
				)
			) from error

		if etree.QName(root).namespace != self._XSD_NAMESPACE:
			raise UserError(
				_("Plik „%s” nie posiada elementu głównego xs:schema.", source)
			)
		return root

	def _download_xsd(self, initial_url):
		"""Pobiera pojedynczy XSD z limitami rozmiaru i przekierowań."""
		current_url = initial_url
		for redirect_number in range(self._MAX_REDIRECTS + 1):
			self._validate_public_url(current_url)
			response = requests.get(
				current_url,
				timeout=(5, 20),
				allow_redirects=False,
				stream=True,
			)
			try:
				if 300 <= response.status_code < 400:
					location = response.headers.get("Location")
					if not location:
						raise UserError(
							_("Przekierowanie bez nagłówka Location: %s", current_url)
						)
					if redirect_number >= self._MAX_REDIRECTS:
						raise UserError(
							_("Przekroczono limit przekierowań dla %s", initial_url)
						)
					current_url = urljoin(current_url, location)
					continue

				if not response.ok:
					raise UserError(
						_(
							"Nie udało się pobrać %(url)s: HTTP %(status)s",
							url=current_url,
							status=response.status_code,
						)
					)

				content_length = response.headers.get("Content-Length")
				if content_length:
					try:
						if int(content_length) > self._MAX_XSD_SIZE:
							raise UserError(
								_("Plik XSD przekracza limit 10 MB: %s", current_url)
							)
					except ValueError:
						pass

				chunks = []
				total_size = 0
				for chunk in response.iter_content(chunk_size=64 * 1024):
					if not chunk:
						continue
					total_size += len(chunk)
					if total_size > self._MAX_XSD_SIZE:
						raise UserError(
							_("Plik XSD przekracza limit 10 MB: %s", current_url)
						)
					chunks.append(chunk)
				content = b"".join(chunks)
			finally:
				response.close()

			root = self._parse_xsd_content(content, current_url)
			return content, current_url, root

		raise UserError(_("Nie udało się pobrać XSD: %s", initial_url))

	def _dependency_urls(self, root, source_url):
		"""Zwraca bezwzględne URL-e import/include znalezione w XSD."""
		urls = []
		for tag_name in ("import", "include", "redefine"):
			for dependency in root.findall(
				f".//{{{self._XSD_NAMESPACE}}}{tag_name}"
			):
				location = dependency.get("schemaLocation")
				if not location:
					continue
				urls.append(urljoin(source_url, location))
		return urls

	def _attachment_name_from_url(self, url):
		"""Zwraca nazwę pliku bez query string i fragmentu URL."""
		return urlparse(url).path.rsplit("/", 1)[-1] or "plik.xsd"

	# --------------------------------------------------------------
	#  Akcje
	# --------------------------------------------------------------
	def action_confirm(self):
		"""
		Rekurencyjnie pobiera wybrane XSD oraz ich import/include.

		Brak części zależności nie blokuje późniejszego importu dostępnych
		typów. Błędy pobierania są raportowane w chatterze.
		"""
		self.ensure_one()
		Template = self.template_id
		Attachment = self.env["ir.attachment"]

		selected_lines = self.import_line_ids.filtered("download")
		if not selected_lines:
			raise UserError(_("Brak plików do przetworzenia."))

		queue = [
			(line.url.strip(), 0)
			for line in selected_lines
			if line.url and line.url.strip()
		]
		queued_urls = {url for url, unused_depth in queue}
		processed_urls = set()
		downloaded_urls = []
		reused_urls = []
		failed_urls = []

		while queue:
			if len(processed_urls) >= self._MAX_DEPENDENCY_FILES:
				failed_urls.append((
					"(kolejka zależności)",
					_(
						"Przerwano dalsze pobieranie po osiągnięciu limitu "
						"%s plików.",
						self._MAX_DEPENDENCY_FILES,
					),
				))
				break

			url, depth = queue.pop(0)
			if url in processed_urls:
				continue
			processed_urls.add(url)

			if depth > self._MAX_DEPENDENCY_DEPTH:
				failed_urls.append((
					url,
					_(
						"Przekroczono maksymalną głębokość zależności (%s).",
						self._MAX_DEPENDENCY_DEPTH,
					),
				))
				continue

			_logger.info("🌐 Pobieranie XSD (poziom %s): %s", depth, url)
			try:
				att_name = self._attachment_name_from_url(url)
				existing = Template.xsd_type_attachment_ids.filtered(
					lambda attachment: attachment.name == att_name
				)[:1]
				if not existing:
					existing = Attachment.search([
						("res_model", "=", "xml.export.template"),
						("res_id", "=", Template.id),
						("name", "=", att_name),
					], limit=1)

				if existing:
					content = existing.raw
					if not content and existing.datas:
						content = base64.b64decode(existing.datas)
					root = self._parse_xsd_content(content, existing.name)
					final_url = url
					attachment = existing
					reused_urls.append(url)
				else:
					content, final_url, root = self._download_xsd(url)
					company = Template.company_id or self.env.company
					attachment = Attachment.with_company(
						company
					).create({
						"name": self._attachment_name_from_url(final_url),
						"datas": base64.b64encode(content),
						"res_model": "xml.export.template",
						"res_id": Template.id,
						"mimetype": "application/xml",
						"company_id": company.id,
					})
					downloaded_urls.append(final_url)

				Template.write({
					"xsd_type_attachment_ids": [(4, attachment.id)],
				})

				for dependency_url in self._dependency_urls(root, final_url):
					if (
						dependency_url in processed_urls
						or dependency_url in queued_urls
					):
						continue
					queued_urls.add(dependency_url)
					queue.append((dependency_url, depth + 1))

			except Exception as error:
				_logger.exception("Błąd pobierania XSD %s", url)
				failed_urls.append((url, str(error)))

		html = (
			"🌐 Przetworzono pliki XSD z import/include.<br>"
			f"• Pobrane nowe pliki: <b>{len(downloaded_urls)}</b><br>"
			f"• Wykorzystane istniejące pliki: <b>{len(reused_urls)}</b><br>"
			f"• Błędy pobierania: <b>{len(failed_urls)}</b><br>"
		)
		if downloaded_urls:
			html += "<br><b>Pobrane:</b><ul>"
			for url in downloaded_urls:
				html += f"<li>{escape(url)}</li>"
			html += "</ul>"
		if failed_urls:
			html += "<br><b style='color:orange;'>Niepobrane:</b><ul>"
			for url, error in failed_urls:
				html += (
					f"<li>{escape(url)} — {escape(error)}</li>"
				)
			html += "</ul>"

		Template.message_post(
			body=Markup(html),
			subject=_("Import plików XSD"),
			message_type="comment",
			subtype_xmlid="mail.mt_note",
		)

		_logger.info(
			"✅ XSD dla szablonu %s: nowe=%s, istniejące=%s, błędy=%s",
			Template.name,
			len(downloaded_urls),
			len(reused_urls),
			len(failed_urls),
		)
		return Template._import_xsd_types_from_attachments()


class XmlXsdImportLine(models.TransientModel):
	_name = "xml.xsd.import.line"
	_description = "Pozycja pliku XSD do importu"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=False,  # <-- opcjonalne
		default=lambda self: self.env.company,
		ondelete='set null'
	)

	wizard_id = fields.Many2one("xml.xsd.import.wizard", ondelete="cascade")
	url = fields.Char(string="Adres pliku XSD", required=True)
	download = fields.Boolean(string="Pobierz", default=True)


#EoF

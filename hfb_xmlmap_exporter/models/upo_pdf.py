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
"""@version 18.1.0
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
import logging

_logger = logging.getLogger(__name__)


class ReportKsefUpo(models.AbstractModel):
	_name = 'report.hfb_xmlmap_exporter.report_ksef_upo'

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=False,  # <-- opcjonalne
		default=lambda self: self.env.company,
		ondelete='set null'
	)

	def _get_report_values(self, docids, data=None):
		docs = self.env['account.move'].browse(docids)
		doc = docs[0]

		return {
			'doc_ids': docids,
			'doc_model': 'account.move',
			'docs': docs,
			'o': doc,
			'upo': doc._get_ksef_upo_data(),
		}

class AccountMove(models.Model):
	_inherit = 'account.move'

	def base_action_show_ksef_upo(self):
		"""
		Wyświetla treść załącznika UPO (XML) w logu Odoo
		dla bieżącej faktury.
		"""
		self.ensure_one()

		# 1. Walidacja warunku KSeF
		if not self.ksef_number:
			raise UserError(_("Faktura nie posiada numeru KSeF."))

		# 2. Wyszukaj załącznik UPO
		attachment = self.env['ir.attachment'].search([
			('res_model', '=', 'account.move'),
			('res_id', '=', self.id),
			('mimetype', '=', 'application/xml'),
			('name', 'ilike', 'UPO_%'),
		], order='create_date desc', limit=1)

		if not attachment:
			raise UserError(_("Brak załącznika UPO powiązanego z tą fakturą."))

		# 3. Dekoduj XML
		try:
			xml_bytes = base64.b64decode(attachment.datas)
			xml_text = xml_bytes.decode('utf-8', errors='replace')
		except Exception as e:
			_logger.error("Błąd dekodowania UPO XML: %s", e, exc_info=True)
			raise UserError(_("Nie można odczytać treści załącznika UPO."))

		# 4. Wyświetl w logu Odoo
		_logger.info(
			"📄 UPO dla faktury ID=%s, KSeF=%s\n%s",
			self.id,
			self.ksef_number,
			xml_text
		)

		# 5. Informacja zwrotna dla użytkownika
		return {
			'type': 'ir.actions.client',
			'tag': 'display_notification',
			'params': {
				'title': _("UPO KSeF"),
				'message': _("Treść UPO została wypisana w logu Odoo."),
				'type': 'info',
				'sticky': False,
			}
		}

	#
	#
	def _get_ksef_upo_data(self):
		self.ensure_one()

		attachment = self.env['ir.attachment'].search([
			('res_model', '=', 'account.move'),
			('res_id', '=', self.id),
			('mimetype', '=', 'application/xml'),
			('name', 'ilike', 'UPO_%'),
		], order='create_date desc', limit=1)

		if not attachment:
			raise UserError(_("Brak załącznika UPO."))

		xml_bytes = base64.b64decode(attachment.datas)

		import xml.etree.ElementTree as ET
		root = ET.fromstring(xml_bytes)

		def find(local_name):
			for el in root.iter():
				if el.tag.endswith(local_name):
					return el.text
			return None

		return {
			# Nagłówek
			'nazwa_podmiotu': find('NazwaPodmiotuPrzyjmujacego'),
			'numer_sesji': find('NumerReferencyjnySesji'),

			# Uwierzytelnienie
			'nip': find('Nip'),
			'skrot_uwierzytelniajacy': find('SkrotDokumentuUwierzytelniajacego'),

			# Opis potwierdzenia
			'strona': find('Strona'),
			'liczba_stron': find('LiczbaStron'),
			'zakres_od': find('ZakresDokumentowOd'),
			'zakres_do': find('ZakresDokumentowDo'),
			'liczba_dokumentow': find('CalkowitaLiczbaDokumentow'),

			# Struktura dokumentu
			'nazwa_struktury': find('NazwaStrukturyLogicznej'),
			'kod_formularza': find('KodFormularza'),

			# Dane dokumentu
			'nip_sprzedawcy': find('NipSprzedawcy'),
			'numer_ksef': find('NumerKSeFDokumentu'),
			'numer_faktury': find('NumerFaktury'),
			'data_wystawienia': find('DataWystawieniaFaktury'),
			'data_przeslania': find('DataPrzeslaniaDokumentu'),
			'data_nadania_ksef': find('DataNadaniaNumeruKSeF'),
			'skrot_dokumentu': find('SkrotDokumentu'),
			'tryb_wysylki': find('TrybWysylki'),

			# Podpis cyfrowy (XAdES)
			'signing_time': find('SigningTime'),
			'cert_issuer': find('X509IssuerName'),
			'cert_serial': find('X509SerialNumber'),
			'digest_value': find('DigestValue'),
			'signature_value': find('SignatureValue'),
		}

	#
	def action_show_ksef_upo(self):
		self.ensure_one()

		if not self.ksef_number:
			raise UserError(_("Faktura nie posiada numeru KSeF."))

		attachment = self.env['ir.attachment'].search([
			('res_model', '=', 'account.move'),
			('res_id', '=', self.id),
			('mimetype', '=', 'application/pdf'),
			('name', '=', f'UPO_{self.ksef_number}.pdf'),
		], limit=1)

		if attachment:
			return {
				'type': 'ir.actions.act_window',
				'res_model': 'ir.attachment',
				'res_id': attachment.id,
				'view_mode': 'form',
				'target': 'current',
			}

		return self.env.ref(
			'hfb_xmlmap_exporter.action_report_ksef_upo'
		).report_action(self)


#EoF

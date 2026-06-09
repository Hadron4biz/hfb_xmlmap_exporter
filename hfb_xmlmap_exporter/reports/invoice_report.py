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
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import re
from odoo import release
import io
import uuid
from lxml import etree
import base64
from markupsafe import Markup, escape

import logging
_logger = logging.getLogger(__name__)

class KSeFParserFA3:
	"""Parser dla KSeF FA(3) - obsługa wariantów: VAT, ZAL, ROZ, KOR, KOR_ZAL"""

	def __init__(self, xml_content, company_nip=None):
		self.tree = etree.fromstring(xml_content.encode('utf-8'))
		self.company_nip = company_nip
		self.ns = {'fa': self.tree.nsmap.get(None) or self.tree.nsmap.get('')}
		
		if not self.ns['fa']:
			tag = etree.QName(self.tree.tag)
			self.ns['fa'] = tag.namespace

	def parse(self):
		issuer = self._parse_subject('Podmiot1')
		recipient = self._parse_subject('Podmiot2')
		role = self._detect_role(issuer, recipient)
		invoice_type = self._get_invoice_type()

		result = {
			"type": invoice_type,
			"issuer": issuer,
			"recipient": recipient,
			"our_role": role,
			"our_company": issuer if role == "issuer" else recipient,
			"counterparty": recipient if role == "issuer" else issuer,
			"invoice": self._parse_invoice_header(invoice_type),
			"lines": self._parse_lines(invoice_type),
			"totals": self._parse_totals(invoice_type),
			"annotations": self._parse_annotations(),
			"original_invoice": self._parse_original_invoice(invoice_type),
		}
		
		return result

	def _get_invoice_type(self):
		"""Określa typ faktury na podstawie RodzajFaktury"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is not None:
			rodzaj = self._safe(fa, 'RodzajFaktury')
			if rodzaj:
				return rodzaj
		return "VAT"

	def _parse_subject(self, tag):
		node = self.tree.find(f'.//fa:{tag}', namespaces=self.ns)
		if node is None:
			return {}
		
		dane = node.find('.//fa:DaneIdentyfikacyjne', namespaces=self.ns)
		if dane is None:
			return {}
		
		brak_id = self._safe(dane, 'BrakID') == '1'
		nip = self._safe(dane, 'NIP')
		foreign_id = self._safe(dane, 'NrID')
		country_code = self._safe(dane, 'KodKraju')
		
		result = {
			"name": self._safe(dane, 'Nazwa'),
			"nip": nip,
			"country_code": country_code,
			"foreign_tax_id": foreign_id,
			"is_domestic": bool(nip) and not brak_id,
			"no_tax_id": brak_id,
			"customer_number": self._safe(node, 'NrKlienta'),
			"is_jst": self._safe(node, 'JST') == '1',
			"is_gv": self._safe(node, 'GV') == '1',
		}
		
		# Adres
		adres = node.find('.//fa:Adres', namespaces=self.ns)
		if adres is not None:
			result["address"] = {
				"country_code": self._safe(adres, 'KodKraju'),
				"line1": self._safe(adres, 'AdresL1'),
				"line2": self._safe(adres, 'AdresL2'),
			}
		
		return result

	def _detect_role(self, issuer, recipient):
		if not self.company_nip:
			return "unknown"
		if issuer.get("nip") == self.company_nip:
			return "issuer"
		if recipient.get("nip") == self.company_nip:
			return "recipient"
		return "unknown"

	def _parse_invoice_header(self, invoice_type):
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return {}

		header = {
			"number": self._safe(fa, 'P_2'),
			"issue_date": self._safe(fa, 'P_1'),
			"sale_date": self._safe(fa, 'P_6'),
			"place_issue": self._safe(fa, 'P_1M'),
			"currency": self._safe(fa, 'KodWaluty'),
			"type": invoice_type,
		}

		# Dla faktur zaliczkowych (ZAL) i korekt zaliczek (KOR_ZAL)
		if invoice_type in ['ZAL', 'KOR_ZAL']:
			zamowienie = self.tree.find('.//fa:Zamowienie', namespaces=self.ns)
			if zamowienie is not None:
				header["order_value"] = self._safe(zamowienie, 'WartoscZamowienia')

		# Dla korekt zaliczek - wartość brutto przed korektą
		if invoice_type == 'KOR_ZAL':
			header["advance_gross_before"] = self._safe(fa, 'P_15ZK')

		return header

	def _parse_lines(self, invoice_type):
		lines = []

		if invoice_type == 'ZAL':
			# Zaliczka - linie z ZamowienieWiersz
			nodes = self.tree.findall('.//fa:ZamowienieWiersz', namespaces=self.ns)
			for node in nodes:
				lines.append({
					"name": self._safe(node, 'P_7Z'),
					"qty": self._safe(node, 'P_8BZ'),
					"unit": self._safe(node, 'P_8AZ'),
					"price": self._safe(node, 'P_9AZ'),
					"net": self._safe(node, 'P_11NettoZ'),
					"vat": self._safe(node, 'P_11VatZ'),
					"vat_rate": self._safe(node, 'P_12Z'),
					"is_before_correction": self._safe(node, 'StanPrzedZ') == '1',
				})

		elif invoice_type == 'KOR_ZAL':
			# Korekta zaliczki - linie z ZamowienieWiersz (z StanPrzedZ)
			nodes = self.tree.findall('.//fa:ZamowienieWiersz', namespaces=self.ns)
			for node in nodes:
				lines.append({
					"name": self._safe(node, 'P_7Z'),
					"qty": self._safe(node, 'P_8BZ'),
					"unit": self._safe(node, 'P_8AZ'),
					"price": self._safe(node, 'P_9AZ'),
					"net": self._safe(node, 'P_11NettoZ'),
					"vat": self._safe(node, 'P_11VatZ'),
					"vat_rate": self._safe(node, 'P_12Z'),
					"is_before_correction": self._safe(node, 'StanPrzedZ') == '1',
				})

		else:
			# VAT, ROZ, KOR - linie z FaWiersz
			nodes = self.tree.findall('.//fa:FaWiersz', namespaces=self.ns)
			for node in nodes:
				lines.append({
					"name": self._safe(node, 'P_7'),
					"qty": self._safe(node, 'P_8B'),
					"unit": self._safe(node, 'P_8A'),
					"price": self._safe(node, 'P_9A'),
					"net": self._safe(node, 'P_11'),
					"vat_rate": self._safe(node, 'P_12'),  # string, NIE float
					"vat": self._safe(node, 'P_11_VAT'),   # kwota VAT - DODAJ TO!
					"gross": self._safe(node, 'P_11_GROSS'), # kwota brutto - DODAJ TO!
					"exchange_rate": self._safe(node, 'KursWaluty'),
					"line_number": self._safe(node, 'NrWierszaFa'),
					"is_before_correction": self._safe(node, 'StanPrzed') == '1',
				})

		return lines

	def _parse_totals(self, invoice_type):
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return {}

		totals = {
			"net": self._safe(fa, 'P_13_1'),
			"vat": self._safe(fa, 'P_14_1'),
			"gross": self._safe(fa, 'P_15'),
		}

		# Dla korekt - wartości mogą być ujemne
		if invoice_type in ['KOR', 'KOR_ZAL']:
			totals["is_correction"] = True

		return totals

	# Tabelka podatków
	def _parse_totals(self, invoice_type):
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return {}

		totals = {
			"net": self._safe(fa, 'P_13_1'),
			"vat": self._safe(fa, 'P_14_1'),
			"gross": self._safe(fa, 'P_15'),
			"vat_breakdown": self._parse_vat_breakdown(),
		}

		if invoice_type in ['KOR', 'KOR_ZAL']:
			totals["is_correction"] = True

		return totals

	def _parse_vat_breakdown(self):
		"""Parsuje podsumowanie stawek VAT"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return []

		vat_breakdown = []

		lines = self._parse_lines(self._get_invoice_type())
		vat_rates = {}

		for line in lines:
			rate = line.get('vat_rate', '0')
			
			# Bezpieczne pobranie netto
			net_str = line.get('net', '0')
			try:
				net = float(net_str) if net_str else 0
			except (ValueError, TypeError):
				net = 0
			
			# Bezpieczne pobranie vat
			vat_str = line.get('vat', '0')
			if vat_str is None:
				vat_str = '0'
			try:
				vat_amount = float(vat_str)
			except (ValueError, TypeError):
				vat_amount = 0
			
			gross = net + vat_amount

			if rate not in vat_rates:
				vat_rates[rate] = {'net': 0, 'vat': 0, 'gross': 0}
			vat_rates[rate]['net'] += net
			vat_rates[rate]['vat'] += vat_amount
			vat_rates[rate]['gross'] += gross

		for rate, values in vat_rates.items():
			vat_breakdown.append({
				"rate": rate,
				"net": f"{values['net']:.2f}",
				"vat": f"{values['vat']:.2f}",
				"gross": f"{values['gross']:.2f}",
			})

		return vat_breakdown

	def _get_vat_rate_for_index(self, index):
		"""Pobiera stawkę VAT dla danego indeksu (np. z P_12_1, P_12_2)"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return '0'
		return self._safe(fa, f'P_12_{index}') or '0'

	# Tabelka opisu
	def _parse_annotations(self):
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return {}

		invoice_type = self._get_invoice_type()
		
		annotations = {}
		adnotacje = fa.find('.//fa:Adnotacje', namespaces=self.ns)
		
		if adnotacje is not None:
			# Odwrotne obciążenie
			reverse_charge_val = self._safe(adnotacje, 'P_16')
			annotations['reverse_charge'] = reverse_charge_val == '2'
			
			# Split payment
			split_payment_val = self._safe(adnotacje, 'P_17')
			annotations['split_payment'] = split_payment_val == '2'
			
			# Zwolniony z VAT - tylko jeśli faktura nie ma pozycji z VAT > 0
			exempt_val = self._safe(adnotacje, 'Zwolnienie/P_19N')
			if invoice_type in ['ZAL', 'KOR_ZAL']:
				has_vat = self._has_vat_positive_lines_zal()
			else:
				has_vat = self._has_vat_positive_lines()
			annotations['exempt'] = exempt_val == '1' and not has_vat
			
			# Nowe środki transportu
			new_transport_val = self._safe(adnotacje, 'NoweSrodkiTransportu/P_22N')
			annotations['new_transport'] = new_transport_val == '1'
			
			# Procedura marży
			margin_val = self._safe(adnotacje, 'PMarzy/P_PMarzyN')
			annotations['margin'] = margin_val == '1'

		return annotations
	def _has_vat_positive_lines(self):
		"""Sprawdza czy faktura ma pozycje z VAT > 0"""
		nodes = self.tree.findall('.//fa:FaWiersz', namespaces=self.ns)
		for node in nodes:
			vat_rate = self._safe(node, 'P_12')
			if vat_rate:
				# Spróbuj przekonwertować tylko jeśli to liczba
				try:
					if float(vat_rate) > 0:
						return True
				except ValueError:
					# Nie jest liczbą (np. '0 WDT', 'zw', 'oo') - pomiń
					pass
		return False

	def _has_vat_positive_lines_zal(self):
		"""Sprawdza czy zamówienie ma pozycje z VAT > 0"""
		nodes = self.tree.findall('.//fa:ZamowienieWiersz', namespaces=self.ns)
		for node in nodes:
			vat_rate = self._safe(node, 'P_12Z')
			if vat_rate:
				try:
					if float(vat_rate) > 0:
						return True
				except ValueError:
					pass
		return False

	def _parse_original_invoice(self, invoice_type):
		"""Parsuje dane faktury pierwotnej dla korekt"""
		if invoice_type not in ['KOR', 'KOR_ZAL']:
			return {}

		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return {}

		dane = fa.find('.//fa:DaneFaKorygowanej', namespaces=self.ns)
		if dane is None:
			return {}

		return {
			"number": self._safe(dane, 'NrFaKorygowanej'),
			"date": self._safe(dane, 'DataWystFaKorygowanej'),
			"ksef_id": self._safe(dane, 'NrKSeFFaKorygowanej'),
		}

	def _safe(self, node, path):
		if node is None:
			return None
		parts = path.split('/')
		current = node
		for part in parts:
			current = current.find(f'fa:{part}', namespaces=self.ns)
			if current is None:
				return None
		return current.text


class AccountMove(models.Model):
	_inherit = "account.move"

	# ------------------------------------------------------------------------------------------------------
	# Metody do podglądu faktury MF AP KSeF
	# ------------------------------------------------------------------------------------------------------

	def action_preview_ksef_pdf(self):
		self.ensure_one()

		communication = self.env['communication.log'].search([
			('document_model', '=', 'account.move'),
			('document_id', '=', self.id),
			('file_data', '!=', False),
			('direction', 'in', ['import', 'export']),
		], limit=1, order='create_date DESC')

		_logger.info(
			f"\n👉 action_preview_ksef_pdf"
			f"\n👉 communication = {communication}"
			f"\n👉 ----------------------------------------------------------------------"
		)

		if not communication:
			raise UserError(_(
				'Nie znaleziono pliku XML KSeF dla tej faktury.'
			))

		try:

			xml_content = base64.b64decode(communication.file_data).decode('utf-8')

			parser = KSeFParserFA3(
				xml_content,
				company_nip=self.company_id.vat
			)

			#normalized = parser.parse()

		except Exception as e:
			raise UserError(_('Błąd parsowania XML KSeF: %s') % str(e))

		normalized = parser.parse()

		_logger.info(
			f"\n🚩 action_preview_ksef_pdf"
			f"\n🚩 communication = {communication}"
			f"\n🚩 parser = {parser}"
			f"\n🚩 normalized = {normalized}"
			f"\n🚩 xml_content = {xml_content}"
			f"\n🚩 --------------------------------------------------------------------------"
		)


		# Przekaż dane przez context
		return self.env.ref(
			'hfb_xmlmap_exporter.action_report_ksef_invoice'
			).with_context(
					ksef_preview_data=normalized
				).report_action(self)

	def _get_ksef_communication(self):
		"""Pomocnicza metoda do pobrania komunikacji KSeF"""
		return self.env['communication.log'].search([
			('document_model', '=', 'account.move'),
			('document_id', '=', self.id),
			('file_data', '!=', False),
		], limit=1, order='create_date DESC')


#EoF

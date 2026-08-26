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
"""@version 16.1.6
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import re, json
from odoo import release
import io
import uuid
from lxml import etree
import base64
from markupsafe import Markup, escape
from decimal import Decimal, ROUND_HALF_UP

import logging
_logger = logging.getLogger(__name__)

class KSeFParserFA3:
	"""Parser dla KSeF FA(3) - obsługa wariantów: VAT, ZAL, ROZ, KOR, KOR_ZAL"""

	CORRECTION_TYPE_LABELS = {
		"1": "Korekta skutkująca w dacie ujęcia faktury pierwotnej",
		"2": "Korekta skutkująca w dacie wystawienia faktury korygującej",
		"3": "Korekta skutkująca w dacie innej, w tym gdy dla różnych pozycji faktury korygującej daty te są różne",
	}

	PAYMENT_METHODS = {
		"1": "Gotówka",
		"2": "Karta",
		"3": "Bon",
		"4": "Czek",
		"5": "Kredyt",
		"6": "Przelew",
		"7": "Mobilna",
	}

	VAT_SUMMARY_FIELDS = [
		{
			"net_field": "P_13_1",
			"vat_field": "P_14_1",
			"vat_pln_field": "P_14_1W",
			"rate": "23",
			"rate_label": "23%",
			"description": "Sprzedaż opodatkowana stawką podstawową",
		},
		{
			"net_field": "P_13_2",
			"vat_field": "P_14_2",
			"vat_pln_field": "P_14_2W",
			"rate": "8",
			"rate_label": "8%",
			"description": "Sprzedaż opodatkowana stawką obniżoną pierwszą",
		},
		{
			"net_field": "P_13_3",
			"vat_field": "P_14_3",
			"vat_pln_field": "P_14_3W",
			"rate": "5",
			"rate_label": "5%",
			"description": "Sprzedaż opodatkowana stawką obniżoną drugą",
		},
		{
			"net_field": "P_13_4",
			"vat_field": "P_14_4",
			"vat_pln_field": "P_14_4W",
			"rate": "taxi",
			"rate_label": "ryczałt TAXI",
			"description": "Ryczałt dla taksówek osobowych",
		},
		{
			"net_field": "P_13_5",
			"vat_field": "P_14_5",
			"vat_pln_field": None,
			"rate": "special",
			"rate_label": "procedura szczególna",
			"description": "Procedura szczególna dział XII rozdział 6a",
		},
		{
			"net_field": "P_13_6_1",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "0",
			"rate_label": "0%",
			"description": "Sprzedaż objęta stawką 0%",
		},
		{
			"net_field": "P_13_6_2",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "0_WDT",
			"rate_label": "0% WDT",
			"description": "Wewnątrzwspólnotowa dostawa towarów",
		},
		{
			"net_field": "P_13_6_3",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "0_EX",
			"rate_label": "0% EX",
			"description": "Eksport towarów",
		},
		{
			"net_field": "P_13_7",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "zw",
			"rate_label": "zw",
			"description": "Sprzedaż zwolniona od podatku",
		},
		{
			"net_field": "P_13_8",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "np",
			"rate_label": "np",
			"description": "Dostawa towarów lub świadczenie usług poza terytorium kraju",
		},
		{
			"net_field": "P_13_9",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "np_ue",
			"rate_label": "np UE",
			"description": "Świadczenie usług, o których mowa w art. 100 ust. 1 pkt 4 ustawy",
		},
		{
			"net_field": "P_13_10",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "oo",
			"rate_label": "oo",
			"description": "Odwrotne obciążenie",
		},
		{
			"net_field": "P_13_11",
			"vat_field": None,
			"vat_pln_field": None,
			"rate": "marza",
			"rate_label": "marża",
			"description": "Procedura marży",
		},
	]

	def _has_amount(self, value):
		"""
		Czy wartość z XML ma sens finansowy.

		Uwaga:
		- '0.00' też może być informacją, ale w podsumowaniu VAT
		  nie chcemy drukować pustych pozycji wynikających z braku pola.
		- Dlatego ta metoda sprawdza istnienie tekstu, a nie to, czy kwota != 0.
		"""
		return value not in (None, "")

	def __init__(self, xml_content, company_nip=None):
		self.tree = etree.fromstring(xml_content.encode('utf-8'))
		self.company_nip = company_nip
		self.ns = {'fa': self.tree.nsmap.get(None) or self.tree.nsmap.get('')}
		
		if not self.ns['fa']:
			tag = etree.QName(self.tree.tag)
			self.ns['fa'] = tag.namespace


	"""
		Rozliczenia
	"""
	def _parse_settlement(self):
		"""
		Parsuje pełny blok Fa/Rozliczenie.

		Dane są przepisywane wyłącznie z XML.
		Nie wyliczamy DoZaplaty ani DoRozliczenia.
		"""
		fa = self.tree.find(".//fa:Fa", namespaces=self.ns)
		if fa is None:
			return {}

		node = fa.find("fa:Rozliczenie", namespaces=self.ns)
		if node is None:
			return {}

		charges = []

		for item in node.findall("fa:Obciazenia", namespaces=self.ns):
			amount = self._safe(item, "Kwota")
			reason = self._safe(item, "Powod")

			if amount not in (None, "") or reason:
				charges.append({
					"amount": self._format_optional_amount(amount),
					"reason": reason or "",
				})

		deductions = []

		for item in node.findall("fa:Odliczenia", namespaces=self.ns):
			amount = self._safe(item, "Kwota")
			reason = self._safe(item, "Powod")

			if amount not in (None, "") or reason:
				deductions.append({
					"amount": self._format_optional_amount(amount),
					"reason": reason or "",
				})

		return {
			"exists": True,

			"charges": charges,
			"total_charges": self._format_optional_amount(
				self._safe(node, "SumaObciazen")
			),

			"deductions": deductions,
			"total_deductions": self._format_optional_amount(
				self._safe(node, "SumaOdliczen")
			),

			"amount_due": self._format_optional_amount(
				self._safe(node, "DoZaplaty")
			),

			"amount_to_settle": self._format_optional_amount(
				self._safe(node, "DoRozliczenia")
			),
		}
	"""
		Main
	"""
	def parse(self):
		issuer = self._parse_subject('Podmiot1')
		recipient = self._parse_subject('Podmiot2')
		role = self._detect_role(issuer, recipient)
		invoice_type = self._get_invoice_type()

		correction = self._parse_correction(invoice_type)
		advance = self._parse_advance(invoice_type)

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
			"correction": correction,
			"advance": advance,
			"settlement": self._parse_settlement(),
			"correction_tax_analysis": self._parse_correction_tax_analysis(invoice_type),
			"additional_info": self._parse_additional_info(),
			"transaction_conditions": self._parse_transaction_conditions(),
			"registries": self._parse_registries(),
			"original_invoice": (
				correction.get("corrected_invoices", [{}])[0]
				if correction.get("corrected_invoices")
				else {}
			),
			"payment": self._parse_payment(),
		}
		
		return result

	# Dodatkowe helpery
	def _parse_correction_tax_analysis(self, invoice_type):
		"""
		Analiza różnic korekty według stawek VAT.

		Zasady:
		- StanPrzed = 1 odejmujemy,
		- wiersze po korekcie dodajemy,
		- grupujemy po stawce VAT,
		- jeśli XML pozycji nie zawiera P_11Vat, VAT liczony jest od
		  zgrupowanej zmiany netto dla danej stawki.
		"""
		if invoice_type not in ["KOR", "KOR_ZAL", "KOR_ROZ"]:
			return {}

		lines = self._parse_lines(invoice_type)
		if not lines:
			return {}

		groups = {}

		for line in lines:
			rate = line.get("vat_rate") or ""
			rate_label = line.get("vat_rate_label") or self._format_vat_rate_label(rate)

			if not rate:
				rate = "unknown"
				rate_label = "brak stawki"

			if rate not in groups:
				groups[rate] = {
					"rate": rate,
					"rate_label": rate_label,
					"before_net": Decimal("0.00"),
					"after_net": Decimal("0.00"),
					"net_delta": Decimal("0.00"),
					"vat_delta": Decimal("0.00"),
					"vat_compute_base": Decimal("0.00"),
					"computed_vat": False,
				}

			sign = Decimal("-1.00") if line.get("is_before_correction") else Decimal("1.00")

			net = self._to_decimal(line.get("net")).quantize(
				Decimal("0.01"),
				rounding=ROUND_HALF_UP
			)

			net_signed = net * sign

			groups[rate]["net_delta"] += net_signed

			if sign < 0:
				groups[rate]["before_net"] += net
			else:
				groups[rate]["after_net"] += net

			vat_raw = line.get("vat")

			if vat_raw not in (None, ""):
				vat = self._to_decimal(vat_raw).quantize(
					Decimal("0.01"),
					rounding=ROUND_HALF_UP
				)
				groups[rate]["vat_delta"] += vat * sign
			else:
				# Nie liczymy VAT per linia.
				# Zbieramy podstawę i liczymy VAT dopiero po zgrupowaniu.
				groups[rate]["vat_compute_base"] += net_signed
				groups[rate]["computed_vat"] = True

		rows = []
		total_net = Decimal("0.00")
		total_vat = Decimal("0.00")
		total_gross = Decimal("0.00")
		any_computed_vat = False

		def _sort_key(group):
			try:
				return (0, Decimal(str(group.get("rate")).replace(',', '.')))
			except Exception:
				return (1, str(group.get("rate")))

		for group in sorted(groups.values(), key=_sort_key):
			net_delta = group["net_delta"].quantize(
				Decimal("0.01"),
				rounding=ROUND_HALF_UP
			)

			vat_delta = group["vat_delta"]

			if group["computed_vat"]:
				vat_delta += self._compute_vat_from_net_and_rate(
					group["vat_compute_base"],
					group["rate"]
				)
				any_computed_vat = True

			vat_delta = vat_delta.quantize(
				Decimal("0.01"),
				rounding=ROUND_HALF_UP
			)

			gross_delta = (net_delta + vat_delta).quantize(
				Decimal("0.01"),
				rounding=ROUND_HALF_UP
			)

			if (
				net_delta == Decimal("0.00")
				and vat_delta == Decimal("0.00")
				and gross_delta == Decimal("0.00")
			):
				continue

			total_net += net_delta
			total_vat += vat_delta
			total_gross += gross_delta

			rows.append({
				"rate": group["rate"],
				"rate_label": group["rate_label"],
				"before_net": self._decimal_to_amount(group["before_net"]),
				"after_net": self._decimal_to_amount(group["after_net"]),
				"net": self._decimal_to_amount(net_delta),
				"vat": self._decimal_to_amount(vat_delta),
				"gross": self._decimal_to_amount(gross_delta),
				"computed_vat": group["computed_vat"],
			})

		return {
			"exists": bool(rows),
			"rows": rows,
			"total_net": self._decimal_to_amount(total_net),
			"total_vat": self._decimal_to_amount(total_vat),
			"total_gross": self._decimal_to_amount(total_gross),
			"computed_vat": any_computed_vat,
		}


	def _to_decimal(self, value):
		if value in (None, ''):
			return Decimal('0.00')

		try:
			return Decimal(str(value).replace(',', '.').strip())
		except Exception:
			return Decimal('0.00')


	def _decimal_to_amount(self, value):
		if value in (None, ''):
			value = Decimal('0.00')

		if not isinstance(value, Decimal):
			value = self._to_decimal(value)

		return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


	def _is_numeric_vat_rate(self, rate):
		if rate in (None, ''):
			return False

		try:
			Decimal(str(rate).replace(',', '.').strip())
			return True
		except Exception:
			return False


	def _compute_vat_from_net_and_rate(self, net, rate):
		"""
		Pomocnicze wyliczenie VAT dla analizy korekty.

		Nie zastępuje danych XML. Używane tylko w sekcji analitycznej,
		gdy pozycje nie mają P_11Vat.
		"""
		if not self._is_numeric_vat_rate(rate):
			return Decimal('0.00')

		net_dec = self._to_decimal(net)
		rate_dec = self._to_decimal(rate)

		return (net_dec * rate_dec / Decimal('100')).quantize(
			Decimal('0.01'),
			rounding=ROUND_HALF_UP
		)


	def _parse_corrected_invoice(self, node):
		if node is None:
			return {}

		has_ksef_marker = self._safe(node, "NrKSeF") == "1"
		outside_ksef_marker = self._safe(node, "NrKSeFN") == "1"

		return {
			"number": self._safe(node, "NrFaKorygowanej"),
			"date": self._safe(node, "DataWystFaKorygowanej"),
			"ksef_marker": has_ksef_marker,
			"outside_ksef_marker": outside_ksef_marker,
			"ksef_id": self._safe(node, "NrKSeFFaKorygowanej"),
		}

	def _parse_correction(self, invoice_type):
		"""
		Parsuje dane korekty dla KOR, KOR_ZAL, KOR_ROZ.

		Nie zakłada, że istnieje tylko jedna faktura korygowana.
		"""
		if invoice_type not in ["KOR", "KOR_ZAL", "KOR_ROZ"]:
			return {}

		fa = self.tree.find(".//fa:Fa", namespaces=self.ns)
		if fa is None:
			return {}

		type_code = self._safe(fa, "TypKorekty")

		correction = {
			"exists": True,
			"reason": self._safe(fa, "PrzyczynaKorekty"),
			"type_code": type_code,
			"type_label": self.CORRECTION_TYPE_LABELS.get(type_code, type_code or ""),
			"corrected_period": self._safe(fa, "OkresFaKorygowanej"),
			"corrected_invoice_number": self._safe(fa, "NrFaKorygowany"),
			"p15_before_correction": self._format_optional_amount(self._safe(fa, "P_15ZK")),
			"currency_rate_before_correction": self._safe(fa, "KursWalutyZK"),
			"corrected_invoices": [],
		}

		for node in fa.findall("fa:DaneFaKorygowanej", namespaces=self.ns):
			item = self._parse_corrected_invoice(node)
			if any(item.values()):
				correction["corrected_invoices"].append(item)

		return correction

	def _payment_method_label(self, code):
		if code in (None, ''):
			return ''
		code = str(code).strip()
		return self.PAYMENT_METHODS.get(code, code)

	def _parse_bank_account(self, node):
		if node is None:
			return {}

		return {
			"number": self._safe(node, "NrRB"),
			"swift": self._safe(node, "SWIFT"),
			"own_bank_account": self._safe(node, "RachunekWlasnyBanku"),
			"bank_name": self._safe(node, "NazwaBanku"),
			"description": self._safe(node, "OpisRachunku"),
		}

	def _parse_due_term(self, node):
		if node is None:
			return {}

		term_desc = node.find("fa:TerminOpis", namespaces=self.ns)

		result = {
			"date": self._safe(node, "Termin"),
			"description": "",
			"quantity": "",
			"unit": "",
			"initial_event": "",
		}

		if term_desc is not None:
			result.update({
				"quantity": self._safe(term_desc, "Ilosc"),
				"unit": self._safe(term_desc, "Jednostka"),
				"initial_event": self._safe(term_desc, "ZdarzeniePoczatkowe"),
			})

			parts = []
			if result["quantity"] and result["unit"]:
				parts.append(f"{result['quantity']} {result['unit']}")
			if result["initial_event"]:
				parts.append(f"od: {result['initial_event']}")
			result["description"] = ", ".join(parts)

		return result

	def _parse_partial_payment(self, node):
		if node is None:
			return {}

		method_code = self._safe(node, "FormaPlatnosci")
		other_payment = self._safe(node, "PlatnoscInna") == "1"

		return {
			"amount": self._format_optional_amount(self._safe(node, "KwotaZaplatyCzesciowej")),
			"date": self._safe(node, "DataZaplatyCzesciowej"),
			"method_code": method_code,
			"method_label": self._payment_method_label(method_code),
			"other_payment": other_payment,
			"other_payment_description": self._safe(node, "OpisPlatnosci"),
		}

	def _format_optional_amount(self, value):
		"""
		Formatuje kwotę tylko wtedy, gdy pole istnieje w XML.
		Dla braku pola zwraca pusty string.
		"""
		if value in (None, ''):
			return ''
		return self._format_amount(value)

	def _compute_line_gross(self, net, vat, gross):
		"""
		Wartość brutto pozycji:
		1. preferuj wartość brutto z XML,
		2. jeśli jej nie ma, ale jest netto i VAT, policz netto + VAT,
		3. jeśli VAT nie występuje na pozycji, nie licz brutto.
		"""
		if gross not in (None, ''):
			return self._format_amount(gross)

		if net not in (None, '') and vat not in (None, ''):
			return self._sum_amounts(net, vat)

		return ''

	def _collect_line_identifiers(self, node, zal=False):
		"""
		Zbiera dodatkowe identyfikatory pozycji do pokazania pod nazwą.
		Nie wszystkie występują w każdym XML.
		"""
		if node is None:
			return []

		if zal:
			fields_map = [
				('GTU', 'GTUZ'),
				('PKWiU', 'PKWiUZ'),
				('CN', 'CNZ'),
				('PKOB', 'PKOBZ'),
				('GTIN', 'GTINZ'),
				('Indeks', 'IndeksZ'),
				('Procedura', 'ProceduraZ'),
				('P_12_XII', 'P_12Z_XII'),
				('Zał. 15', 'P_12Z_Zal_15'),
			]
		else:
			fields_map = [
				('GTU', 'GTU'),
				('PKWiU', 'PKWiU'),
				('CN', 'CN'),
				('PKOB', 'PKOB'),
				('GTIN', 'GTIN'),
				('Indeks', 'Indeks'),
				('Procedura', 'Procedura'),
				('P_12_XII', 'P_12_XII'),
				('Zał. 15', 'P_12_Zal_15'),
				('UU_ID', 'UU_ID'),
			]

		result = []
		for label, field_name in fields_map:
			value = self._safe(node, field_name)
			if value not in (None, ''):
				result.append({
					"label": label,
					"value": value,
				})

		return result

	def _to_float(self, value):
		"""Bezpieczna konwersja wartości kwotowej z XML do float."""
		if value in (None, ''):
			return 0.0
		try:
			return float(str(value).replace(',', '.').strip())
		except (ValueError, TypeError):
			return 0.0

	def _format_amount(self, value):
		"""Format kwoty do wyświetlania w raporcie."""
		return f"{self._to_float(value):.2f}"

	def _sum_amounts(self, *values):
		"""Suma kwot XML jako tekst z dwoma miejscami."""
		return f"{sum(self._to_float(v) for v in values):.2f}"

	def _format_vat_rate_label(self, rate):
		"""
		Formatuje stawkę VAT do wydruku.
		Nie zakładamy automatycznie, że każda stawka to liczba z procentem.
		Obsługujemy także: zw, np, oo, 0 WDT, 0 EX.
		"""
		if rate in (None, ''):
			return ''

		raw = str(rate).strip()
		normalized = raw.replace(',', '.')
		lower = normalized.lower()

		special_labels = {
			'zw': 'zw',
			'np': 'np',
			'oo': 'oo',
			'0 wdt': '0% WDT',
			'0% wdt': '0% WDT',
			'0 ex': '0% EX',
			'0% ex': '0% EX',
			'0 eksport': '0% EX',
			'0% eksport': '0% EX',
		}

		if lower in special_labels:
			return special_labels[lower]

		if normalized.endswith('%'):
			return normalized

		try:
			value = float(normalized)
			if value.is_integer():
				return f"{int(value)}%"
			return f"{value:g}%"
		except ValueError:
			return raw


	def _get_invoice_type(self):
		"""Określa typ faktury na podstawie RodzajFaktury"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is not None:
			rodzaj = self._safe(fa, 'RodzajFaktury')
			if rodzaj:
				return rodzaj
		return "VAT"

	def _parse_payment(self):
		fa = self.tree.find(".//fa:Fa", namespaces=self.ns)
		if fa is None:
			return {}

		platnosc = fa.find("fa:Platnosc", namespaces=self.ns)
		if platnosc is None:
			return {}

		payment = {
			"exists": True,

			# status zapłaty
			"status_code": "unpaid",
			"status_label": "Brak zapłaty",
			"paid": False,
			"paid_date": "",

			# forma płatności
			"method_code": "",
			"method_label": "",
			"other_payment": False,
			"other_payment_description": "",

			# zbiory danych
			"partial_payment_marker": "",
			"partial_payment_label": "",
			"partial_payments": [],
			"due_terms": [],
			"bank_accounts": [],
			"factor_bank_accounts": [],

			# dodatkowe
			"skonto": {},
			"payment_link": "",
			"ipksef": "",
		}

		# ------------------------------------------------------------
		# 1. Status zapłaty
		# ------------------------------------------------------------
		if self._safe(platnosc, "Zaplacono") == "1":
			payment.update({
				"status_code": "paid",
				"status_label": "Zapłacono",
				"paid": True,
				"paid_date": self._safe(platnosc, "DataZaplaty") or "",
			})

		partial_marker = self._safe(platnosc, "ZnacznikZaplatyCzesciowej")
		if partial_marker:
			payment["partial_payment_marker"] = partial_marker

			if partial_marker == "1":
				payment.update({
					"status_code": "partially_paid",
					"status_label": "Zapłacono częściowo",
					"partial_payment_label": "Zapłacono częściowo",
				})
			elif partial_marker == "2":
				payment.update({
					"status_code": "paid_in_parts",
					"status_label": "Zapłacono w całości w częściach",
					"paid": True,
					"partial_payment_label": "Zapłacono w całości w częściach",
				})

		# ------------------------------------------------------------
		# 2. Zapłaty częściowe
		# ------------------------------------------------------------
		for partial in platnosc.findall("fa:ZaplataCzesciowa", namespaces=self.ns):
			partial_data = self._parse_partial_payment(partial)
			if partial_data:
				payment["partial_payments"].append(partial_data)

		# ------------------------------------------------------------
		# 3. Terminy płatności
		# ------------------------------------------------------------
		for term in platnosc.findall("fa:TerminPlatnosci", namespaces=self.ns):
			term_data = self._parse_due_term(term)

			# Pusty <TerminPlatnosci/> nie powinien generować pustego wiersza.
			if any(term_data.values()):
				payment["due_terms"].append(term_data)

		# ------------------------------------------------------------
		# 4. Forma płatności
		# ------------------------------------------------------------
		method_code = self._safe(platnosc, "FormaPlatnosci")
		if method_code:
			payment["method_code"] = method_code
			payment["method_label"] = self._payment_method_label(method_code)

		if self._safe(platnosc, "PlatnoscInna") == "1":
			payment["other_payment"] = True
			payment["other_payment_description"] = self._safe(platnosc, "OpisPlatnosci") or ""

		# ------------------------------------------------------------
		# 5. Rachunki bankowe
		# ------------------------------------------------------------
		for account in platnosc.findall("fa:RachunekBankowy", namespaces=self.ns):
			account_data = self._parse_bank_account(account)
			if any(account_data.values()):
				payment["bank_accounts"].append(account_data)

		for account in platnosc.findall("fa:RachunekBankowyFaktora", namespaces=self.ns):
			account_data = self._parse_bank_account(account)
			if any(account_data.values()):
				payment["factor_bank_accounts"].append(account_data)

		# ------------------------------------------------------------
		# 6. Skonto
		# ------------------------------------------------------------
		skonto = platnosc.find("fa:Skonto", namespaces=self.ns)
		if skonto is not None:
			payment["skonto"] = {
				"terms": self._safe(skonto, "WarunkiSkonta"),
				"amount": self._safe(skonto, "WysokoscSkonta"),
			}

		# ------------------------------------------------------------
		# 7. Link płatności / IPKSeF
		# ------------------------------------------------------------
		payment["payment_link"] = self._safe(platnosc, "LinkDoPlatnosci") or ""
		payment["ipksef"] = self._safe(platnosc, "IPKSeF") or ""

		return payment

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
			"email": self._safe(node, 'DaneKontaktowe/Email'),
			"phone": self._safe(node, 'DaneKontaktowe/Telefon'),
		}
		
		# Adres
		adres = node.find('.//fa:Adres', namespaces=self.ns)
		if adres is not None:
			result["address"] = {
				"country_code": self._safe(adres, 'KodKraju'),
				"line1": self._safe(adres, 'AdresL1'),
				"line2": self._safe(adres, 'AdresL2'),
			}

		# Adres korespondencyjny (opcjonalny, może wystąpić u Podmiot1 lub Podmiot2)
		adres_koresp = node.find('.//fa:AdresKoresp', namespaces=self.ns)
		if adres_koresp is not None:
			result["correspondence_address"] = {
				"country_code": self._safe(adres_koresp, 'KodKraju'),
				"line1": self._safe(adres_koresp, 'AdresL1'),
				"line2": self._safe(adres_koresp, 'AdresL2'),
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

	def _parse_additional_info(self):
		"""
		Parsuje listę Fa/DodatkowyOpis (Klucz/Wartosc).
		Element może wystąpić wielokrotnie (dowolna liczba par).
		"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return []

		result = []
		for node in fa.findall('fa:DodatkowyOpis', namespaces=self.ns):
			key = self._safe(node, 'Klucz')
			value = self._safe(node, 'Wartosc')
			if key or value:
				result.append({
					"key": key or '',
					"value": value or '',
				})

		return result

	def _parse_transaction_conditions(self):
		"""
		Parsuje warunki transakcji:
		- Fa/WarunkiTransakcji/Zamowienia (DataZamowienia + NrZamowienia), wielokrotne
		- Fa/WZ (numery dokumentów magazynowych WZ), wielokrotne, bezpośrednio pod Fa
		  (WZ NIE jest zagnieżdżone w WarunkiTransakcji w schemacie FA(3)).
		"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return {"orders": [], "wz_documents": []}

		orders = []
		warunki = fa.find('fa:WarunkiTransakcji', namespaces=self.ns)
		if warunki is not None:
			for node in warunki.findall('fa:Zamowienia', namespaces=self.ns):
				date = self._safe(node, 'DataZamowienia')
				number = self._safe(node, 'NrZamowienia')
				if date or number:
					orders.append({
						"date": date or '',
						"number": number or '',
					})

		wz_documents = [
			node.text.strip()
			for node in fa.findall('fa:WZ', namespaces=self.ns)
			if node.text and node.text.strip()
		]

		return {
			"orders": orders,
			"wz_documents": wz_documents,
		}

	def _parse_registries(self):
		"""
		Parsuje Stopka/Rejestry (KRS, REGON). Element opcjonalny na poziomie
		całego dokumentu (nie Fa) - dotyczy wystawcy.
		"""
		node = self.tree.find('.//fa:Stopka/fa:Rejestry', namespaces=self.ns)
		if node is None:
			return {}

		krs = self._safe(node, 'KRS')
		regon = self._safe(node, 'REGON')

		if not (krs or regon):
			return {}

		return {
			"krs": krs or '',
			"regon": regon or '',
		}

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

	# ==============================================================================================
	# poprzednio : _parse_zal_summary_lines
	#  
	# ==============================================================================================
	def _parse_zal_accounting_lines(self):
		"""
		Fallback PDF dla ZAL bez ZamowienieWiersz.

		Tworzy znormalizowane pozycje techniczne na podstawie
		pól podsumowania P_13_* / P_14_*.

		Nie modyfikuje account.move ani account.move.line.
		Służy wyłącznie do prezentacji PDF.
		"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)

		if fa is None:
			return []

		lines = []
		line_number = 1

		for item in self.VAT_SUMMARY_FIELDS:
			net_raw = self._safe(
				fa,
				item["net_field"]
			)

			if not self._has_amount(net_raw):
				continue

			vat_raw = ""

			if item.get("vat_field"):
				vat_raw = self._safe(
					fa,
					item["vat_field"]
				) or ""

			net = self._format_optional_amount(net_raw)
			vat = self._format_optional_amount(vat_raw)

			if vat_raw not in (None, ""):
				gross = self._sum_amounts(
					net_raw,
					vat_raw
				)
			else:
				gross = self._format_optional_amount(
					net_raw
				)

			lines.append({
				"line_number": str(line_number),

				"name": (
					f"Zaliczka KSeF – stawka "
					f"{item['rate_label']}"
				),

				"qty": "1",
				"unit": "",

				# jedna techniczna pozycja = cała podstawa danej stawki
				"price": net,
				"price_gross": "",

				"net": net,
				"vat": vat,
				"gross": gross,

				"vat_rate": item["rate"],
				"vat_rate_label": item["rate_label"],

				"discount": "",
				"exchange_rate": "",

				"is_before_correction": False,
				"identifiers": [],

				# informacja dla szablonu / diagnostyki
				"synthetic": True,
				"source": "vat_summary",
			})

			line_number += 1

		return lines

	# ==============================================================================================
	def _gross_to_net(self, gross_value, vat_rate):
		"""
		Przelicza kwotę brutto na netto na podstawie stawki VAT (P_12).
		Dla wierszy FA(3) w wariancie brutto (P_9B/P_11A) zamiast netto
		(P_9A/P_11) - spójne z konwersją w communication_provider_ksef_addons.py.
		Dla stawek nieliczbowych (zw/np/oo) zwraca wartość bez przeliczenia.
		"""
		rate = self._to_float(vat_rate)
		divisor = (1 + rate / 100) if rate else 1.0
		return f"{self._to_float(gross_value) / divisor:.2f}"

	# ==============================================================================================

	def _parse_lines(self, invoice_type):
		lines = []
		if invoice_type == "ZAL":
			return self._parse_zal_accounting_lines()
		elif invoice_type == "KOR_ZAL":
			nodes = self.tree.findall(
				".//fa:ZamowienieWiersz",
				namespaces=self.ns
			)
			for node in nodes:
				lines.append(
					self._parse_order_line(
						node,
						correction=True
					)
				)
		else:
			# VAT, ROZ, KOR - linie z FaWiersz
			nodes = self.tree.findall('.//fa:FaWiersz', namespaces=self.ns)
			for node in nodes:
				vat_rate = self._safe(node, 'P_12')
				net = self._safe(node, 'P_11')
				vat = self._safe(node, 'P_11Vat')
				gross = self._safe(node, 'P_11A')

				# Cena jednostkowa - wariant netto (P_9A) lub, gdy go brak,
				# brutto (P_9B) przeliczone stawką P_12.
				price_raw = self._safe(node, 'P_9A')
				price_gross_raw = self._safe(node, 'P_9B')

				price = price_raw
				if not self._has_amount(price_raw) and self._has_amount(price_gross_raw):
					price = self._gross_to_net(price_gross_raw, vat_rate)

				# Wartość pozycji - analogicznie: netto (P_11) lub przeliczone
				# z brutto (P_11A).
				net_for_display = net
				if not self._has_amount(net) and self._has_amount(gross):
					net_for_display = self._gross_to_net(gross, vat_rate)

				lines.append({
					# identyfikacja wiersza
					"line_number": self._safe(node, 'NrWierszaFa'),
					# podstawowe dane pozycji
					"name": self._safe(node, 'P_7'),
					"unit": self._safe(node, 'P_8A'),
					"qty": self._format_optional_amount(self._safe(node, 'P_8B')),
					# ceny jednostkowe
					"price": self._format_optional_amount(price),
					"price_gross": self._format_optional_amount(price_gross_raw),
					# opust / obniżka, jeżeli występuje
					"discount": self._safe(node, 'P_10'),
					# wartości pozycji z XML
					"net": self._format_optional_amount(net_for_display),
					"vat": self._format_optional_amount(vat),
					"gross": self._compute_line_gross(net, vat, gross),
					# stawka podatku
					"vat_rate": vat_rate,
					"vat_rate_label": self._format_vat_rate_label(vat_rate),
					# dane dodatkowe
					"exchange_rate": self._safe(node, 'KursWaluty'),
					"is_before_correction": self._safe(node, 'StanPrzed') == '1',
					"identifiers": self._collect_line_identifiers(node, zal=False),
				})
		return lines

	# ==============================================================================================
	# Tabelka podatków
	def _parse_totals(self, invoice_type):
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return {}

		vat_breakdown = self._parse_vat_breakdown()

		net_total = sum(self._to_float(row.get("net")) for row in vat_breakdown)
		vat_total = sum(self._to_float(row.get("vat")) for row in vat_breakdown)

		# P_15 jest nadrzędną kwotą należności ogółem.
		gross_total = self._safe(fa, 'P_15')

		totals = {
			"net": f"{net_total:.2f}",
			"vat": f"{vat_total:.2f}",
			"gross": self._format_amount(gross_total),
			"vat_breakdown": vat_breakdown,
			"currency_rate": self._safe(fa, 'KursWalutyZ'),
		}

		if invoice_type in ['KOR', 'KOR_ZAL', 'KOR_ROZ']:
			totals["is_correction"] = True

		return totals

	def _parse_vat_breakdown(self, lines=None):
		"""
		Parsuje podsumowanie stawek VAT z pól P_13_* / P_14_*.

		Podstawowym źródłem danych jest sekcja Fa, a nie linie faktury.
		Linie są tylko fallbackiem, gdy XML nie zawiera pól podsumowania.
		"""
		fa = self.tree.find('.//fa:Fa', namespaces=self.ns)
		if fa is None:
			return []

		vat_breakdown = []

		for item in self.VAT_SUMMARY_FIELDS:
			net_raw = self._safe(fa, item["net_field"])

			if not self._has_amount(net_raw):
				continue

			vat_raw = ""
			if item.get("vat_field"):
				vat_raw = self._safe(fa, item["vat_field"])

			vat_pln_raw = ""
			if item.get("vat_pln_field"):
				vat_pln_raw = self._safe(fa, item["vat_pln_field"])

			net = self._to_float(net_raw)
			vat = self._to_float(vat_raw)
			gross = net + vat

			row = {
				"source": "summary",
				"net_field": item["net_field"],
				"vat_field": item.get("vat_field") or "",
				"vat_pln_field": item.get("vat_pln_field") or "",
				"rate": item["rate"],
				"rate_label": item["rate_label"],
				"description": item["description"],
				"net": f"{net:.2f}",
				"vat": f"{vat:.2f}",
				"gross": f"{gross:.2f}",
			}

			if self._has_amount(vat_pln_raw):
				row["vat_pln"] = self._format_amount(vat_pln_raw)

			vat_breakdown.append(row)

		# Fallback techniczny: gdyby XML nie miał P_13_*,
		# próbujemy zsumować linie, jak w starej wersji.
		if not vat_breakdown:
			vat_breakdown = self._parse_vat_breakdown_from_lines(lines)

		return vat_breakdown

	def _parse_vat_breakdown_from_lines(self, lines=None):
		"""
		Fallback: buduje VAT breakdown z pozycji faktury.

		Używane tylko wtedy, gdy w Fa nie ma pól P_13_*.
		"""
		if lines is None:
			lines = self._parse_lines(self._get_invoice_type())

		vat_rates = {}

		for line in lines:
			rate = line.get('vat_rate') or ''
			if not rate:
				continue

			if rate not in vat_rates:
				vat_rates[rate] = {
					'net': 0.0,
					'vat': 0.0,
					'gross': 0.0,
				}

			net = self._to_float(line.get('net'))
			vat = self._to_float(line.get('vat'))

			vat_rates[rate]['net'] += net
			vat_rates[rate]['vat'] += vat
			vat_rates[rate]['gross'] += net + vat

		vat_breakdown = []

		for rate, values in vat_rates.items():
			vat_breakdown.append({
				"source": "lines",
				"rate": rate,
				"rate_label": self._format_vat_rate_label(rate),
				"description": "",
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

		annotations = {
			"cash_accounting": False,
			"self_billing": False,
			"reverse_charge": False,
			"split_payment": False,
			"exempt": False,
			"exemption_basis": "",
			"new_transport": False,
			"simplified_triangular": False,
			"margin": False,
			"margin_type": "",
		}

		adnotacje = fa.find('.//fa:Adnotacje', namespaces=self.ns)
		if adnotacje is None:
			return annotations

		# P_16: metoda kasowa
		annotations["cash_accounting"] = self._safe(adnotacje, 'P_16') == '1'

		# P_17: samofakturowanie
		annotations["self_billing"] = self._safe(adnotacje, 'P_17') == '1'

		# P_18: odwrotne obciążenie
		annotations["reverse_charge"] = self._safe(adnotacje, 'P_18') == '1'

		# P_18A: mechanizm podzielonej płatności
		annotations["split_payment"] = self._safe(adnotacje, 'P_18A') == '1'

		# Zwolnienie: pozytywne jest P_19=1, nie P_19N
		if self._safe(adnotacje, 'Zwolnienie/P_19') == '1':
			annotations["exempt"] = True
			annotations["exemption_basis"] = (
				self._safe(adnotacje, 'Zwolnienie/P_19A')
				or self._safe(adnotacje, 'Zwolnienie/P_19B')
				or self._safe(adnotacje, 'Zwolnienie/P_19C')
				or ''
			)

		# Nowe środki transportu: pozytywne jest P_22=1, nie P_22N
		annotations["new_transport"] = (
			self._safe(adnotacje, 'NoweSrodkiTransportu/P_22') == '1'
		)

		# P_23: procedura uproszczona w transakcji trójstronnej
		annotations["simplified_triangular"] = self._safe(adnotacje, 'P_23') == '1'

		# Procedura marży: pozytywne jest P_PMarzy=1, nie P_PMarzyN
		if self._safe(adnotacje, 'PMarzy/P_PMarzy') == '1':
			annotations["margin"] = True

			margin_types = []
			if self._safe(adnotacje, 'PMarzy/P_PMarzy_2') == '1':
				margin_types.append('procedura marży dla biur podróży')
			if self._safe(adnotacje, 'PMarzy/P_PMarzy_3_1') == '1':
				margin_types.append('procedura marży - towary używane')
			if self._safe(adnotacje, 'PMarzy/P_PMarzy_3_2') == '1':
				margin_types.append('procedura marży - dzieła sztuki')
			if self._safe(adnotacje, 'PMarzy/P_PMarzy_3_3') == '1':
				margin_types.append('procedura marży - przedmioty kolekcjonerskie i antyki')

			annotations["margin_type"] = ', '.join(margin_types)

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
		"""
		Kompatybilność wsteczna.

		Nowe dane korekty są w:
			ksef["correction"]["corrected_invoices"]
		"""
		correction = self._parse_correction(invoice_type)
		items = correction.get("corrected_invoices") or []
		return items[0] if items else {}

	def _parse_advance_invoice(self, node):
		"""
		Dane identyfikacyjne faktury zaliczkowej rozliczanej przez ROZ.

		FA(3) przewiduje dwa warianty:
		- faktura poza KSeF:
			NrKSeFZN = 1
			NrFaZaliczkowej
		- faktura w KSeF:
			NrKSeFFaZaliczkowej
		"""
		if node is None:
			return {}

		outside_ksef = self._safe(node, "NrKSeFZN") == "1"
		ksef_id = self._safe(node, "NrKSeFFaZaliczkowej") or ""

		return {
			"number": self._safe(node, "NrFaZaliczkowej") or "",
			"ksef_marker": bool(ksef_id),
			"outside_ksef_marker": outside_ksef,
			"ksef_id": self._safe(node, "NrKSeFFaZaliczkowej") or "",
		}

	def _parse_partial_advance(self, node):
		"""
		Pojedyncza płatność składająca się na kwotę zaliczki.

		Pola FA(3):
		- P_6Z		  data otrzymania płatności,
		- P_15Z		 kwota płatności,
		- KursWalutyZW  opcjonalny kurs waluty.
		"""
		if node is None:
			return {}

		return {
			"date": self._safe(node, "P_6Z") or "",
			"amount": self._format_optional_amount(
				self._safe(node, "P_15Z")
			),
			"exchange_rate": self._safe(
				node,
				"KursWalutyZW"
			) or "",
		}


	def _parse_order_line(self, node, correction=False):
		"""
		Parsuje ZamowienieWiersz dla ZAL oraz KOR_ZAL.
		"""
		vat_rate = self._safe(node, "P_12Z")
		net = self._safe(node, "P_11NettoZ")
		vat = self._safe(node, "P_11VatZ")

		return {
			"line_number": self._safe(node, "NrWierszaZam"),

			"name": self._safe(node, "P_7Z"),
			"qty": self._format_optional_amount(self._safe(node, "P_8BZ")),
			"unit": self._safe(node, "P_8AZ"),

			"price": self._format_optional_amount(
				self._safe(node, "P_9AZ")
			),

			# ZamowienieWiersz nie ma ceny jednostkowej brutto.
			"price_gross": "",

			"net": self._format_optional_amount(net),
			"vat": self._format_optional_amount(vat),

			# Brutto pozycji pomocniczo z netto + VAT.
			"gross": self._compute_line_gross(
				net,
				vat,
				""
			),

			"vat_rate": vat_rate,
			"vat_rate_label": self._format_vat_rate_label(vat_rate),

			# ZamowienieWiersz nie ma P_10Z.
			"discount": "",

			"exchange_rate": "",

			"is_before_correction": (
				correction
				and self._safe(node, "StanPrzedZ") == "1"
			),

			"identifiers": self._collect_line_identifiers(
				node,
				zal=True
			),
		}

	def _parse_advance(self, invoice_type):
		"""
		Parsuje dane zaliczek i rozliczenia zaliczek.

		Obejmuje:
		- Zamowienie / WartoscZamowienia,
		- FakturaZaliczkowa,
		- ZaliczkaCzesciowa.
		"""
		if invoice_type not in ["ZAL", "ROZ", "KOR_ZAL", "KOR_ROZ"]:
			return {}

		fa = self.tree.find(".//fa:Fa", namespaces=self.ns)
		if fa is None:
			return {}

		advance = {
			"exists": True,
			"order_value": "",
			"order_lines": [],
			"advance_invoices": [],
			"partial_advances": [],
		}

		zamowienie = fa.find("fa:Zamowienie", namespaces=self.ns)
		if zamowienie is not None:
			advance["order_value"] = self._format_optional_amount(
				self._safe(zamowienie, "WartoscZamowienia")
			)

			for node in zamowienie.findall(
				"fa:ZamowienieWiersz",
				namespaces=self.ns
			):
				advance["order_lines"].append(
					self._parse_order_line(
						node,
						correction=(invoice_type == "KOR_ZAL")
					)
				)

		for node in fa.findall("fa:FakturaZaliczkowa", namespaces=self.ns):
			item = self._parse_advance_invoice(node)
			if any(item.values()):
				advance["advance_invoices"].append(item)

		for node in fa.findall("fa:ZaliczkaCzesciowa", namespaces=self.ns):
			item = self._parse_partial_advance(node)
			if any(item.values()):
				advance["partial_advances"].append(item)

		# Jeśli typ jest zaliczkowy/rozliczeniowy, ale brak danych szczegółowych,
		# nadal zwracamy exists=True, bo sam RodzajFaktury jest informacją.
		return advance

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

		# 0. Ustalamy poprawnie datę wydruku
		print_dt = fields.Datetime.context_timestamp(
			self,
			fields.Datetime.now()
		)

		print_datetime = print_dt.strftime('%Y-%m-%d %H:%M:%S')

		# 1. Przygotowanie docelowej nazwy pliku
		ksef_title = self.ksef_number
		report_file_name = f"KSeF-{ksef_title}.pdf".replace('/', '_')

		# 2. Słownik dedykowany TYLKO dla wewnętrznego renderowania załącznika w pamięci RAM serwera
		# (Zapobiega błędowi KeyError: 'context' i zapewnia pełną treść w pliku PDF załącznika)
		render_data_for_pdf = {
			'ksef_preview_data': normalized,
			'docs': self,
			'doc': self,
			'context': {
				'move_id': self.id,
				'active_id': self.id,
				'active_model': 'account.move',
				'ksef_preview_data': normalized,
				'print_datetime': print_datetime,
			}
		}

		# 3. WYSZUKIWANIE ISTNIEJĄCEGO ZAŁĄCZNIKA
		existing_attachment = self.env['ir.attachment'].search([
			('res_model', '=', 'account.move'),
			('res_id', '=', self.id),
			('name', '=', report_file_name)
		], limit=1)

		# 4. ŚCIEŻKA A: Załącznik już istnieje – otwieramy go bez ponownego renderowania
		if existing_attachment:
			return {
				'type': 'ir.actions.act_url',
				'url': '/web/content/%s?download=false' % existing_attachment.id,
				'target': 'new',
			}

		# 5. ŚCIEŻKA B: Jeśli załącznik NIE istnieje - proces pierwszej generacji
		report_record = self.env.ref('hfb_xmlmap_exporter.action_report_ksef_invoice')
		
		# Do generowania pliku w pamięci podajemy słownik z obiektami i contextem
		pdf_content, content_type = report_record.with_context(
			active_id=self.id,
			move_id=self.id,
			active_model='account.move',
			ksef_preview_data=normalized,
			print_datetime=print_datetime,
			)._render_qweb_pdf(
				report_record.report_name,
				self.ids,
				data=render_data_for_pdf,
			)

		# Rejestracja nowego załącznika w systemie
		attachment = self.env['ir.attachment'].create({
			'name': report_file_name,
			'type': 'binary',
			'datas': base64.b64encode(pdf_content),
			'res_model': 'account.move',
			'res_id': self.id,
			'mimetype': 'application/pdf',
		})

		# Wywołanie pobierania dla pierwszej generacji (identycznie jak w Ścieżce A)
		report_for_download = report_record.with_context(must_skip_send_mail=True)
		report_for_download.name = report_file_name.replace('.pdf', '')

		if attachment != False:
			return {
				'type': 'ir.actions.act_url',
				'url': '/web/content/%d?download=false' % attachment.id,
				'target': 'new',
			}
		else:
			return report_for_download.with_context(
				active_id=self.id,
				move_id=self.id,
				active_model='account.move',
				ksef_preview_data=normalized,
				print_datetime=print_datetime,
			).report_action(self, data={'ksef_preview_data': normalized})


	def _get_ksef_communication(self):
		"""Pomocnicza metoda do pobrania komunikacji KSeF"""
		return self.env['communication.log'].search([
			('document_model', '=', 'account.move'),
			('document_id', '=', self.id),
			('file_data', '!=', False),
		], limit=1, order='create_date DESC')


	#################################################################

	#################################################################


class CommunicationLog(models.Model):
	_inherit = "communication.log"

	#####################################################################################
	# Główna metoda odtwarzania faktury przychodzącej 
	# uzupełnienie o wykonanie akcji generowania załącznika faktury pdf z xml
	#####################################################################################
	def action_restore_ksef_invoice(self):
		invoice = super(CommunicationLog, self).action_restore_ksef_invoice()
		if invoice:
			try:
				invoice.action_preview_ksef_pdf()
			except Exception:
				_logger.exception("Nie udało się wygenerować podglądu PDF KSeF.")
		return invoice

#EoF

# -*- coding: utf-8 -*-
#################################################################################
#
# Odoo, Open ERP Source Management Solution
# Copyright (C) 17-25 Hadron for business sp. z o.o. (http://www.hadron.eu.com)
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
""" @version 16.1.2
	@owner  Hadron for Business
	@author andrzej wiśniewski warp3r
	@date   2025.10.15
"""
#################################################################################
#   Rozszerzenie CommunicationLog dla importu faktur KSeF z XML do Odoo 18
#   Pełna obsługa typów faktur: VAT, ZAL, ROZ, KOR, KOR_ZAL, KOR_ROZ, UPR
#################################################################################

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
import re
import os
import json
from lxml import etree
import base64
import subprocess
import tempfile
import logging
import uuid
import psycopg2
from pathlib import Path
import time
import signal
from markupsafe import Markup, escape
_logger = logging.getLogger(__name__)


class CommunicationLog(models.Model):
	_inherit = "communication.log"

	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	# ROZSZERZENIE SPOZA DOKUMENTACJI FSEF (fragment - do uzupełnienia)
	#  Użycie:
	#   uom_type = self.UN_CEFACT_UOM.get(raw.ksef_p_8a, "quantity")
	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	UN_CEFACT_UOM = {
		"C62": "quantity",
		"HUR": "quantity",
		"DAY": "quantity",
		"KGM": "quantity",
		"LTR": "quantity",
		"P1":  "percent",
	}

	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	# TYLKO NA CZAS ROZWOJU - DO USUNIĘCIA PO IMPLEMENTACJI W NODE'ach
	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	def _extract_kor_zal_special_fields(self, xml_root, values):
		"""
		Wyciąga specjalne pola dla faktur KOR_ZAL
		"""
		ns_uri = xml_root.nsmap.get(None)
		
		# 1. Wartość zamówienia (ważne dla zaliczek)
		wartosc_zam = self._extract_direct_value(xml_root, './/WartoscZamowienia')
		if wartosc_zam:
			try:
				values['ksef_order_value'] = float(wartosc_zam.replace(',', '.'))
				_logger.info("💰 KOR_ZAL WartoscZamowienia: %s", values['ksef_order_value'])
			except (ValueError, TypeError) as e:
				_logger.warning("⚠️ Cannot parse WartoscZamowienia: %s", wartosc_zam)
		
		# 2. P_15ZK - wartość przed korektą
		p15zk = self._extract_direct_value(xml_root, './/P_15ZK')
		if p15zk:
			try:
				values['ksef_p15zk'] = float(p15zk.replace(',', '.'))
				_logger.info("📊 KOR_ZAL P_15ZK: %s", values['ksef_p15zk'])
			except (ValueError, TypeError) as e:
				values['ksef_p15zk'] = p15zk  # Zapisz jako tekst
		
		# 3. Przyczyna korekty (jeśli jest)
		przyczyna = self._extract_direct_value(xml_root, './/PrzyczynaKorekty')
		if przyczyna:
			values['ksef_przyczyna_korekty'] = przyczyna
			_logger.info("📝 KOR_ZAL PrzyczynaKorekty: %s", przyczyna)
		
		# 4. Typ korekty
		typ_korekty = self._extract_direct_value(xml_root, './/TypKorekty')
		if typ_korekty:
			values['ksef_correction_type_code'] = typ_korekty
		
		# 5. Dodaj informację do nazwy/opisu faktury
		if 'ref' in values and (wartosc_zam or p15zk):
			info_parts = []
			if wartosc_zam:
				info_parts.append(f"Zam: {wartosc_zam}")
			if p15zk:
				info_parts.append(f"Przed: {p15zk}")
			
			if info_parts:
				values['name'] = f"{values.get('name', values.get('ref', ''))} [{' | '.join(info_parts)}]"
		
		return values
		
	def _process_kor_zal_correction_lines(self, xml_root, ns):
		"""
		Przetwarza wiersze korekty faktury zaliczkowej (KOR_ZAL)
		ze strukturą ZamowienieWiersz
		"""
		lines_values = []
		ns_uri = ns.get('ns') if ns else None
		
		# Znajdź WSZYSTKIE ZamowienieWiersz
		if ns_uri:
			zam_wiersze = xml_root.findall(f'.//{{{ns_uri}}}ZamowienieWiersz')
		else:
			zam_wiersze = xml_root.findall('.//ZamowienieWiersz')
		
		if not zam_wiersze:
			_logger.warning("⚠️ KOR_ZAL: No ZamowienieWiersz found!")
			return lines_values
		
		_logger.info("🏗️ KOR_ZAL: Processing %d ZamowienieWiersz", len(zam_wiersze))
		
		# Grupuj wiersze po NrWierszaZam
		wiersze_by_nr = {}
		for zam_wiersz in zam_wiersze:
			nr_wiersza = self._get_xml_value(zam_wiersz, 'NrWierszaZam', ns) or "0"
			stan_przed_z = self._get_xml_value(zam_wiersz, 'StanPrzedZ', ns)
			
			wiersze_by_nr.setdefault(nr_wiersza, [])
			wiersze_by_nr[nr_wiersza].append({
				'element': zam_wiersz,
				'stan_przed_z': stan_przed_z,
				'is_before': stan_przed_z == '1',
				'is_after': stan_przed_z != '1'  # Brak lub inna wartość = stan po
			})
		
		# Przetwarzaj każdą grupę
		for nr_wiersza, wiersze_list in sorted(wiersze_by_nr.items(), key=lambda x: int(x[0])):
			if len(wiersze_list) != 2:
				_logger.warning("⚠️ KOR_ZAL position %s: expected 2 elements, got %d", 
							  nr_wiersza, len(wiersze_list))
			
			# Sortuj: stan przed (1), potem stan po
			wiersze_list.sort(key=lambda x: 0 if x['is_before'] else 1)
			
			base_sequence = int(nr_wiersza) * 10
			
			# 1. Wiersz-note "ZALICZKA - STAN PRZED"
			lines_values.append((0, 0, {
				'name': f"### ZALICZKA - STAN PRZED korektą (poz. {nr_wiersza}) ###",
				'quantity': 0,
				'price_unit': 0,
				'display_type': 'line_note',
				'sequence': base_sequence - 5,
			}))
			
			# 2. Wiersze STAN PRZED (ujemne!)
			for wiersz_data in [w for w in wiersze_list if w['is_before']]:
				line_vals = self._create_kor_zal_line_from_element(
					wiersz_data['element'], ns, nr_wiersza, is_before=True
				)
				if line_vals:
					line_vals['sequence'] = base_sequence
					lines_values.append((0, 0, line_vals))
			
			# 3. Wiersz-note "ZALICZKA - STAN PO"
			lines_values.append((0, 0, {
				'name': f"### ZALICZKA - STAN PO korekcie (poz. {nr_wiersza}) ###",
				'quantity': 0,
				'price_unit': 0,
				'display_type': 'line_note',
				'sequence': base_sequence + 95,
			}))
			
			# 4. Wiersze STAN PO (dodatnie)
			for wiersz_data in [w for w in wiersze_list if w['is_after']]:
				line_vals = self._create_kor_zal_line_from_element(
					wiersz_data['element'], ns, nr_wiersza, is_before=False
				)
				if line_vals:
					line_vals['sequence'] = base_sequence + 100
					lines_values.append((0, 0, line_vals))
		
		# Sortuj według sequence
		lines_values.sort(key=lambda x: x[2].get('sequence', 0))
		
		_logger.info("✅ KOR_ZAL: Created %d total lines", len(lines_values))
		return lines_values	
		
	def _create_kor_zal_line_from_element(self, element, ns, nr_wiersza, is_before=False):
		"""
		Tworzy wiersz faktury dla KOR_ZAL z elementu ZamowienieWiersz
		Obsługuje suffix Z we wszystkich polach
		"""
		# Pobierz wartości (używając suffixu Z!)
		p7z = self._get_xml_value(element, 'P_7Z', ns) or f"Zaliczka {nr_wiersza}"
		p8az = self._get_xml_value(element, 'P_8AZ', ns)
		p8bz = self._get_xml_value(element, 'P_8BZ', ns)
		p9az = self._get_xml_value(element, 'P_9AZ', ns)
		p11nettoz = self._get_xml_value(element, 'P_11NettoZ', ns)
		p12z = self._get_xml_value(element, 'P_12Z', ns)
		
		# Przygotuj wiersz
		line_vals = {
			'name': p7z,
			'ksef_line_no': int(nr_wiersza),
			#'ksef_is_advance_line': True,  # Flaga wiersza zaliczkowego
		}
		
		# ILOŚĆ - dla zaliczek zwykle 1, ale obsługujemy różne wartości
		quantity = 1.0
		if p8bz:
			try:
				quantity = float(p8bz.replace(',', '.'))
			except (ValueError, TypeError):
				quantity = 1.0
		
		# Dla korekt: stan przed = ujemny, stan po = dodatni
		if is_before:
			line_vals['quantity'] = -abs(quantity)
			line_vals['name'] = f"[ZAL-PRZED] {p7z}"
		else:
			line_vals['quantity'] = abs(quantity)
			line_vals['name'] = f"[ZAL-PO] {p7z}"
		
		# CENA JEDNOSTKOWA - preferuj P_9AZ
		price_unit = 0.0
		if p9az:
			try:
				price_unit = float(p9az.replace(',', '.'))
			except (ValueError, TypeError):
				pass
		
		# Fallback: oblicz z netto/ilość
		if price_unit == 0.0 and p11nettoz:
			try:
				netto = float(p11nettoz.replace(',', '.'))
				if quantity != 0:
					price_unit = abs(netto / quantity)
			except (ValueError, TypeError):
				pass
		
		line_vals['price_unit'] = price_unit
		
		# PODATEK - P_12Z (23, 8, zw, np, etc.)
		if p12z:
			tax_ids = self._find_tax_ids_by_name(p12z)
			if tax_ids:
				line_vals['tax_ids'] = [(6, 0, tax_ids)]
			else:
				_logger.warning("⚠️ KOR_ZAL: Tax not found for %s", p12z)
		
		# JEDNOSTKA MIARY - P_8AZ
		if p8az:
			uom = self._find_uom_by_name(p8az)
			if uom:
				line_vals['product_uom_id'] = uom.id
		
		# Dodatkowe info dla debugowania
		if p11nettoz:
			try:
				netto_val = float(p11nettoz.replace(',', '.'))
				line_vals['ksef_correction_info'] = f"Netto: {netto_val}"
			except:
				pass
		
		_logger.debug("🏗️ KOR_ZAL line %s: %s, qty=%s, price=%s", 
					  "PRZED" if is_before else "PO",
					  line_vals['name'], line_vals['quantity'], line_vals['price_unit'])
		
		return line_vals	
		
	def _get_xml_value(self, container, field_name, ns):
		"""
		Pobiera wartość tekstową z elementu XML - POPRAWIONA dla suffixów
		"""
		ns_uri = ns.get('ns') if ns else None
		
		# Dla KOR_ZAL: pola mają suffix Z (P_7Z, P_8AZ, etc.)
		# Ale mogą też być bez suffixu w innych fakturach
		# Spróbuj kolejno: z suffixem, bez suffixu
		
		# Lista wersji do wypróbowania
		versions_to_try = [field_name]
		
		# Jeśli pole kończy się na Z, spróbuj też bez Z
		if field_name.endswith('Z'):
			versions_to_try.append(field_name[:-1])
		
		# Jeśli pole nie kończy się na Z, spróbuj też z Z
		elif not field_name.endswith('Z') and field_name.startswith('P_'):
			versions_to_try.append(f"{field_name}Z")
		
		for version in versions_to_try:
			try:
				if ns_uri:
					element = container.find(f'{{{ns_uri}}}{version}')
					if element is None:
						element = container.find(f'.//{{{ns_uri}}}{version}')
				else:
					element = container.find(version)
					if element is None:
						element = container.find(f'.//{version}')
				
				if element is not None and element.text:
					return element.text.strip()
					
			except Exception as e:
				_logger.debug("Error getting XML value %s (tried as %s): %s", 
							 field_name, version, e)
		
		return None	

	# ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	def _create_correction_line_from_element(self, element, ns, nr_wiersza, is_before=False):
		"""
		Tworzy wiersz faktury z elementu FaWiersz z uwzględnieniem:
		- is_before=True: ilość ujemna (StanPrzed=1)
		- is_before=False: normalna ilość
		"""
		# Pobierz wartości
		p7 = self._get_xml_value(element, 'P_7', ns) or f"Pozycja {nr_wiersza}"
		p8a = self._get_xml_value(element, 'P_8A', ns)
		p8b = self._get_xml_value(element, 'P_8B', ns)
		p9a = self._get_xml_value(element, 'P_9A', ns)
		p11 = self._get_xml_value(element, 'P_11', ns)
		p12 = self._get_xml_value(element, 'P_12', ns)
		
		# Przygotuj wiersz
		line_vals = {
			'name': p7,
			'sequence': int(nr_wiersza) * 10,  # Zachowujemy oryginalny numer
		}
		
		# ILOŚĆ - kluczowa logika!
		if p8b:
			try:
				quantity = float(p8b.replace(',', '.'))
				if is_before:
					# Stan przed: ilość UJEMNA
					line_vals['quantity'] = -abs(quantity)
					line_vals['name'] = f"[PRZED] {p7}"
				else:
					# Stan po: ilość normalna
					line_vals['quantity'] = abs(quantity)
					line_vals['name'] = f"[PO] {p7}"
			except:
				line_vals['quantity'] = -1.0 if is_before else 1.0
		else:
			line_vals['quantity'] = -1.0 if is_before else 1.0
		
		# CENA JEDNOSTKOWA
		price_set = False
		if p9a:
			try:
				line_vals['price_unit'] = float(p9a.replace(',', '.'))
				price_set = True
			except:
				pass
		
		if not price_set and p11 and p8b:
			try:
				netto = float(p11.replace(',', '.'))
				ilosc = float(p8b.replace(',', '.'))
				if ilosc != 0:
					line_vals['price_unit'] = abs(netto / ilosc)
					price_set = True
			except:
				pass
		
		if not price_set:
			line_vals['price_unit'] = 0.0
		
		# PODATEK
		if p12:
			tax_ids = self._find_tax_ids_by_name(p12)
			if tax_ids:
				line_vals['tax_ids'] = [(6, 0, tax_ids)]
		
		# JEDNOSTKA MIARY
		if p8a:
			uom = self._find_uom_by_name(p8a)
			if uom:
				line_vals['product_uom_id'] = uom.id
		
		# DODATKOWE INFORMACJE
		if is_before:
			line_vals['ksef_is_before_correction'] = True
		
		_logger.debug("📝 Correction line: %s (before=%s), qty=%s, price=%s", 
					  line_vals['name'], is_before, line_vals['quantity'], line_vals['price_unit'])
		
		return line_vals

	def _process_ksef_correction_invoice(self, xml_root, template):
		"""
		Specjalna metoda do przetwarzania faktur korekt KSeF (KOR, KOR_ZAL, KOR_ROZ)
		z bezpośrednim parsowaniem XML (niezależnie od template node'ów)
		"""
		values = {}
		ns_uri = xml_root.nsmap.get(None)
		ns = {'ns': ns_uri} if ns_uri else {}
		
		_logger.info("=" * 80)
		_logger.info("🔄 Processing KSeF correction with direct XML parsing")
		_logger.info("=" * 80)
		
		# 1. Ustal typ faktury
		rodzaj = self._extract_direct_value(xml_root, './/RodzajFaktury')
		if not rodzaj:
			rodzaj = 'KOR'  # domyślnie
		
		values['ksef_rodzaj_faktury'] = rodzaj
		values['move_type'] = 'in_refund'
		
		# 2. Znajdź partnera (Podmiot1) - BEZPOŚREDNIO z XML
		partner_nip = None
		for xpath in [
			'.//Podmiot1//NIP',
			f'.//{{http://crd.gov.pl/wzor/2025/06/25/13775/}}Podmiot1//{{http://crd.gov.pl/wzor/2025/06/25/13775/}}NIP',
		]:
			partner_nip = self._extract_direct_value(xml_root, xpath)
			if partner_nip:
				break
		
		if partner_nip:
			partner = self._find_partner_by_nip(partner_nip)
			if partner:
				values['partner_id'] = partner.id
				_logger.info("✅ Found partner by NIP: %s (%s)", partner_nip, partner.name)
			else:
				_logger.warning("⚠️ Partner not found for NIP: %s", partner_nip)
				values['requires_reversed_entry'] = True
				values['state'] = 'draft'
		
		# 3. Znajdź numer KSeF faktury korygowanej
		corrected_ksef_number = None
		for xpath in [
			'.//NrKSeFFaKorygowanej',
			f'.//{{http://crd.gov.pl/wzor/2025/06/25/13775/}}NrKSeFFaKorygowanej',
		]:
			corrected_ksef_number = self._extract_direct_value(xml_root, xpath)
			if corrected_ksef_number:
				break
		
		if corrected_ksef_number:
			values['ksef_corrected_ref'] = corrected_ksef_number
			
			# Szukaj faktury do skorygowania
			corrected_invoice = self.env['account.move'].search([
				('ksef_number', '=', corrected_ksef_number),
				('company_id', '=', self.env.company.id),
			], limit=1)
			
			if corrected_invoice:
				values['reversed_entry_id'] = corrected_invoice.id
				values['requires_reversed_entry'] = False
				_logger.info("✅ Found corrected invoice: %s (ID: %d)", 
							corrected_invoice.name, corrected_invoice.id)
			else:
				values['requires_reversed_entry'] = True
				values['state'] = 'draft'
				_logger.warning("⚠️ Corrected invoice not found: %s", corrected_ksef_number)
		
		# 4. Pobierz inne kluczowe pola (P_1, P_2, P_6)
		p1 = self._extract_direct_value(xml_root, './/P_1')  # Data wystawienia
		p2 = self._extract_direct_value(xml_root, './/P_2')  # Numer faktury
		p6 = self._extract_direct_value(xml_root, './/P_6')  # Data sprzedaży

		# 4.B NUMER KSeF (zawsze)
		if self.ksef_invoice_number:
			values['ksef_number'] = self.ksef_invoice_number

		if p1:
			values['invoice_date'] = self._parse_date(p1)
		if p2:
			values['ref'] = p2
			values['invoice_origin'] = p2
		if p6:
			values['date'] = self._parse_date(p6)
		
		# 5. Typ korekty
		typ_korekty = self._extract_direct_value(xml_root, './/TypKorekty')
		if typ_korekty:
			values['ksef_correction_type_code'] = typ_korekty
		
		# 6. SPECJALNE PRZETWARZANIE WIERSZY KOREKTY
		if rodzaj == 'KOR_ZAL':
			lines_values = self._process_kor_zal_correction_lines(xml_root, ns)
		else:  # KOR, KOR_ROZ
			lines_values = self._process_correction_lines_with_notes(xml_root, ns)

		if lines_values:
			values['invoice_line_ids'] = lines_values
			_logger.info("✅ Added %d correction lines (with notes)", len(lines_values))
		
		# 7. Domyślne wartości
		if 'company_id' not in values:
			values['company_id'] = self.env.company.id
		
		if 'journal_id' not in values:
			journal = self.env['account.journal'].search([
				('type', '=', 'purchase'),
				('company_id', '=', self.env.company.id),
			], limit=1)
			if journal:
				values['journal_id'] = journal.id
		
		_logger.info("📊 Correction invoice prepared: %d fields, %d lines", 
					len(values), len(lines_values) if 'invoice_line_ids' in values else 0)
		
		_logger.info("✅ Correction processing complete:")
		_logger.info(f"   - Type: {rodzaj}")
		_logger.info(f"   - Partner: {values.get('partner_id', 'Not found')}")
		_logger.info(f"   - Corrected invoice: {values.get('reversed_entry_id', 'Not found')}")
		_logger.info(f"   - Lines: {len(lines_values) if 'invoice_line_ids' in values else 0}")
		_logger.info(f"   - Special fields: {[k for k in values.keys() if 'ksef' in k]}")

		return values

	def _process_correction_lines_with_notes(self, xml_root, ns):
		"""
		Przetwarza wiersze korekty zgodnie z wymaganiami:
		1. NrWierszaFa zachowujemy (nie zwiększamy)
		2. Dla StanPrzed=1: ilość ujemna
		3. Dodajemy wiersze-note "stan przed" i "stan po"
		"""
		lines_values = []
		ns_uri = ns.get('ns') if ns else None
		
		# Znajdź wszystkie wiersze
		if ns_uri:
			fa_wiersze = xml_root.findall(f'.//{{{ns_uri}}}FaWiersz')
		else:
			fa_wiersze = xml_root.findall('.//FaWiersz')
		
		_logger.info("📄 Found %d FaWiersz elements for correction processing", len(fa_wiersze))
		
		# Grupuj wiersze po numerze
		wiersze_by_nr = {}
		for fa_wiersz in fa_wiersze:
			nr_wiersza = self._get_xml_value(fa_wiersz, 'NrWierszaFa', ns) or "0"
			stan_przed = self._get_xml_value(fa_wiersz, 'StanPrzed', ns)
			
			wiersze_by_nr.setdefault(nr_wiersza, [])
			wiersze_by_nr[nr_wiersza].append({
				'element': fa_wiersz,
				'stan_przed': stan_przed,
				'is_before': stan_przed == '1',
				'is_after': stan_przed != '1'  # Brak lub 0 = stan po
			})
		
		# Przetwarzaj każdą grupę wierszy
		for nr_wiersza, wiersze_list in sorted(wiersze_by_nr.items(), key=lambda x: int(x[0])):
			_logger.debug("Processing correction group for position %s: %d elements", 
						 nr_wiersza, len(wiersze_list))
			
			# Sortuj: najpierw stan przed (1), potem stan po (None/0)
			wiersze_list.sort(key=lambda x: 0 if x['is_before'] else 1)
			
			base_sequence = int(nr_wiersza) * 10
			
			# 1. Dodaj wiersz-note "stan przed" (SEKWENCJA: base - 5)
			lines_values.append((0, 0, {
				'name': f"### STAN PRZED korektą (pozycja {nr_wiersza}) ###",
				'quantity': 0,
				'price_unit': 0,
				'display_type': 'line_note',
				'sequence': base_sequence - 5,  # Przed właściwym wierszem
			}))
			
			# 2. Przetwórz wiersze STAN PRZED (SEKWENCJA: base)
			for wiersz_data in [w for w in wiersze_list if w['is_before']]:
				line_vals = self._create_correction_line_from_element(
					wiersz_data['element'], ns, nr_wiersza, is_before=True
				)
				if line_vals:
					line_vals['sequence'] = base_sequence  # Zachowaj oryginalną sekwencję
					lines_values.append((0, 0, line_vals))
			
			# 3. Dodaj wiersz-note "stan po" (SEKWENCJA: base + 95)
			lines_values.append((0, 0, {
				'name': f"### STAN PO korekcie (pozycja {nr_wiersza}) ###",
				'quantity': 0,
				'price_unit': 0,
				'display_type': 'line_note',
				'sequence': base_sequence + 95,  # PO właściwym wierszu (duża liczba żeby było na końcu)
			}))
			
			# 4. Przetwórz wiersze STAN PO (SEKWENCJA: base + 100)
			for wiersz_data in [w for w in wiersze_list if w['is_after']]:
				line_vals = self._create_correction_line_from_element(
					wiersz_data['element'], ns, nr_wiersza, is_before=False
				)
				if line_vals:
					line_vals['sequence'] = base_sequence + 100  # Po notatce
					lines_values.append((0, 0, line_vals))
		
		# Sortuj według sequence
		lines_values.sort(key=lambda x: x[2].get('sequence', 0))
		
		return lines_values


	def _extract_direct_value(self, xml_root, xpath):
		"""Wyciąga wartość bezpośrednio z XML (niezależnie od template) - POPRAWIONA"""
		try:
			# Spróbuj bez namespace
			elem = xml_root.find(xpath)
			
			if elem is None:
				# Dodaj namespace jeśli jest w root
				ns_uri = xml_root.nsmap.get(None)
				if ns_uri:
					# Konwertuj prosty xpath na xpath z namespace
					# Zamienia './/RodzajFaktury' na './/{namespace}RodzajFaktury'
					import re
					if xpath.startswith('.//'):
						element_name = xpath[3:]  # Usuń './/'
						ns_xpath = f'.//{{{ns_uri}}}{element_name}'
						elem = xml_root.find(ns_xpath)
					elif xpath.startswith('//'):
						element_name = xpath[2:]  # Usuń '//'
						ns_xpath = f'//{{{ns_uri}}}{element_name}'
						elem = xml_root.find(ns_xpath)
			
			if elem is not None and elem.text:
				return elem.text.strip()
		except Exception as e:
			_logger.debug("Direct extraction error for %s: %s", xpath, e)
		
		return None

	# =========================================================================
	# GŁÓWNA METODA IMPORTU
	# =========================================================================
	def _process_invoice_lines_zal(self, xml_root, line_nodes, ns):
		"""
		Przetwarza wiersze dla faktur zaliczkowych (ZamowienieWiersz).
		"""
		lines_values = []
		ns_uri = ns.get('ns') if ns else None
		
		# Znajdź WSZYSTKIE ZamowienieWiersz
		if ns_uri:
			line_containers = xml_root.findall(f'.//{{{ns_uri}}}ZamowienieWiersz')
		else:
			line_containers = xml_root.findall('.//ZamowienieWiersz')
		
		_logger.info("📄 Found %d ZAL invoice lines (ZamowienieWiersz)", len(line_containers))
		
		for line_index, line_container in enumerate(line_containers):
			line_vals = {'sequence': (line_index + 1) * 10}
			
			# Pobierz wartości (z suffix Z!)
			p7z = self._get_xml_value(line_container, 'P_7Z', ns)		 # Nazwa
			p8az = self._get_xml_value(line_container, 'P_8AZ', ns)	   # Jednostka
			p8bz = self._get_xml_value(line_container, 'P_8BZ', ns)	   # Ilość
			p9az = self._get_xml_value(line_container, 'P_9AZ', ns)	   # Cena jednostkowa
			p11nettoz = self._get_xml_value(line_container, 'P_11NettoZ', ns)  # Netto
			p11vatz = self._get_xml_value(line_container, 'P_11VatZ', ns) # VAT
			p12z = self._get_xml_value(line_container, 'P_12Z', ns)	   # Stawka VAT
			
			# Nazwa
			if p7z:
				line_vals['name'] = p7z
			else:
				line_vals['name'] = f"Zaliczka {line_index + 1}"
			
			# Ilość
			if p8bz:
				try:
					line_vals['quantity'] = float(p8bz.replace(',', '.'))
				except:
					line_vals['quantity'] = 1.0
			else:
				line_vals['quantity'] = 1.0
			
			# CENA JEDNOSTKOWA - preferuj P_9AZ, potem oblicz z netto
			price_unit_set = False
			if p9az:
				try:
					line_vals['price_unit'] = float(p9az.replace(',', '.'))
					price_unit_set = True
				except:
					pass
			
			if not price_unit_set and p11nettoz and p8bz:
				try:
					netto = float(p11nettoz.replace(',', '.'))
					ilosc = float(p8bz.replace(',', '.'))
					if ilosc != 0:
						line_vals['price_unit'] = netto / ilosc
						price_unit_set = True
				except:
					pass
			
			if not price_unit_set:
				line_vals['price_unit'] = 0.0
			
			# Podatek (P_12Z)
			if p12z:
				tax_ids = self._find_tax_ids_by_name(p12z)
				if tax_ids:
					line_vals['tax_ids'] = [(6, 0, tax_ids)]
			
			# Jednostka (P_8AZ)
			if p8az:
				uom = self._find_uom_by_name(p8az)
				if uom:
					line_vals['product_uom_id'] = uom.id
			
			# Numer wiersza
			nr_wiersza = self._get_xml_value(line_container, 'NrWierszaZam', ns)
			if nr_wiersza:
				try:
					line_vals['sequence'] = int(nr_wiersza) * 10
				except:
					pass
			
			lines_values.append((0, 0, line_vals))
				
			_logger.debug("✅ ZAL Line %d: %s, qty: %s, price: %s", 
						 line_index + 1, 
						 line_vals.get('name', 'No name')[:30],
						 line_vals.get('quantity'),
						 line_vals.get('price_unit'))
		
		return lines_values

	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	# metoda pomocnicza dla głwnej metody odtwarzania faktury przychodzącej
	# +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
	def _create_or_get_partner_from_xml(self, xml_root, party_type='Podmiot1'):
		"""
		Znajduje lub tworzy partnera na podstawie danych z XML.
		Jeśli partner istnieje - zwraca go.
		Jeśli nie istnieje - tworzy z pełnymi danymi z XML.
		"""
		try:
			ns_uri = xml_root.nsmap.get(None)
			ns_prefix = f"{{{ns_uri}}}" if ns_uri else ""
			
			# 1. Pobierz NIP (wymagany) - POPRAWIONE testowanie
			nip_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}NIP')
			
			# Jawne testowanie zamiast "if not nip_elem"
			if nip_elem is None:
				_logger.warning("⚠️ Brak elementu NIP w XML dla %s", party_type)
				return None
			
			if nip_elem.text is None or not nip_elem.text.strip():
				_logger.warning("⚠️ Element NIP istnieje ale jest pusty dla %s", party_type)
				return None
			
			nip = nip_elem.text.strip()
			
			# 2. Najpierw spróbuj znaleźć istniejącego partnera
			existing_partner = self._find_partner_by_nip(nip)
			if existing_partner:
				_logger.info("✅ Found existing partner: %s (NIP: %s)", 
							existing_partner.name, nip)
				return existing_partner
			
			# 3. Jeśli nie ma partnera, utwórz go z pełnymi danami z XML
			_logger.info("🆕 Creating new partner from XML data (NIP: %s)", nip)
			
			# Pobierz nazwę - POPRAWIONE testowanie
			nazwa = f"Partner {nip}"  # Domyślna
			nazwa_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}Nazwa')
			if nazwa_elem is not None and nazwa_elem.text and nazwa_elem.text.strip():
				nazwa = nazwa_elem.text.strip()
			
			# Przygotuj wartości dla partnera
			partner_vals = {
				'name': nazwa,
				'vat': f"PL{nip}" if not nip.startswith('PL') else nip,
				'company_type': 'company',
				'is_company': True,
			}

			ksef_info = []
			ksef_info.append(f"Importowany z KSeF: {self.ksef_invoice_number}")
			ksef_info.append(f"Data importu: {fields.Date.today()}")		
			if 'comment' in partner_vals:
				partner_vals['comment'] = " | ".join(ksef_info) + "\n\n" + partner_vals['comment']
			else:
				partner_vals['comment'] = " | ".join(ksef_info)
	
			# 4. REGON (jeśli istnieje) - POPRAWIONE testowanie
			regon_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}REGON')
			if regon_elem is not None and regon_elem.text and regon_elem.text.strip():
				partner_vals['company_registry'] = regon_elem.text.strip()
			
			# 5. Adres (zgodnie ze schemą XSD) - POPRAWIONE testowanie
			adres_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}Adres')
			if adres_elem is not None:
				# AdresL1 - AdresL4
				street_parts = []
				for i in range(1, 5):
					adresl_elem = adres_elem.find(f'{ns_prefix}AdresL{i}')
					if adresl_elem is not None and adresl_elem.text and adresl_elem.text.strip():
						street_parts.append(adresl_elem.text.strip())
				
				if street_parts:
					partner_vals['street'] = ', '.join(street_parts)
				
				# KodKraju
				kraj_elem = adres_elem.find(f'{ns_prefix}KodKraju')
				if kraj_elem is not None and kraj_elem.text and kraj_elem.text.strip():
					partner_vals['country_code'] = kraj_elem.text.strip()
			
			# 6. Adres korespondencyjny (opcjonalny) - POPRAWIONE testowanie
			adres_koresp_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}AdresKoresp')
			if adres_koresp_elem is not None:
				comment_parts = ["Adres korespondencyjny:"]
				
				for i in range(1, 5):
					adresl_elem = adres_koresp_elem.find(f'{ns_prefix}AdresL{i}')
					if adresl_elem is not None and adresl_elem.text and adresl_elem.text.strip():
						comment_parts.append(adresl_elem.text.strip())
				
				if len(comment_parts) > 1:
					existing_comment = partner_vals.get('comment', '')
					if existing_comment:
						partner_vals['comment'] = f"{existing_comment}\n{' '.join(comment_parts)}"
					else:
						partner_vals['comment'] = ' '.join(comment_parts)
			
			# 7. Dane kontaktowe (opcjonalne, max 3) - POPRAWIONE testowanie
			dane_kontaktowe = xml_root.findall(f'.//{ns_prefix}{party_type}//{ns_prefix}DaneKontaktowe')
			if dane_kontaktowe:
				emails = []
				phones = []
				
				for kontakt in dane_kontaktowe:
					email_elem = kontakt.find(f'{ns_prefix}Email')
					if email_elem is not None and email_elem.text and email_elem.text.strip():
						emails.append(email_elem.text.strip())
					
					telefon_elem = kontakt.find(f'{ns_prefix}Telefon')
					if telefon_elem is not None and telefon_elem.text and telefon_elem.text.strip():
						phones.append(telefon_elem.text.strip())
				
				# Pierwszy email jako główny
				if emails:
					partner_vals['email'] = emails[0]
					if len(emails) > 1:
						comment = partner_vals.get('comment', '')
						partner_vals['comment'] = f"{comment}\nInne emaile: {', '.join(emails[1:])}" if comment else f"Inne emaile: {', '.join(emails[1:])}"
				
				# Pierwszy telefon jako główny
				if phones:
					partner_vals['phone'] = phones[0]
					if len(phones) > 1:
						comment = partner_vals.get('comment', '')
						partner_vals['comment'] = f"{comment}\nInne telefony: {', '.join(phones[1:])}" if comment else f"Inne telefony: {', '.join(phones[1:])}"
			
			# 8. NrEORI (opcjonalny) - POPRAWIONE testowanie
			nreori_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}NrEORI')
			if nreori_elem is not None and nreori_elem.text and nreori_elem.text.strip():
				partner_vals['ksef_nreori'] = nreori_elem.text.strip()
			
			# 9. PrefiksPodatnika - POPRAWIONE testowanie
			prefiks_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}PrefiksPodatnika')
			if prefiks_elem is not None and prefiks_elem.text and prefiks_elem.text.strip():
				partner_vals['ksef_prefiks'] = prefiks_elem.text.strip()
			
			# 10. StatusInfoPodatnika (opcjonalny)
			status_elem = xml_root.find(f'.//{ns_prefix}{party_type}//{ns_prefix}StatusInfoPodatnika')
			if status_elem is not None:
				# Możesz dodać przetwarzanie statusu jeśli potrzebne
				pass
			
			# 11. Utwórz partnera
			try:
				partner = self.env['res.partner'].create(partner_vals)
				
				# Dodaj informację o źródle w komentarzu
				source_info = f"\n\n--- Import z KSeF ---\nFaktura: {self.ksef_invoice_number}\nData: {fields.Datetime.now()}"
				
				if 'comment' in partner_vals:
					partner.write({'comment': partner_vals['comment'] + source_info})
				else:
					partner.write({'comment': source_info})
				
				_logger.info("✅ Created new partner: %s (NIP: %s, ID: %d)", 
							partner.name, nip, partner.id)
				
				return partner
				
			except Exception as create_error:
				_logger.error("❌ Error creating partner: %s", create_error, exc_info=True)
				# Fallback: utwórz partnera z minimalnymi danymi
				try:
					minimal_partner = self.env['res.partner'].create({
						'name': nazwa,
						'vat': f"PL{nip}",
						'company_type': 'company',
					})
					_logger.warning("⚠️ Created minimal partner due to error: %s", minimal_partner.name)
					return minimal_partner
				except Exception as fallback_error:
					_logger.error("❌ Even fallback failed: %s", fallback_error)
					return None
					
		except Exception as e:
			_logger.error("❌ Error in _create_or_get_partner_from_xml: %s", e, exc_info=True)
			return None


	#####################################################################################
	# Główna metoda odtwarzania faktury przychodzącej
	#####################################################################################
	def action_restore_ksef_invoice(self):
		"""
		Importuje fakturę KSeF z XML do Odoo 18.
		"""
		def _extract_zal_numbers( xml_root, ns):
			ns_uri = ns.get('ns') if ns else None

			if ns_uri:
				nodes = xml_root.findall(
					f'.//{{{ns_uri}}}FakturaZaliczkowa/'
					f'{{{ns_uri}}}NrKSeFFaZaliczkowej'
				)
			else:
				nodes = xml_root.findall(
					'.//FakturaZaliczkowa/NrKSeFFaZaliczkowej'
				)

			return [n.text for n in nodes if n.text]

		for log in self:
			if not log.file_data:
				raise ValidationError(_("Brak pliku XML z fakturą w polu 'file_data'."))
			
			try:
				decoded_data = base64.b64decode(log.file_data)
				xml_root = etree.fromstring(decoded_data)
			except Exception as e:
				raise ValidationError(_("Nieprawidłowy XML: %s") % str(e))
			
			# Pobierz szablon importu
			provider = log.provider_id
			if not provider or not provider.provider_config_id:
				raise ValidationError(_("Brak konfiguracji KSeF dla providera."))
			
			provider_ksef = provider.provider_config_id
			ksef_config = self.env['communication.provider.ksef'].browse(provider_ksef)
			template = ksef_config.import_template_id
			
			if not template:
				raise ValidationError(_("Brak przypisanego szablonu importu (import_template_id)"))
			
			_logger.info("📥 Importing invoice %s with template %s", 
						log.ksef_invoice_number, template.name)
			
			# Sprawdź czy faktura już istnieje (po numerze KSeF)
			existing = self.env['account.move'].search([
				('ksef_number', '=', log.ksef_invoice_number)
			], limit=1)
			
			if existing:
				_logger.info("⚠️ Invoice KSeF %s already exists as %s", 
							log.ksef_invoice_number, existing.id)

				# AKTUALIZUJ COMMUNICATION.LOG
				log.write({
					'document_model': 'account.move',
					'document_id': existing.id,
					'import_move_id': existing.id,
					'state': 'received',
					'ksef_status': 'success',
					'ksef_operation': 'completed',
				})
				return existing
			
			# Przetwórz XML według szablonu
			# na czas rozwoju - do pełnej implementacji w node
			# invoice_values = log._process_import_template(xml_root, template)

			# Sprawdź czy to korekta
			###rodzaj = log._extract_direct_value(xml_root, './/RodzajFaktury')
			rodzaj = log._extract_invoice_type_from_xml(xml_root)
			# WYBIERZ ODPOWIEDNIĄ METODĘ PRZETWARZANIA
			_logger.info("🎯 Invoice type: %s", rodzaj)

			if rodzaj in ['KOR', 'KOR_ZAL', 'KOR_ROZ']:
				# KOREKTY - specjalny parser
				_logger.info("🔄 Using correction parser")
				invoice_values = log._process_ksef_correction_invoice(xml_root, template)
				
				# Upewnij się że metoda rozróżnia typy
				if rodzaj == 'KOR_ZAL' and '_process_kor_zal_correction_lines' not in dir(log):
					_logger.error("❌ KOR_ZAL processing not implemented!")
					
			elif rodzaj == 'ZAL':
				# FAKTURA ZALICZKOWA - standardowy parser z specjalnymi liniami
				_logger.info("💰 Processing advance invoice (ZAL)")
				invoice_values = log._process_import_template(xml_root, template)
				# Metoda _process_import_template powinna wewnętrznie wywołać _process_invoice_lines_zal
				
			else:
				# WSZYSTKIE INNE - standardowy parser
				_logger.info("📄 Using standard template parser")
				invoice_values = log._process_import_template(xml_root, template)
			
			# WALIDACJA I UZUPEŁNIENIE DANYCH
			
			# 1. Dla faktur zakupowych - partner
			if invoice_values.get('move_type') == 'in_invoice':
				if 'partner_id' not in invoice_values:
					# Jedna metoda - jeśli nie znajdzie partnera, tworzy go z pełnymi danymi z XML
					partner = log._create_or_get_partner_from_xml(xml_root)
					if partner:
						invoice_values['partner_id'] = partner.id
						_logger.info("✅ Partner assigned: %s (ID: %d)", partner.name, partner.id)
					else:
						invoice_values['state'] = 'draft'
						_logger.warning("⚠️ Nie można utworzyć partnera - faktura jako draft")

			
			# 2. Dla korekt - sprawdź reversed_entry_id
			if invoice_values.get('move_type') == 'in_refund':
				if 'reversed_entry_id' not in invoice_values:
					invoice_values['state'] = 'draft'
					_logger.warning("⚠️ Korekta bez faktury źródłowej - utworzona jako draft")
			
			# 3. Domyślna firma i journal
			if 'company_id' not in invoice_values:
				invoice_values['company_id'] = self.env.company.id
			
			if 'journal_id' not in invoice_values:
				journal = self.env['account.journal'].search([
					('type', '=', 'purchase'),
					('company_id', '=', self.env.company.id),
				], limit=1)
				if journal:
					invoice_values['journal_id'] = journal.id

			# 4. Obsługa waluty (fail-safe)
			chatter = []
			msg = ""
			try:
				ns = {'ns': xml_root.nsmap.get(None)} if None in xml_root.nsmap else {}
				kod_waluty = xml_root.xpath( "//*[local-name()='KodWaluty']/text()" )

				company_currency = self.env.company.currency_id
				currency = None

				_logger.info( f"\n👉👉👉 kod_waluty = {kod_waluty}  company_currency = {company_currency}")

				if kod_waluty:
					currency = self.env['res.currency'].search([
						('name', 'in', kod_waluty)
					], limit=1)

				if not currency:
					msg = "⚠️ Nie znaleziono waluty %s w systemie – ustawiono %s" % (kod_waluty, company_currency.name)
					_logger.warning( msg)
					chatter.append( msg)
					invoice_values['currency_id'] = company_currency.id
					currency = company_currency
				else:
					invoice_values['currency_id'] = currency.id

					# jeśli waluta obca
					if currency != company_currency:
						kurs_xml = xml_root.xpath( "//*[local-name()='KursWaluty']/text()" )
						if kurs_xml:
							try:
								kurs = float(str(kurs_xml[0]).replace(',', '.'))
								invoice_values['ksef_kurswaluty'] = kurs
								msg = f"💲 Ustawiona waluta {kod_waluty} z kursem {kurs}"
							except Exception:
								msg = f"⚠️ Niepoprawny KursWaluty {kurs_xml} – ustawiono PLN"
								_logger.warning(msg)
								invoice_values['currency_id'] = company_currency.id
						else:
							msg = f"⚠️ Brak KursWaluty dla waluty {currency.name} – ustawiono PLN"
							_logger.warning(msg)
							invoice_values['currency_id'] = company_currency.id
			except Exception as e:
				msg = f"⚠️ Błąd obsługi waluty {str(e)} – ustawiono PLN"
				_logger.warning(msg)
				invoice_values['currency_id'] = self.env.company.currency_id.id
			chatter.append( msg)

			# UTWÓRZ FAKTURĘ
			try:
				_logger.info( f"\n👉👉👉  UTWÓRZ FAKTURĘ {invoice_values}")
				invoice = self.env['account.move'].with_context(
					default_currency_id=currency.id,
					force_price_include=False,
				).create(invoice_values)
				
				_logger.info("✅ Created invoice %s (ID: %d) from KSeF %s", 
							invoice.name, invoice.id, log.ksef_invoice_number)

				if chatter != []:
					invoice.message_post(
						body=Markup("<br/>".join(chatter))
					)

				# post-process dla ROZ
				if invoice:
					chatter = []
					zal_numbers = _extract_zal_numbers(xml_root, ns)
					invoice._link_imported_zal(zal_numbers)
					chatter.append( f"🧩 Przekazono informacje o fakturach zaliczkach:")
					for zal_number in zal_numbers:
						chatter.append( f"👉 <b>{zal_number}</b>")
					invoice.message_post(body=Markup("<br/>".join(chatter)))
				
				# Dla korekt - automatyczne powiązanie linii
				if invoice.move_type == 'in_refund' and invoice.reversed_entry_id:
					log._auto_match_refund_lines(invoice, invoice.reversed_entry_id)
				
				#_logger.info(f"#👉 ZAPISZ XML JAKO ZAŁĄCZNIK KSeF_{log.ksef_invoice_number}.xml log.ksef_status = {log.ksef_status}")
				attachment = self.env['ir.attachment'].create({
					'name': f"KSeF_{log.ksef_invoice_number}.xml",
					'res_model': 'account.move',
					'res_id': invoice.id,
					'type': 'binary',
					'mimetype': 'application/xml',
					'datas': log.file_data,
					'description': f"Faktura KSeF {log.ksef_invoice_number} zaimportowana {fields.Datetime.now()}",
				})
				
				#_logger.info(f"#👉 # AKTUALIZUJ COMMUNICATION.LOG attachment = {attachment} log.ksef_status = {log.ksef_status}")
				log.write({
					'document_model': 'account.move',
					'document_id': invoice.id,
					'import_move_id': invoice.id,
					'state': 'received',
					'ksef_status': 'success',
					'ksef_operation': 'completed',
					'file_name': f"KSeF_{log.ksef_invoice_number}.xml",
				})

				invoice.ksef_process_state = 'imported'
				invoice._compute_ksef_ui_state()

				_logger.info(f"\n👉 ## ZAPISANA invoice {invoice}\nlog.ksef_status = {log.ksef_status}\ninvoice.ksef_process_state = {invoice.ksef_process_state}")
				return invoice
				
			except Exception as e:
				_logger.error("❌ Error creating invoice: %s", e, exc_info=True)
				raise ValidationError(_("Błąd tworzenia faktury: %s") % str(e))

	# =========================================================================
	# PRZETWARZANIE XML ZGODNIE Z SZABLONEM
	# =========================================================================

	def _process_import_template(self, xml_root, template):
		"""
		Przetwarza XML faktury KSeF według szablonu importu.
		"""
		_logger.info("📥 Start processing XML with template ID: %s", template.id)
		
		values = {}
		
		# 1. ROZPOZNAJ TYP FAKTURY (nowa metoda!)
		rodzaj = self._extract_invoice_type_from_xml(xml_root)
		type_info = self.map_invoice_type(rodzaj, xml_root)
		
		# Ustaw podstawowe pola
		values['move_type'] = type_info['move_type']
		
		# 2. DODAJ SPECJALNE POLA Z type_info
		for key, value in type_info['special_fields'].items():
			if value:
				values[key] = value
		
		# 3. DLA KOREKT - SPRAWDŹ reversed_entry_id
		if (type_info['special_fields'].get('requires_reversed_entry') and 
			'reversed_entry_id' not in values):
			_logger.warning("⚠️ Korekta bez reversed_entry_id - wymaga ręcznego powiązania")
			values['state'] = 'draft'
		
		# 4. NUMER KSeF (zawsze)
		if self.ksef_invoice_number:
			values['ksef_number'] = self.ksef_invoice_number
		
		# 5. DLA FAKTUR UPROSZCZONYCH (UPR) - stan = draft
		if rodzaj == 'UPR':
			values['state'] = 'draft'
		
		# 6. PRZETWÓRZ POZOSTAŁE POLA Z SZABLONU
		p2_value = None
		ns_uri = xml_root.nsmap.get(None)
		ns = {'ns': ns_uri} if ns_uri else {}
		if ns_uri:
			p2_elem = xml_root.find(f'.//{{{ns_uri}}}P_2')
		else:
			p2_elem = xml_root.find('.//P_2')
		
		if p2_elem is not None and p2_elem.text:
			p2_value = p2_elem.text.strip()
			values['ref'] = p2_value
			values['invoice_origin'] = p2_value
			_logger.info("✅ Direct ref extraction: %s", p2_value)

		
		# Podział node'ów na nagłówek i wiersze
		header_nodes = []
		line_field_nodes = []
		
		for node in template.node_ids:
			if node.src_rel_path and 'invoice_line_ids' in node.src_rel_path:
				line_field_nodes.append(node)
			else:
				header_nodes.append(node)
		
		# Pola już przetworzone (pomijamy)
		skip_fields = {'move_type', 'ksef_number', 'state', 'ref'}
		
		# Przetwarzanie nagłówka
		for node in header_nodes:
			if not node.src_rel_path or node.src_rel_path in skip_fields:
				continue

			value = self._extract_value_from_xml_node(xml_root, node, ns)
			if value is not None:
				# Specjalna obsługa dla partner_id
				if node.src_rel_path == 'partner_id':
					partner = self._find_partner_by_nip(value)
					if partner:
						values['partner_id'] = partner.id
				
				# Specjalna obsługa dla dat
				elif node.src_rel_path.endswith('_date'):
					date_value = self._parse_date(value)
					if date_value:
						values[node.src_rel_path] = date_value
				
				# Normalne pole
				else:
					values[node.src_rel_path] = value
		
		# 7. PRZETWÓRZ WIERSZE FAKTURY (nowa metoda dla FaWiersz!)
		lines_values = []
		
		if rodzaj in ['ZAL', 'KOR_ZAL']:
			# Faktury zaliczkowe - ZamowienieWiersz
			lines_values = self._process_invoice_lines_zal(xml_root, line_field_nodes, ns)
		else:
			# Pozostałe typy - FaWiersz
			lines_values = self._process_invoice_lines_fawiersz(xml_root, line_field_nodes, ns)

		if lines_values:
			values['invoice_line_ids'] = lines_values
			_logger.info("✅ Added %d invoice lines", len(lines_values))
		
		# 8. DODAJ POLA SPECJALNE Z FAKTURY
		self._add_invoice_specific_fields(values, xml_root, rodzaj)
		values['ksef_rodzaj_faktury'] = rodzaj
		
		# 9. WALIDACJA DLA KOREKT
		if rodzaj in ['KOR', 'KOR_ZAL', 'KOR_ROZ']:
			if 'reversed_entry_id' not in values:
				values['state'] = 'draft'
				_logger.warning("⚠️ Korekta bez reversed_entry_id - utworzona jako draft")
			
			if 'reversed_entry_id' in values and values['reversed_entry_id']:
				corrected_invoice = self.env['account.move'].browse(values['reversed_entry_id'])
				if corrected_invoice and 'date' in values:
					corr_date = fields.Date.from_string(values['date'])
					orig_date = corrected_invoice.invoice_date or corrected_invoice.date
					if orig_date and corr_date < orig_date:
						_logger.warning("⚠️ Data korekty wcześniejsza niż data faktury korygowanej")
		
		_logger.info("✅ Processed invoice %s: move_type=%s, %d fields, %d lines", 
					 rodzaj, values.get('move_type'), len(values), len(lines_values) if 'invoice_line_ids' in values else 0)
		
		return values

	# =========================================================================
	# NOWE METODY DLA STRUKTURY FAWIERSZ
	# =========================================================================
	def _extract_invoice_type_from_xml(self, xml_root):
		"""
		Wyciąga rodzaj faktury z RodzajFaktury (nowa struktura KSeF FA(3)).
		"""
		# Namespace
		ns_uri = xml_root.nsmap.get(None)
		
		# 1. Spróbuj z RodzajFaktury
		rodzaj_elem = None
		if ns_uri:
			rodzaj_elem = xml_root.find(f'.//{{{ns_uri}}}RodzajFaktury')
		if rodzaj_elem is None:
			rodzaj_elem = xml_root.find('.//RodzajFaktury')
		
		if rodzaj_elem is not None and rodzaj_elem.text:
			rodzaj = rodzaj_elem.text.strip().upper()
			_logger.info("📋 Found RodzajFaktury: %s", rodzaj)
			return rodzaj
		
		# 2. Fallback: stare pola
		_logger.warning("⚠️ RodzajFaktury not found, using fallback detection")
		
		# Helper do znajdowania z namespace
		def find_with_ns(xpath_name):
			if ns_uri:
				elem = xml_root.find(f'.//{{{ns_uri}}}{xpath_name}')
				if elem is None:
					elem = xml_root.find(f'.//{xpath_name}')
				return elem
			return xml_root.find(f'.//{xpath_name}')
		
		p17 = find_with_ns('P_17')  # Czy korygująca?
		if p17 is not None and p17.text and p17.text.strip() == '1':
			p18a = find_with_ns('P_18A')  # Czy rozliczeniowa?
			if p18a is not None and p18a.text and p18a.text.strip() == '1':
				return 'KOR_ROZ'
			
			p16 = find_with_ns('P_16')  # Czy zaliczkowa?
			if p16 is not None and p16.text and p16.text.strip() == '1':
				return 'KOR_ZAL'
			
			return 'KOR'
		
		p16 = find_with_ns('P_16')
		if p16 is not None and p16.text and p16.text.strip() == '1':
			return 'ZAL'
		
		p18a = find_with_ns('P_18A')
		if p18a is not None and p18a.text and p18a.text.strip() == '1':
			return 'ROZ'
		
		return 'VAT'

	# XXX
	def _process_invoice_lines_fawiersz(self, xml_root, line_nodes, ns):
		"""
		Przetwarza wiersze faktury z FaWiersz (KSeF FA(3)).

		Returns:
			list: [(0, 0, line_vals), ...] dla invoice_line_ids
		"""
		def _to_float(val):
			if not val:
				return None
			try:
				return float(val.replace(',', '.'))
			except Exception:
				return None

		lines_values = []
		ns_uri = ns.get('ns') if ns else None

		# 1. Znajdź WSZYSTKIE FaWiersz
		if ns_uri:
			line_containers = xml_root.findall(f'.//{{{ns_uri}}}FaWiersz')
		else:
			line_containers = xml_root.findall('.//FaWiersz')

		# 2. Fallback: stara struktura Pozycje/P_2A
		if not line_containers:
			if ns_uri:
				line_containers = xml_root.findall(
					f'.//{{{ns_uri}}}Pozycje/{{{ns_uri}}}P_2A'
				)
			else:
				line_containers = xml_root.findall('.//Pozycje/P_2A')

		_logger.info("📄 Found %d invoice lines (FaWiersz)", len(line_containers))

		# 3. Przetwarzanie wierszy
		for line_index, line_container in enumerate(line_containers):
			line_vals = {
				'sequence': (line_index + 1) * 10,
				'discount': 0.0,  # ZAWSZE 0 – FA(3) nie mapuje discount%
			}

			# --- pobranie wartości XML ---
			p7 = self._get_xml_value(line_container, 'P_7', ns)	 # opis
			p8a = self._get_xml_value(line_container, 'P_8A', ns)   # jednostka miary
			p9a = self._get_xml_value(line_container, 'P_9A', ns)   # cena jedn. netto
			p10 = self._get_xml_value(line_container, 'P_10', ns)   # ilość
			p11 = self._get_xml_value(line_container, 'P_11', ns)   # wartość netto
			p12 = self._get_xml_value(line_container, 'P_12', ns)   # stawka VAT

			# --- konwersje ---
			qty = _to_float(p10)
			unit_price = _to_float(p9a)
			net_value = _to_float(p11)

			# --- nazwa pozycji ---
			line_vals['name'] = p7 or f"Pozycja {line_index + 1}"

			# --- klasyfikacja jednostki ---
			uom_type = self.UN_CEFACT_UOM.get(p8a, "quantity")

			# ==========================================================
			# JEDYNA REGUŁA SEMANTYCZNA FA(3)
			# ==========================================================

			# 1) Rabat / korekta kwotowa
			if net_value is not None and net_value < 0:
				line_vals['quantity'] = 1.0
				line_vals['price_unit'] = net_value

			# 2) Jednostka procentowa (P1) – NIE discount, tylko linia kwotowa
			elif uom_type == "percent":
				line_vals['quantity'] = 1.0
				line_vals['price_unit'] = net_value or 0.0

			# 3) Standardowa pozycja
			else:
				line_vals['quantity'] = qty if qty not in (None, 0) else 1.0
				line_vals['price_unit'] = unit_price or 0.0

			# --- PODATEK ---
			if p12:
				tax_ids = self._find_tax_ids_by_name(p12)
				if tax_ids:
					line_vals['tax_ids'] = [(6, 0, tax_ids)]
				else:
					_logger.warning("⚠️ Tax not found for value: %s", p12)

			# --- Jednostka miary (jeśli istnieje w Odoo) ---
			if p8a:
				uom = self._find_uom_by_name(p8a)
				if uom:
					line_vals['product_uom_id'] = uom.id

			# --- Numer wiersza (jeśli obecny w XML) ---
			nr_wiersza = self._get_xml_value(line_container, 'NrWierszaFa', ns)
			if nr_wiersza:
				try:
					line_vals['sequence'] = int(nr_wiersza) * 10
				except Exception:
					pass

			lines_values.append((0, 0, line_vals))

			_logger.debug(
				"✅ Line %d: %s | qty=%s | price=%s",
				line_index + 1,
				line_vals['name'][:40],
				line_vals['quantity'],
				line_vals['price_unit'],
			)

		return lines_values


	def XXX_process_invoice_lines_fawiersz(self, xml_root, line_nodes, ns):
		"""
		Przetwarza wiersze faktury z FaWiersz (nowa struktura KSeF).
		
		Returns:
			list: [(0, 0, line_vals), ...] dla invoice_line_ids
		"""
		lines_values = []
		ns_uri = ns.get('ns') if ns else None
		
		# 1. Znajdź WSZYSTKIE FaWiersz
		if ns_uri:
			line_containers = xml_root.findall(f'.//{{{ns_uri}}}FaWiersz')
		else:
			line_containers = xml_root.findall('.//FaWiersz')
		
		# 2. Fallback: stara struktura Pozycje/P_2A
		if not line_containers:
			if ns_uri:
				line_containers = xml_root.findall(f'.//{{{ns_uri}}}Pozycje/{{{ns_uri}}}P_2A')
			else:
				line_containers = xml_root.findall('.//Pozycje/P_2A')
		
		_logger.info("📄 Found %d invoice lines (FaWiersz)", len(line_containers))
		
		# 3. Przetwórz każdy wiersz
		for line_index, line_container in enumerate(line_containers):
			line_vals = {'sequence': (line_index + 1) * 10}
			
			# Pobierz kluczowe wartości bezpośrednio (szybsze i pewniejsze)
			p7 = self._get_xml_value(line_container, 'P_7', ns)	 # Nazwa
			p8a = self._get_xml_value(line_container, 'P_8A', ns)   # Jednostka
			p8b = self._get_xml_value(line_container, 'P_8B', ns)   # Ilość
			p9a = self._get_xml_value(line_container, 'P_9A', ns)   # Cena jednostkowa
			p10 = self._get_xml_value(line_container, 'P_10', ns)   # Rabat
			p11 = self._get_xml_value(line_container, 'P_11', ns)   # Wartość netto
			p12 = self._get_xml_value(line_container, 'P_12', ns)   # Podatek
			
			# 4. Nazwa (wymagane)
			if p7:
				line_vals['name'] = p7
			else:
				line_vals['name'] = f"Pozycja {line_index + 1}"
			
			# 5. Ilość (wymagane)
			if p8b:
				try:
					line_vals['quantity'] = float(p8b.replace(',', '.'))
				except:
					line_vals['quantity'] = 1.0
			else:
				line_vals['quantity'] = 1.0
			
			# 6. CENA JEDNOSTKOWA (KLUCZOWE!) - preferuj P_9A, jeśli nie ma, oblicz z P_11
			price_unit_set = False
			if p9a:
				try:
					line_vals['price_unit'] = float(p9a.replace(',', '.'))
					price_unit_set = True
				except:
					pass
			
			if not price_unit_set and p11 and p8b:
				try:
					netto = float(p11.replace(',', '.'))
					ilosc = float(p8b.replace(',', '.'))
					if ilosc != 0:
						line_vals['price_unit'] = netto / ilosc
						price_unit_set = True
				except:
					pass
			
			if not price_unit_set:
				line_vals['price_unit'] = 0.0
			
			# 7. Rabat
			if p10:
				try:
					line_vals['discount'] = float(p10.replace(',', '.'))
				except:
					pass
			
			# 8. PODATEK (NAJWAŻNIEJSZE!)
			if p12:
				tax_ids = self._find_tax_ids_by_name(p12)
				if tax_ids:
					line_vals['tax_ids'] = [(6, 0, tax_ids)]
				else:
					_logger.warning("⚠️ Tax not found for value: %s", p12)
			
			# 9. Jednostka miary
			if p8a:
				uom = self._find_uom_by_name(p8a)
				if uom:
					line_vals['product_uom_id'] = uom.id
			
			# 10. Numer wiersza (jeśli jest w XML)
			nr_wiersza = self._get_xml_value(line_container, 'NrWierszaFa', ns)
			if nr_wiersza:
				try:
					line_vals['sequence'] = int(nr_wiersza) * 10
				except:
					pass
			
			# 11. Dodaj wiersz (zawsze, nawet jeśli puste wartości)
			lines_values.append((0, 0, line_vals))
			
			_logger.debug("✅ Line %d: %s, qty: %s, price: %s", 
						 line_index + 1, 
						 line_vals.get('name', 'No name')[:30],
						 line_vals.get('quantity'),
						 line_vals.get('price_unit'))
		
		return lines_values

	def _get_xml_value(self, container, field_name, ns):
		"""
		Pomocnicza: pobiera wartość tekstową z elementu XML.
		"""
		ns_uri = ns.get('ns') if ns else None
		
		try:
			if ns_uri:
				# Najpierw bezpośrednie dziecko
				element = container.find(f'{{{ns_uri}}}{field_name}')
				if element is None:
					# Potem w poddrzewie
					element = container.find(f'.//{{{ns_uri}}}{field_name}')
			else:
				element = container.find(field_name)
				if element is None:
					element = container.find(f'.//{field_name}')
			
			if element is not None and element.text:
				return element.text.strip()
				
		except Exception as e:
			_logger.debug("Error getting XML value %s: %s", field_name, e)
		
		return None

	def _find_uom_by_name(self, uom_name):
		"""
		Znajduje jednostkę miary po nazwie.
		"""
		if not uom_name:
			return None
		
		# Popularne mapowania PL → EN
		uom_mapping = {
			'szt': 'Units',
			'szt.': 'Units',
			'sztuka': 'Units',
			'kpl': 'Units',
			'usł': 'Units',
			'usługa': 'Units',
			'm2': 'Square Meter',
			'm²': 'Square Meter',
			'm3': 'Cubic Meter',
			'm³': 'Cubic Meter',
			'kg': 'kg',
			't': 'Ton',
			'l': 'Liter',
			'h': 'Hour',
			'godz': 'Hour',
			'godz.': 'Hour',
			'dzień': 'Day',
			'dni': 'Day',
			'mb': 'Meter',
			'm': 'Meter',
			'km': 'km',
		}
		
		# 1. Szukaj dokładnie
		uom = self.env['uom.uom'].search([
			('name', '=', uom_name),
		], limit=1)
		
		# 2. Szukaj przez mapowanie
		if not uom and uom_name.lower() in uom_mapping:
			mapped_name = uom_mapping[uom_name.lower()]
			uom = self.env['uom.uom'].search([
				('name', 'ilike', mapped_name),
			], limit=1)
		
		# 3. Szukaj podobnie
		if not uom:
			uom = self.env['uom.uom'].search([
				('name', 'ilike', uom_name),
			], limit=1)
		
		if not uom:
			_logger.debug("⚠️ UoM not found: %s", uom_name)
		
		return uom

	# =========================================================================
	# MAPOWANIE TYPÓW FAKTUR (ZAKTUALIZOWANE)
	# =========================================================================

	def map_invoice_type(self, rodzaj, xml_root=None):
		"""
		Mapuje rodzaj faktury KSeF na typ Odoo - ROZSZERZONA WERSJA.
		"""
		# Normalizacja
		rodzaj_norm = rodzaj.strip().upper() if rodzaj else 'VAT'
		
		# ROZSZERZONE mappingi dla wszystkich typów KSeF
		mapping = {
			# Standardowe typy FA(3)
			"VAT": {
				'move_type': 'in_invoice',
				'name_field': 'ref',
				'is_refund': False,
			},
			"ZAL": {
				'move_type': 'in_invoice',
				'name_field': 'ref',
				'is_refund': False,
				'is_advance': True,
			},
			"ROZ": {
				'move_type': 'in_invoice',
				'name_field': 'ref',
				'is_refund': False,
				'is_settlement': True,
			},
			"UPR": {
				'move_type': 'in_invoice',
				'name_field': 'ref',
				'is_refund': False,
				'is_upr': True,
			},
			"KOR": {
				'move_type': 'in_refund',
				'name_field': 'name',
				'is_refund': True,
				'correction_type': 'standard',
				'requires_reversed_entry': True,
			},
			"KOR_ZAL": {
				'move_type': 'in_refund',
				'name_field': 'name',
				'is_refund': True,
				'is_advance': True,
				'correction_type': 'advance',
				'requires_reversed_entry': True,
			},
			"KOR_ROZ": {
				'move_type': 'in_refund',
				'name_field': 'name',
				'is_refund': True,
				'is_settlement': True,
				'correction_type': 'settlement',
				'requires_reversed_entry': True,
			},
			
			# Dodatkowe typy (dla kompletności)
			"EE": {
				'move_type': 'in_invoice',
				'name_field': 'ref',
				'is_refund': False,
			},
			"PRO_FORMA": {
				'move_type': 'in_invoice',
				'name_field': 'ref',
				'is_refund': False,
			},
			"VAT_MARZA": {
				'move_type': 'in_invoice',
				'name_field': 'ref',
				'is_refund': False,
			},
		}
		
		base_info = mapping.get(rodzaj_norm, mapping["VAT"])  # Domyślnie VAT
		
		result = {
			'move_type': base_info['move_type'],
			'name_field': base_info['name_field'],
			'special_fields': {
				'ksef_is_advance': base_info.get('is_advance', False),
				'ksef_is_settlement': base_info.get('is_settlement', False),
				'ksef_is_upr': base_info.get('is_upr', False),
				'ksef_correction_type': base_info.get('correction_type', False),
				'requires_reversed_entry': base_info.get('requires_reversed_entry', False),
			}
		}
		
		if xml_root is not None:
			result['special_fields'].update(
				self._extract_invoice_special_fields(xml_root, rodzaj_norm)
			)
		
		_logger.info("🗺️ Mapped invoice type %s → %s", rodzaj_norm, result['move_type'])
		return result

	def _extract_invoice_special_fields(self, xml_root, rodzaj):
		"""
		Wyciąga specjalne pola faktury z XML.
		"""
		fields = {}
		
		# 1. Numer faktury korygowanej (dla KOR)
		if rodzaj in ['KOR', 'KOR_ZAL', 'KOR_ROZ']:
			corrected_number = self._extract_value_by_path(xml_root, './/NrKSeFFaKorygowanej')
			if corrected_number:
				corrected_invoice = self.env['account.move'].search([
					'|',
					('ref', '=', corrected_number),
					('ksef_number', '=', corrected_number),
					('move_type', '=', 'in_invoice'),
					('company_id', '=', self.env.company.id),
				], limit=1)
				
				if corrected_invoice:
					fields['reversed_entry_id'] = corrected_invoice.id
				else:
					fields['ksef_corrected_ref'] = corrected_number
		
		# 2. Data wystawienia
		invoice_date = self._extract_value_by_path(xml_root, './/P_1')
		if invoice_date:
			date_value = self._parse_date(invoice_date)
			if date_value:
				fields['invoice_date'] = date_value
		
		# 3. Data sprzedaży/dostawy
		sale_date = self._extract_value_by_path(xml_root, './/P_6')
		if sale_date:
			date_value = self._parse_date(sale_date)
			if date_value:
				fields['date'] = date_value
		
		# 4. Dodatkowe flagi
		fields.update(self._check_additional_flags(xml_root))
		
		return fields

	# =========================================================================
	# METODY POMOCNICZE (istniejące - zaktualizowane)
	# =========================================================================

	def _extract_value_from_xml_node(self, xml_root, node, ns):
		"""
		Wyciąga wartość z XML na podstawie node'a szablonu.
		"""
		if not node.xpath or not node.name:
			return None
			
		try:
			containers = xml_root.xpath(node.xpath, namespaces=ns)
			if not containers:
				return None
				
			container = containers[0]
			
			element = None
			if ns.get('ns'):
				element = container.find(f"{{{ns['ns']}}}{node.name}")
			else:
				element = container.find(node.name)
				
			if element is not None and element.text:
				return element.text.strip()
				
		except Exception as e:
			_logger.debug("Error extracting value for node %s: %s", node.name, e)
		
		return None

	def _extract_value_by_path(self, xml_root, xpath):
		"""
		Pobiera wartość tekstową po XPath.
		"""
		try:
			elem = xml_root.find(xpath)
			if elem is None:
				# Spróbuj z namespace
				ns_uri = xml_root.nsmap.get(None)
				if ns_uri:
					elem = xml_root.find(f'.//{{{ns_uri}}}{xpath.split("//")[-1]}')
			
			if elem is not None and elem.text:
				return elem.text.strip()
		except:
			pass
		return None

	def _parse_date(self, date_str):
		"""
		Parsuje datę z różnych formatów.
		"""
		if not date_str:
			return None
		
		date_str = date_str.split('T')[0]  # Usuń czas
		
		formats = [
			'%Y-%m-%d',	# 2024-01-15
			'%d.%m.%Y',	# 15.01.2024
			'%d/%m/%Y',	# 15/01/2024
			'%Y%m%d',	  # 20240115
		]
		
		for fmt in formats:
			try:
				return datetime.strptime(date_str, fmt).date().isoformat()
			except:
				continue
		
		return date_str

	def _add_invoice_specific_fields(self, values, xml_root, rodzaj):
		"""
		Dodaje specyficzne pola dla różnych typów faktur.
		"""
		# Dla faktur rozliczeniowych - data dostawy
		if rodzaj in ['ROZ', 'KOR_ROZ']:
			delivery_date = self._extract_value_by_path(xml_root, './/P_6')
			if delivery_date:
				values['ksef_delivery_date'] = self._parse_date(delivery_date)
		
		# Dla faktur zaliczkowych - wartość zamówienia
		if rodzaj in ['ZAL', 'KOR_ZAL']:
			# 1. # order_value = self._extract_value_by_path(xml_root, './/P_13_1')
			order_value = self._extract_value_by_path(xml_root, './/WartoscZamowienia')
			if order_value:
				try:
					values['ksef_order_value'] = float(order_value.replace(',', '.'))
				except:
					pass

			# 2. Fallback: P_13_1 (jeśli nie ma WartoscZamowienia)
			if 'ksef_order_value' not in values or not values['ksef_order_value']:
				order_value = self._extract_value_by_path(xml_root, './/P_13_1')
				if order_value:
					try:
						values['ksef_order_value'] = float(order_value.replace(',', '.'))
					except:
						pass
		
		# Dla faktur rozliczeniowych - numery faktur zaliczkowych
		if rodzaj in ['ROZ', 'KOR_ROZ']:
			advance_refs = self._extract_advance_references(xml_root)
			if advance_refs:
				values['ksef_advance_refs'] = ','.join(advance_refs)

	def _extract_advance_references(self, xml_root):
		"""
		Wyciąga numery faktur zaliczkowych dla faktur rozliczeniowych.
		"""
		refs = []
		
		try:
			advances_elem = xml_root.find('.//P_6A')
			if advances_elem is not None and advances_elem.text:
				text = advances_elem.text.strip()
				for separator in [',', ';', '|', '/']:
					if separator in text:
						refs.extend([ref.strip() for ref in text.split(separator) if ref.strip()])
						break
				else:
					refs.append(text)
		except:
			pass
		
		return refs

	def _check_additional_flags(self, xml_root):
		"""
		Sprawdza dodatkowe flagi z XML.
		"""
		flags = {}
		
		# Helper do znajdowania
		def find_flag(flag_name):
			elem = xml_root.find(f'.//{flag_name}')
			if elem is None:
				ns_uri = xml_root.nsmap.get(None)
				if ns_uri:
					elem = xml_root.find(f'.//{{{ns_uri}}}{flag_name}')
			return elem
		
		# P_16: Czy faktura zaliczkowa?
		p16 = find_flag('P_16')
		if p16 is not None and p16.text:
			flags['ksef_p16'] = p16.text.strip()
			if p16.text.strip() == '1':
				flags['ksef_is_advance'] = True
		
		# P_17: Czy faktura korygująca?
		p17 = find_flag('P_17')
		if p17 is not None and p17.text:
			flags['ksef_p17'] = p17.text.strip()
		
		# P_18A: Czy faktura rozliczeniowa?
		p18a = find_flag('P_18A')
		if p18a is not None and p18a.text:
			flags['ksef_p18a'] = p18a.text.strip()
			if p18a.text.strip() == '1':
				flags['ksef_is_settlement'] = True
		
		# P_19N: Czy podatek nie podlega odliczeniu?
		p19n = find_flag('P_19N')
		if p19n is not None and p19n.text:
			#p19n = '2' if p19n == '2' else '1'
			flags['ksef_p19n'] = p19n.text.strip() 
		
		# P_22N: Czy nie podlega opodatkowaniu?
		p22n = find_flag('P_22N')
		if p22n is not None and p22n.text:
			#p22n = '2' if p22n == '2' else '1'
			flags['ksef_p22n'] = p22n.text.strip()
		
		# P_23: Czy marża?
		p23 = find_flag('P_23')
		if p23 is not None and p23.text:
			flags['ksef_p23'] = p23.text.strip()
			if p23.text.strip() == '1':
				flags['ksef_pmarzyn'] = True
		
		return flags

	# =========================================================================
	# ZNAJDOWANIE REKORDÓW W ODOO
	# =========================================================================

	def _find_tax_ids_by_name(self, tax_name):
		"""
		Znajduje ID podatku po nazwie/stawce z XML.
		"""
		if not tax_name:
			return []
		
		# 1. Próba parsowania jako liczba (stawka procentowa)
		try:
			tax_rate = float(tax_name.replace(',', '.'))
			
			tax = self.env['account.tax'].search([
				('amount', '=', tax_rate),
				('type_tax_use', 'in', ['purchase', 'all']),
				('company_id', '=', self.env.company.id),
				('active', '=', True),
			], limit=1)
			
			if tax:
				return [tax.id]
		except (ValueError, TypeError):
			pass
		
		# 2. Szukaj po nazwie
		search_terms = [
			tax_name,
			f"{tax_name}%",
			tax_name.upper(),
			tax_name.lower(),
		]
		
		for term in search_terms:
			tax = self.env['account.tax'].search([
				('name', 'ilike', term),
				('type_tax_use', 'in', ['purchase', 'all']),
				('company_id', '=', self.env.company.id),
				('active', '=', True),
			], limit=1)
			
			if tax:
				return [tax.id]
		
		# 3. Mapowanie specjalnych przypadków
		special_mapping = {
			'zw': ['zw.', 'zwolniony', 'zwolnione'],
			'np': ['nie podl.', 'nie podlega', 'np'],
			'oo': ['odwrotne obciążenie', 'oo'],
			'0': ['0%', '0'],
			'0 kr': ['0% kr', '0 kr'],
			'0 wdt': ['0% wdt', '0 wdt'],
			'0 ex': ['0% ex', '0 ex'],
		}
		
		for xml_key, odoo_names in special_mapping.items():
			if xml_key in tax_name.lower():
				for odoo_name in odoo_names:
					tax = self.env['account.tax'].search([
						('name', 'ilike', odoo_name),
						('type_tax_use', 'in', ['purchase', 'all']),
						('company_id', '=', self.env.company.id),
						('active', '=', True),
					], limit=1)
					
					if tax:
						return [tax.id]
		
		_logger.warning("⚠️ Tax not found for XML value: %s", tax_name)
		return []

	def _find_partner_by_nip(self, nip):
		"""
		Znajduje partnera po NIP.
		"""
		if not nip or len(nip) < 10:
			return None
		
		clean_nip = nip.replace('PL', '').replace('-', '').replace(' ', '').strip()
		
		partner = self.env['res.partner'].search([
			'|',
			('vat', 'ilike', f'%{clean_nip}%'),
			('vat', 'ilike', f'%PL{clean_nip}%'),
		], limit=1)
		
		return partner

	# =========================================================================
	# METODY DLA KOREKT (opcjonalne)
	# =========================================================================

	def _auto_match_refund_lines(self, refund_invoice, original_invoice):
		"""
		Automatyczne powiązanie linii korekty z oryginalną fakturą.
		"""
		try:
			for refund_line in refund_invoice.invoice_line_ids:
				for original_line in original_invoice.invoice_line_ids:
					if (refund_line.product_id == original_line.product_id and
						refund_line.name == original_line.name):
						
						if hasattr(refund_line, 'reversed_entry_line_id'):
							refund_line.reversed_entry_line_id = original_line.id
						break
						
			_logger.info("✅ Auto-matched lines for refund %s", refund_invoice.name)
			
		except Exception as e:
			_logger.warning("⚠️ Error auto-matching refund lines: %s", e)

#################################################################################
#EoF

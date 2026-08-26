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
   @date   2026-08-25

   Wzbogacenie wierszy faktury KSeF (FaWiersz) o dodatkowe elementy nieobsługiwane
   dotąd przez główną logikę importu w communication_provider_ksef_addons.py:
   UU_ID, Indeks, GTIN, CN, PKWiU, GTU, KursWaluty - oraz uzupełnienie
   surowych pól ksef_p_* zdefiniowanych na account.move.line (dotąd puste).

   UWAGA - ZAKRES:
   Dotyczy WYŁĄCZNIE wierszy typu <FaWiersz> (ścieżki: VAT, ROZ, UPR, EE,
   PRO_FORMA, VAT_MARZA - przez _process_invoice_lines_fawiersz; oraz
   KOR, KOR_ROZ - przez _create_correction_line_from_element).

   Faktury zaliczkowe (ZAL, KOR_ZAL - węzeł <ZamowienieWiersz>) NIE są tu
   obsługiwane - brak próbki faktury zaliczkowej do weryfikacji, czy i pod
   jakimi nazwami występują w niej te same elementy. Do zrobienia later.

   Metoda _enrich_line_vals_ksef_extra jest wołana z dwóch miejsc
   w communication_provider_ksef_addons.py, tuż przed dodaniem wiersza
   do listy (0, 0, line_vals):
	 - _process_invoice_lines_fawiersz
	 - _create_correction_line_from_element
"""
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class CommunicationLogKsefLineImport(models.Model):
	_inherit = "communication.log"

	def _enrich_line_vals_ksef_extra(self, line_vals, line_container, ns=None):
		"""
		Uzupełnia line_vals o dodatkowe pola KSeF odczytane z pojedynczego
		elementu <FaWiersz>. Modyfikuje przekazany słownik w miejscu (in place)
		i dodatkowo go zwraca dla wygody wywołania.

		Hardkodowany xpath przez local-name() (self._get_xml_value) - bez
		fallbacku do szablonu XET (świadomie odłożone na później, patrz notatka
		w ARCHITECTURE.md / ustalenia w rozmowie).

		Args:
			line_vals (dict): wartości wiersza budowane przez metodę wywołującą.
			line_container: element lxml odpowiadający <FaWiersz>.
			ns: ignorowany, zachowany dla spójności sygnatur z resztą modułu.

		Returns:
			dict: ten sam obiekt line_vals, zmodyfikowany.
		"""

		def _to_float(val):
			if not val:
				return None
			try:
				return float(val.replace(",", "."))
			except (ValueError, TypeError):
				return None

		# --- Pola już zdefiniowane na account.move.line, dotąd niewypełniane ---
		p7 = self._get_xml_value(line_container, "P_7", ns)
		if p7:
			line_vals["ksef_p_7"] = p7

		p8a = self._get_xml_value(line_container, "P_8A", ns)
		if p8a:
			line_vals["ksef_p_8a"] = p8a

		p8b = _to_float(self._get_xml_value(line_container, "P_8B", ns))
		if p8b is not None:
			line_vals["ksef_p_8b"] = p8b

		p9a = _to_float(self._get_xml_value(line_container, "P_9A", ns))
		if p9a is not None:
			line_vals["ksef_p_9a"] = p9a

		p11 = _to_float(self._get_xml_value(line_container, "P_11", ns))
		if p11 is not None:
			line_vals["ksef_p_11"] = p11

		p12 = _to_float(self._get_xml_value(line_container, "P_12", ns))
		if p12 is not None:
			line_vals["ksef_p_12"] = p12

		nr_wiersza = self._get_xml_value(line_container, "NrWierszaFa", ns)
		if nr_wiersza:
			line_vals["ksef_nr_wiersza_fa"] = nr_wiersza

		# --- Nowe elementy, dotąd całkowicie nieobsługiwane ---
		uu_id = self._get_xml_value(line_container, "UU_ID", ns)
		if uu_id:
			line_vals["ksef_uu_id"] = uu_id

		indeks = self._get_xml_value(line_container, "Indeks", ns)
		if indeks:
			line_vals["ksef_indeks"] = indeks

		gtin = self._get_xml_value(line_container, "GTIN", ns)
		if gtin:
			line_vals["ksef_gtin"] = gtin

		cn = self._get_xml_value(line_container, "CN", ns)
		if cn:
			line_vals["ksef_cn"] = cn

		pkwiu = self._get_xml_value(line_container, "PKWiU", ns)
		if pkwiu:
			line_vals["ksef_pkwiu"] = pkwiu

		gtu_code = self._get_xml_value(line_container, "GTU", ns)
		if gtu_code:
			gtu_rec = self.env["ksef.gtu"].search([("name", "=", gtu_code)], limit=1)
			if gtu_rec:
				line_vals["ksef_gtu_id"] = gtu_rec.id
			else:
				_logger.warning(
					"⚠️ Nieznany kod GTU w XML: %s (brak w słowniku ksef.gtu)", gtu_code
				)

		kurs_waluty = _to_float(self._get_xml_value(line_container, "KursWaluty", ns))
		if kurs_waluty is not None:
			line_vals["ksef_kurs_waluty"] = kurs_waluty

		return line_vals

#EoF

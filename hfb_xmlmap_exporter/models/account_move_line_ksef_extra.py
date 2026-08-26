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

   Słownik GTU (JPK_V7) oraz dodatkowe pola importu wierszy KSeF na
   account.move.line, których dotąd nie było w modelu:
   UU_ID, Indeks (kod dostawcy), GTIN, CN, PKWiU, GTU, KursWaluty (wiersz).

   Dane słownika GTU pochodzą z wcześniejszego modułu autora
   (hfb_jpkv7_gtu, OpenERP) - przeniesione i dostosowane do Odoo 18.
"""
from odoo import api, fields, models

_logger = __import__("logging").getLogger(__name__)


#################################################################################
# Słownik GTU - Grupa Towarowo-Usługowa (oznaczenia obowiązkowe w JPK_V7)
#################################################################################
class KsefGtu(models.Model):
	_name = "ksef.gtu"
	_description = "Słownik GTU (JPK_V7)"
	_order = "name"

	name = fields.Char(
		string="Kod",
		required=True,
		index=True,
		help="Kod GTU w formacie GTU_01..GTU_13, zgodny z elementem <GTU> w FaWiersz.",
	)
	description = fields.Text(
		string="Opis",
		help="Pełny opis ustawowy oznaczenia GTU.",
	)

	_sql_constraints = [
		("ksef_gtu_name_uniq", "unique(name)", "Kod GTU musi być unikalny."),
	]

	def name_get(self):
		result = []
		for rec in self:
			result.append((rec.id, rec.name))
		return result


#################################################################################
# account.move.line - dodatkowe pola z FaWiersz, dotąd nieobsługiwane
#################################################################################
class AccountMoveLineKsefExtra(models.Model):
	_inherit = "account.move.line"

	ksef_uu_id = fields.Char(
		string="UU_ID",
		copy=False,
		help="Unikalny identyfikator pozycji nadany przez KSeF (element <UU_ID> w <FaWiersz>).",
	)
	ksef_indeks = fields.Char(
		string="Indeks (kod dostawcy)",
		copy=False,
		help="Wewnętrzny kod magazynowy / indeks towaru u sprzedawcy (element <Indeks>).",
	)
	ksef_gtin = fields.Char(
		string="GTIN",
		copy=False,
		help="Kod kreskowy GTIN towaru (element <GTIN>).",
	)
	ksef_cn = fields.Char(
		string="Kod CN",
		copy=False,
		help="Kod Nomenklatury Scalonej / taryfy celnej (element <CN>).",
	)
	ksef_pkwiu = fields.Char(
		string="PKWiU",
		copy=False,
		help="Kod PKWiU, jeśli podany w fakturze (element <PKWiU>, opcjonalny - nie każda pozycja go ma).",
	)
	ksef_gtu_id = fields.Many2one(
		"ksef.gtu",
		string="GTU",
		copy=False,
		help="Kod GTU (grupa towarowo-usługowa) z elementu <GTU> - wymagany do prawidłowego JPK_V7.",
	)
	ksef_kurs_waluty = fields.Float(
		string="Kurs waluty (wiersz)",
		copy=False,
		digits=(12, 4),
		help=(
			"Kurs waluty przypisany do pozycji faktury (element <KursWaluty> w <FaWiersz>). "
			"Może różnić się od kursu nagłówkowego faktury."
		),
	)

#EoF

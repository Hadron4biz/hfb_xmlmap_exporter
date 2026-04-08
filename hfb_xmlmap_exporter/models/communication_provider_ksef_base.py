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
"""@version 18.1.3
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta, date
import os
import json
import base64
import subprocess
import logging
from markupsafe import Markup, escape

_logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------------
# Rozbudowa do obsługi ZAL / ROZ
# -------------------------------------------------------------------------------
class SaleAdvancePaymentInv(models.TransientModel):
	_inherit = 'sale.advance.payment.inv'

	def _create_invoices(self, sale_orders):
		invoices = super()._create_invoices(sale_orders)

		# Jeżeli to zaliczka
		if self.advance_payment_method in ('percentage', 'fixed'):
			for invoice in invoices:
				invoice.ksef_rodzaj_faktury = 'ZAL'
				invoice.order_id = sale_orders.id

		return invoices

class SaleOrder(models.Model):
	_inherit = 'sale.order'

	def _create_invoices(self, grouped=False, final=False):
		moves = super()._create_invoices(grouped=grouped, final=final)

		for order in self:
			related_moves = moves.filtered(lambda m: m.invoice_origin == order.name)

			# sprawdzamy czy istnieją ZAL
			zal_exists = self.env['account.move'].search_count([
				('order_id', '=', order.id),
				('ksef_rodzaj_faktury', '=', 'ZAL'),
				('state', '!=', 'cancel'),
				('company_id', '=', order.company_id.id),
			]) > 0

			for move in related_moves:
				move.order_id = order.id

				if zal_exists:
					move.ksef_rodzaj_faktury = 'ROZ'
					move._link_zal_from_order()
				else:
					move.ksef_rodzaj_faktury = 'VAT'

		return moves

#################################################################################
# Dodatek roboczy - tymczasowy
#################################################################################
class AccountMoveLineKsef(models.Model):
	_inherit = "account.move.line"

	ksef_is_before_correction = fields.Boolean(
		string="Stan przed korektą",
		help="Czy wiersz reprezentuje stan przed korektą (StanPrzed=1)",
		default=False,
		copy=False,
	)

	ksef_correction_info = fields.Char(
		string="Info korekty",
		help="Dodatkowe informacje o korekcie",
		copy=False,
	)

	ksef_line_correction_type = fields.Selection([
		('before', 'Stan przed korektą'),
		('after', 'Stan po korekcie'),
		('note', 'Wiersz informacyjny'),
	], string="Typ wiersza korekty",
		copy=False,
	)

	# --- KSeF / FA(3) RAW fields ---
	ksef_p_6a = fields.Date(string="P_6A Data")
	ksef_p_6_date = fields.Date(
		string="Data dostawy/wykonania (P_6)",
		copy=False,
		help="""
		Pole odpowiada elementowi P_6 w strukturze faktury FA(3) KSeF.
		
		Data dokonania lub zakończenia dostawy towarów lub wykonania usługi lub data otrzymania zapłaty,
		o której mowa w art. 106b ust. 1 pkt 4 ustawy, o ile taka data jest określona i różni się od
		daty wystawienia faktury. Pole wypełnia się w przypadku, gdy dla wszystkich pozycji faktury
		data jest wspólna.
		"""
	)

	ksef_p_6_from_date = fields.Date(
		string="Okres od (P_6_Od)",
		copy=False,
		help="""
		Pole odpowiada elementowi P_6_Od w strukturze faktury FA(3) KSeF.
		
		Data początkowa okresu, którego dotyczy faktura - w przypadkach, o których mowa w art. 19a
		ust. 3 zdanie pierwsze i ust. 4 oraz ust. 5 pkt 4 ustawy.
		"""
	)

	ksef_p_6_to_date = fields.Date(
		string="Okres do (P_6_Do)",
		copy=False,
		help="""
		Pole odpowiada elementowi P_6_Do w strukturze faktury FA(3) KSeF.
		
		Data końcowa okresu, którego dotyczy faktura - data dokonania lub zakończenia dostawy towarów
		lub wykonania usługi.
		"""
	)

	ksef_p_7 = fields.Char(string="P_7 Opis pozycji")

	ksef_p_8a = fields.Char(string="P_8A Jednostka miary")
	ksef_p_8b = fields.Float(string="P_8B Ilość pomocnicza")

	ksef_p_9a = fields.Monetary(string="P_9A Cena jednostkowa netto")
	ksef_p_10 = fields.Float(string="P_10 Ilość")
	ksef_p_11 = fields.Monetary(string="P_11 Wartość netto")
	ksef_p_12 = fields.Float(string="P_12 Stawka VAT")

	ksef_nr_wiersza_fa = fields.Char(string="NrWierszaFa")

	# opcjonalnie – do debugowania
	ksef_raw_json = fields.Json(string="RAW FaWiersz")

	ksef_line_no = fields.Integer(compute="_compute_ksef_line_no", store=True, copy=False,)
	ksef_tax_percent = fields.Float(compute="_compute_ksef_tax_percent", store=True, copy=False,)
	ksef_uom_code = fields.Char(compute="_compute_ksef_uom_code", store=True, copy=False,)

	@api.depends("move_id", "move_id.invoice_line_ids.sequence")
	def _compute_ksef_line_no(self):
		moves = self.mapped("move_id")
		for move in moves:
			i = 1
			for line in move.invoice_line_ids.sorted("sequence"):
				line.ksef_line_no = i
				i += 1

	@api.depends("tax_ids", "tax_ids.amount")
	def _compute_ksef_tax_percent(self):
		for line in self:
			if line.tax_ids:
				line.ksef_tax_percent = line.tax_ids[0].amount
			else:
				line.ksef_tax_percent = 0

	@api.depends("product_uom_id")
	def _compute_ksef_uom_code(self):
		for line in self:
			line.ksef_uom_code = line.product_uom_id.name or False


	ksef_corrected_line_id = fields.Many2one(
		'account.move.line',
		string='Korygowany wiersz',
		ondelete='restrict',
		copy=False,
		index=True,
		help=(
			"Wskazuje wiersz dokumentu KSeF, który jest korygowany. "
			"Używane do wyznaczenia stanu przed korektą oraz do kolejnych korekt."
		),
	)

	ksef_corrects_move_id = fields.Many2one(
		'account.move',
		string='Korygowany dokument',
		ondelete='restrict',
		copy=False,
		index=True,
	)


#################################################################################
# AccountMoveKsef – pełna wersja z compute
#################################################################################
class AccountMoveKsef(models.Model):
	_inherit = "account.move"

	ksef_log_id = fields.Many2one(
		"communication.log",
		string="Proces Komunikacji",
		help="Ostatnio używany proces obsługi wysyłki KSeF",
		copy=False,
		readonly=True,
		index=True,
	)

	ksef_process_state = fields.Selection([
		('none', 'Brak procesu'),
		('queued', 'W kolejce'),
		('processing', 'W trakcie wysyłki'),
		('waiting', 'Oczekiwanie na MF'),
		('completed', 'Poświadczenie Odbioru'),
		('imported', 'Zaimportowany'),
		('error', 'Błąd'),
		('offline', 'Offline'),
		], 
		compute="_compute_ksef_ui_state", 
		store=True,
		string="Status obsługi",
	)

	ksef_process_message = fields.Char(
		compute="_compute_ksef_ui_state",
		store=True,
		string="Komunikat",
	)

	ksef_ui_status = fields.Selection([
		('pending', 'Pending'),
		('in_progress', 'In Progress'),
		('confirmed', 'Confirmed'),
		('error', 'Error'),
	], compute="_compute_ksef_ui_status", store=True)

	@api.depends('ksef_process_state')
	def _compute_ksef_ui_status(self):
		for rec in self:
			state = rec.ksef_process_state

			if state in ['none', 'queued']:
				rec.ksef_ui_status = 'pending'

			elif state in ['processing', 'waiting']:
				rec.ksef_ui_status = 'in_progress'

			elif state in ['completed', 'imported']:
				rec.ksef_ui_status = 'confirmed'

			elif state in ['error', 'offline']:
				rec.ksef_ui_status = 'error'

			else:
				rec.ksef_ui_status = 'pending'

	# -------------------------------------------------------- User UI
	def get_ksef_user_message(self):
		self.ensure_one()

		log = self.ksef_log_id
		if not log:
			return "Brak operacji KSeF"

		# Interesuje nas tylko stan błędu
		if log.ksef_status != "failed":
			return log.provider_message or "Operacja w toku"

		payload = log.payload_response
		if not payload:
			return "Operacja zakończona błędem"

		try:
			result = json.loads(payload)
		except Exception:
			return "Operacja zakończona błędem (nieczytelna odpowiedź KSeF)"

		data = result.get("data") or {}
		response = data.get("response") or {}
		status = response.get("status") or {}

		status_code = data.get("statusCode")
		description = status.get("description") or data.get("statusDescription")
		invoice_count = response.get("invoiceCount")
		failed_count = response.get("failedInvoiceCount")
		has_upo = data.get("hasUPO")

		lines = []

		if status_code:
			lines.append(f"Status Sesji: {status_code}")

		if description:
			lines.append(description)

		if invoice_count is not None:
			lines.append(f"Liczba faktur w sesji: {invoice_count}")

		if failed_count:
			lines.append(f"Odrzucone: {failed_count}")

		if has_upo is False:
			lines.append("Brak UPO")

		return "\n".join(lines) if lines else "Operacja zakończona błędem"

	@api.depends('ksef_log_id.ksef_status')
	def _compute_ksef_ui_state(self):
		for move in self:
			log = move.ksef_log_id

			move.ksef_process_state = 'none'
			move.ksef_process_message = False

			if not log:
				continue

			# 1. BŁĄD – najwyższy priorytet
			if log.ksef_status == 'failed' or log.ksef_operation == 'failed':
				move.ksef_process_state = 'error'
				move.ksef_process_message = move.get_ksef_user_message()
				continue

			# 2. Oczekiwanie MF / retry
			if log.ksef_status == 'waiting_delay':
				move.ksef_process_state = 'waiting'
				move.ksef_process_message = "Oczekiwanie na odpowiedź MF"
				continue

			# 3. Aktualnie przetwarzane
			if log.is_processing:
				move.ksef_process_state = 'processing'
				move.ksef_process_message = "Trwa komunikacja z KSeF"
				continue

			# 4. Sukces Export
			if log.ksef_operation == 'completed' and log.ksef_status == 'success' and log.direction == 'export':
				move.ksef_process_state = 'completed'
				move.ksef_process_message = "Faktura zarejestrowana w KSeF"
				continue

			# 4. Sukces Import
			if log.ksef_operation == 'completed' and log.direction == 'import':
				move.ksef_process_state = 'imported'
				move.ksef_process_message = "Faktura zaimportowana z KSeF"
				continue

			# 5. Wysłane – czekamy
			if log.state == 'sent' and log.ksef_operation in ('check_status','download_upo'):
				move.ksef_process_state = 'waiting'
				move.ksef_process_message = "Oczekiwanie na przetworzenie przez MF"
				continue

			# 6. W kolejce
			if log.state == 'queued':
				move.ksef_process_state = 'queued'
				move.ksef_process_message = "W kolejce do wysyłki"
				continue

			# 7. Kroki techniczne
			move.ksef_process_state = 'processing'
			move.ksef_process_message = "Przetwarzanie operacji KSeF"

			_logger.info(
				f'\nlog.state = {log.state}'
				f'\nlog.ksef_operation = {log.ksef_operation}'
				f"\nmove.ksef_process_state = {move.ksef_process_state}"
				f'\nmove.ksef_process_message = {move.ksef_process_message}'
				f'\n======================================================================================'
			)


	# ---------------------------------- sekcja Płatności
	ksef_payment_form = fields.Selection([
		('1', 'Gotówka'),
		('2', 'Karta'),
		('3', 'Bon'),
		('4', 'Czek'),
		('5', 'Kredyt'),
		('6', 'Przelew'),
		('7', 'Mobilna'),
		('other', 'Inna'),
	], string="Forma płatności")

	ksef_payment_other_desc = fields.Char(
		string="Opis innej formy płatności",
		copy=False,
	)

	# Użycie dla: loop_expr: record.ksef_reconciled_payments
	ksef_reconciled_payments = fields.Many2many(
		'account.payment',
		string='Powiązane płatności (KSEF)',
		compute='_compute_ksef_payments',
		store=True
	)

	@api.onchange('payment_state', 'state')
	@api.depends('payment_state', 'state')
	def _compute_ksef_payments(self):
		for move in self:
			# Wyszukaj płatności powiązane z tą fakturą poprzez pole invoice_ids
			# ToDo: poza Odoo 18 może być to poważnym problemem
			payments = self.env['account.payment'].search([('invoice_ids', 'in', move.id)])	###XXX
			move.ksef_reconciled_payments = payments 										###XXX

	# --------------------------------------------------------------- Kursy walut
	ksef_kurswaluty = fields.Float(
		string="Kurs waluty",
		digits=(12, 6),
		copy=False,
		tracking=True,
		default=1.0,
		help=(
			"Historyczny kurs waluty względem PLN "
			"z dnia poprzedzającego wystawienie faktury. "
			"Wykorzystywany do generowania XML FA(3) oraz "
			"zapisywany przy imporcie z KSeF."
		),
	)

	@api.onchange("currency_id", "invoice_date")
	def _onchange_set_ksef_rate(self):
		if self.currency_id and self.currency_id.name != "PLN":
			date = self.invoice_date or fields.Date.context_today(self)
			rate = self.currency_id._get_rates(
				self.company_id,
				date
			).get(self.currency_id.id)
			self.ksef_kurswaluty = rate
		else:
			self.ksef_kurswaluty = 1.0

	# na potrzeby identyfikowania zamówienia z fakturą
	order_id = fields.Many2one(
		'sale.order', 
		string='Order', 
		copy=False, 
		index=True,
		store=True,
		readonly=False
	)

	@api.model_create_multi
	def create(self, vals_list):
		"""Rozszerzenie metody create dla wielu rekordów"""
		for vals in vals_list:
			if vals.get('origin') and not vals.get('order_id'):
				order = self.env['sale.order'].search(
					[
						('name', '=', vals.get('origin')),
						('company_id', '=', self.company_id.id)
					], 
					limit=1
				)
				if order:
					vals['order_id'] = order.id
		return super().create(vals_list)

	def write(self, values):
		if values.get('origin'):
			origin = values.get('origin')
			order = self.env['sale.order'].search(
				[
					('name','=', origin),
					('company_id', '=', self.company_id.id)
				], limit=1)
			if order:
				values['order_id'] = order.id
		return super().write(values)


	ksef_number = fields.Char('Nr KSeF', store=True, copy=False, tracking=True, )
	ksef_sent_date = fields.Datetime('Data przesłania', store=True,  copy=False,)

	ksef_rodzaj_faktury = fields.Char(
		string="Rodzaj faktury",
		help='Wartość pola RodzajFaktury ["VAT", "KOR", "ZAL", "ROZ", "UPR", "KOR_ZAL", "KOR_ROZ"]',
		copy=False,
		default="VAT",
		tracking=True,
	)

	ksef_numer_korygowanej = fields.Char(
		string="Nr Faktury Korygowanej",
		copy=False,
		help="NrKSeFFaKorygowanej",
		tracking=True,
	)

	ksef_creation_datetime = fields.Datetime( copy=False,)
	ksef_system_info = fields.Char( copy=False,)
	invoice_city = fields.Char( copy=False,)


	# --- Podstawowe oznaczenia (sekcja Adnotacje) ---
	ksef_p16 = fields.Selection(
		[
			('1', '1 – metoda kasowa'),
			('2', '2 – brak metody kasowej')
		],
		string="Metoda kasowa (P_16)",
		default='2',
		copy=False,
		help="""
		Pole odpowiada elementowi P_16 w strukturze faktury FA(3) KSeF.
		
		W przypadku dostawy towarów lub świadczenia usług, w odniesieniu do których
		obowiązek podatkowy powstaje zgodnie z art. 19a ust. 5 pkt 1 lub art. 21 ust. 1 ustawy
		- wyrazy "metoda kasowa"; należy podać wartość '1', w przeciwnym przypadku - wartość '2'.
		"""
	)

	ksef_p17 = fields.Selection(
		[
			('1', '1 – samofakturowanie'),
			('2', '2 – brak samofakturowania')
		],
		string="Samofakturowanie (P_17)",
		default='2',
		copy=False,
		help="""
		Pole odpowiada elementowi P_17 w strukturze faktury FA(3) KSeF.
		
		W przypadku faktur, o których mowa w art. 106d ust. 1 ustawy - wyraz "samofakturowanie";
		należy podać wartość '1', w przeciwnym przypadku - wartość '2'.
		"""
	)

	ksef_p18 = fields.Selection(
		[
			('1', '1 – odwrotne obciążenie'),
			('2', '2 – brak odwrotnego obciążenia')
		],
		string="Odwrotne obciążenie (P_18)",
		default='2',
		copy=False,
		help="""
		Pole odpowiada elementowi P_18 w strukturze faktury FA(3) KSeF.
		
		W przypadku dostawy towarów lub wykonania usługi, dla których obowiązanym do rozliczenia
		podatku od wartości dodanej lub podatku o podobnym charakterze jest nabywca towaru lub usługi
		- wyrazy "odwrotne obciążenie"; należy podać wartość '1', w przeciwnym przypadku - wartość '2'.
		"""
	)

	ksef_p18a = fields.Selection(
		[
			('1', '1 – mechanizm podzielonej płatności (MPP)'),
			('2', '2 – brak mechanizmu podzielonej płatności')
		],
		string="Mechanizm podzielonej płatności (P_18A)",
		default='2',
		copy=False,
		help="""
		Pole odpowiada elementowi P_18A w strukturze faktury FA(3) KSeF.
		
		W przypadku faktur, w których kwota należności ogółem przekracza kwotę 15 000 zł lub jej
		równowartość wyrażoną w walucie obcej, obejmujących dokonaną na rzecz podatnika dostawę towarów
		lub świadczenie usług, o których mowa w załączniku nr 15 do ustawy - wyrazy 
		"mechanizm podzielonej płatności"; należy podać wartość '1', w przeciwnym przypadku - wartość '2'.
		"""
	)

	ksef_p19n = fields.Selection(
		[
			('1', '1 – brak zwolnień'),
			('2', '2 – występują zwolnienia')
		],
		string="Brak zwolnień (P_19N)",
		default='2',
		copy=False,
		help="Znacznik braku dostawy towarów lub świadczenia usług zwolnionych od podatku."
	)

	ksef_p22n = fields.Selection(
		[
			('1', '1 – brak nowych środków transportu'),
			('2', '2 – występują nowe środki transportu')
		],
		string="Brak nowych środków transportu (P_22N)",
		default='1',
		copy=False,
		help="Znacznik braku wewnątrzwspólnotowej dostawy nowych środków transportu."
	)

	ksef_p23 = fields.Selection(
		[
			('1', '1 – procedura uproszczona (drugi w kolejności podatnik)'),
			('2', '2 – brak procedury uproszczonej')
		],
		string="Procedura uproszczona (P_23)",
		default='2',
		copy=False,
		help="""
		Pole odpowiada elementowi P_23 w strukturze faktury FA(3) KSeF.
		
		W przypadku faktur wystawianych w procedurze uproszczonej przez drugiego w kolejności podatnika,
		o którym mowa w art. 135 ust. 1 pkt 4 lit. b i c oraz ust. 2 ustawy, zawierającej adnotację,
		o której mowa w art. 136 ust. 1 pkt 1 ustawy i stwierdzenie, o którym mowa w art. 136 ust. 1 pkt 2 ustawy,
		należy podać wartość '1', w przeciwnym przypadku - wartość '2'.
		"""
	)

	ksef_pmarzyn = fields.Boolean(
		string="Procedura marży – inne przypadki (PMarzyN)",
		copy=False,
		help="""
		Pole odpowiada elementowi PMarzyN w strukturze faktury FA(3) KSeF.

		Oznacza zastosowanie procedury marży w innych przypadkach niż wskazane
		w dedykowanych oznaczeniach faktury (np. P_19N, P_22N, P_23).

		Wartości:
		• zaznaczone – faktura została wystawiona w procedurze marży
		  w innym przypadku przewidzianym przepisami VAT
		• niezaznaczone – procedura marży nie ma zastosowania

		Oznaczenie to stosowane jest pomocniczo do wskazania szczególnego
		sposobu opodatkowania VAT, w którym podstawą opodatkowania jest marża
		sprzedawcy. Wartość pola jest przenoszona do struktury XML
		przekazywanej do KSeF.
		"""
	)

	ksef_is_jst = fields.Boolean(
		string="Jednostka samorządu terytorialnego (JST)",
		copy=False,
		help="""
		Pole odpowiada oznaczeniu JST w strukturze faktury FA(3) KSeF.

		Wskazuje czy sprzedawca jest jednostką samorządu terytorialnego
		(np. gmina, powiat, województwo) lub jednostką organizacyjną JST
		działającą w ramach centralizacji rozliczeń VAT.

		Wartości:
		• zaznaczone – faktura wystawiona przez jednostkę samorządu terytorialnego (JST)
		• niezaznaczone – sprzedawca nie jest jednostką samorządu terytorialnego

		Oznaczenie to stosowane jest w przypadku podmiotów objętych
		szczególnymi zasadami rozliczeń VAT JST.
		Wartość pola jest przenoszona do struktury XML przekazywanej do KSeF.
		"""
	)

	ksef_is_vat_group = fields.Boolean(
		string="Grupa VAT (GV)",
		copy=False,
		help="""
		Pole odpowiada oznaczeniu GV w strukturze faktury FA(3) KSeF.

		Wskazuje czy sprzedawca jest członkiem grupy VAT,
		o której mowa w art. 15a ustawy o podatku od towarów i usług.

		Wartości:
		• zaznaczone – faktura wystawiona przez podatnika działającego w ramach grupy VAT
		• niezaznaczone – sprzedawca nie jest członkiem grupy VAT

		Oznaczenie stosowane jest w przypadku podmiotów rozliczających VAT
		jako jedna grupa podatkowa. Informacja ta jest przekazywana w strukturze
		XML przesyłanej do KSeF.
		"""
	)

	ksef_facontrol = fields.Integer(
		string="Numer kontrolny FA (FaCtrl)",
		copy=False,
		help="""
		Pole odpowiada elementowi FaCtrl w strukturze faktury FA(3) KSeF.

		Jest to liczba kontrolna obliczana dla struktury Fa w celu zapewnienia
		integralności danych przekazywanych do KSeF. Wartość ta jest generowana
		automatycznie na podstawie zawartości dokumentu XML.

		Wartości:
		• liczba całkowita – numer kontrolny obliczony dla sekcji Fa dokumentu

		Pole ma charakter techniczny i jest wykorzystywane w procesie weryfikacji
		poprawności struktury XML faktury przesyłanej do KSeF.
		"""
	)

	ksef_podmiot3_partner_id = fields.Many2one(
		'res.partner',
		string="Podmiot trzeci (Podmiot3)",
		copy=False,
		help="""
		Pole odpowiada elementowi Podmiot3 w strukturze faktury FA(3) KSeF.

		Wskazuje podmiot trzeci uczestniczący w transakcji, inny niż sprzedawca
		(Podmiot1) i nabywca (Podmiot2). Może to być np. podmiot pośredniczący
		w transakcji, podmiot rozliczający płatność lub inna jednostka wskazana
		w strukturze faktury.

		Wartości:
		• partner – rekord kontrahenta z bazy Odoo wskazany jako Podmiot3

		Dane wybranego partnera są wykorzystywane do wypełnienia sekcji Podmiot3
		w strukturze XML faktury przekazywanej do KSeF.
		"""
	)

	ksef_podmiot3_role = fields.Selection([
		('1', '1 - Faktor'),
		('2', '2 - Odbiorca (jednostka wewnętrzna)'),
		('3', '3 - Podmiot pierwotny'),
		('4', '4 - Dodatkowy nabywca'),
		('5', '5 - Wystawca faktury'),
		('6', '6 - Dokonujący płatności'),
		('7', '7 - JST wystawca'),
		('8', '8 - JST odbiorca'),
		('9', '9 - Członek grupy VAT wystawca'),
		('10', '10 - Członek grupy VAT odbiorca'),
		('11', '11 - Pracownik')
	], string='Rola Podmiotu3', default='2', copy=False,)

	ksef_podmiot3_address_line = fields.Char(
		string="Podmiot trzeci – adres (linia adresowa)",
		copy=False,
		help="""
		Pole odpowiada elementowi adresu w sekcji Podmiot3 struktury faktury FA(3) KSeF.

		Określa linię adresową podmiotu trzeciego uczestniczącego w transakcji,
		wskazanego w sekcji Podmiot3 dokumentu.

		Wartości:
		• tekst – linia adresowa (np. ulica, numer budynku i lokalu)

		Dane z tego pola są wykorzystywane do wypełnienia części adresowej
		podmiotu trzeciego w strukturze XML faktury przekazywanej do KSeF.
		Pole stosowane jest w przypadku, gdy w fakturze wskazano dodatkowy
		podmiot uczestniczący w transakcji.
		"""
	)

	# 🔧 NOWE POLA 
	ksef_delivery_date = fields.Date(
		string="Data dostawy (P_6)",
		copy=False,
		help="""
		Pole odpowiada elementowi P_6 w strukturze faktury FA(3) KSeF.

		Określa datę dokonania lub zakończenia dostawy towarów albo wykonania usługi,
		jeżeli jest ona określona i różni się od daty wystawienia faktury.

		Wartości:
		• data – dzień dokonania dostawy towarów lub wykonania usługi

		Zgodnie z przepisami VAT pole to stosuje się w przypadku, gdy moment dostawy
		lub wykonania usługi jest znany i powinien zostać wykazany na fakturze.
		Wartość pola jest przenoszona do struktury XML przekazywanej do KSeF.
		"""
	)

	ksef_is_advance = fields.Boolean(
		string="Faktura zaliczkowa (ZAL)",
		copy=False,
		help="""
		Pole wskazuje czy dokument jest fakturą zaliczkową w rozumieniu struktury
		FA(3) KSeF.

		W przypadku zaznaczenia pole wpływa na ustawienie rodzaju faktury
		„ZAL” (zaliczkowa) w elemencie RodzajFaktury dokumentu XML.

		Wartości:
		• zaznaczone – faktura dokumentuje otrzymanie zaliczki lub przedpłaty
		• niezaznaczone – faktura nie jest fakturą zaliczkową

		Oznaczenie stosuje się w przypadku otrzymania części lub całości zapłaty
		przed dokonaniem dostawy towarów lub wykonaniem usługi. Informacja ta
		wpływa na sposób generowania struktury XML faktury przekazywanej do KSeF.
		"""
	)

	ksef_is_settlement = fields.Boolean(
		string="Faktura rozliczeniowa (ROZ)",
		copy=False,
		help="""
		Pole wskazuje czy dokument jest fakturą rozliczeniową w rozumieniu
		struktury FA(3) KSeF.

		W przypadku zaznaczenia pole wpływa na ustawienie rodzaju faktury
		„ROZ” (rozliczeniowa) w elemencie RodzajFaktury dokumentu XML.

		Wartości:
		• zaznaczone – faktura rozlicza wcześniej otrzymane zaliczki
		• niezaznaczone – dokument nie jest fakturą rozliczeniową

		Faktura rozliczeniowa wystawiana jest po dokonaniu dostawy towarów
		lub wykonaniu usługi, gdy wcześniej wystawiono jedną lub więcej
		faktur zaliczkowych. Informacja ta wpływa na sposób generowania
		struktury XML faktury przekazywanej do KSeF.
		"""
	)

	ksef_is_upr = fields.Boolean(
		string="Faktura uproszczona (UPR)",
		copy=False,
		help="""
		Pole wskazuje czy dokument jest fakturą uproszczoną w rozumieniu
		struktury FA(3) KSeF.

		W przypadku zaznaczenia pole wpływa na ustawienie rodzaju faktury
		„UPR” (faktura uproszczona) w elemencie RodzajFaktury dokumentu XML.

		Wartości:
		• zaznaczone – dokument jest fakturą uproszczoną
		• niezaznaczone – dokument jest standardową fakturą VAT

		Faktura uproszczona może być wystawiona w przypadku sprzedaży,
		której wartość brutto nie przekracza 450 PLN lub 100 EUR,
		a dokument zawiera ograniczony zakres danych wymaganych
		przepisami VAT. Informacja ta wpływa na sposób generowania
		struktury XML faktury przekazywanej do KSeF.
		"""
	)

	ksef_correction_type = fields.Selection([
		('0', 'To nie jest korekta'),
		('1', 'Korekta danych formalnych'),
		('2', 'Korekta danych rachunkowych'),
		('3', 'Korekta danych formalnych i rachunkowych')
		],
		default='0'
	)
	ksef_advance_refs = fields.Char('Numery faktur zaliczkowych')  # dla ROZ
	ksef_order_value = fields.Float('Wartość zamówienia')  # dla ZAL

	# pole techniczne
	ksef_corrected_ref = fields.Char(
		copy=False,
		tracking=True,
		default=False,
	)

	ksef_corrects_move_id = fields.Many2one(
		'account.move',
		string='Korygowany dokument',
		ondelete='restrict',
		copy=False,
		index=True,
	)

	requires_reversed_entry = fields.Boolean(
		string="Wymaga powiązania z fakturą korygowaną",
		help="Flaga wskazująca, że faktura korekta wymaga ręcznego powiązania z fakturą źródłową",
		copy=False,
		tracking=True,
		default=False,
	)

	# 1. Kod typu korekty (1-9)
	ksef_correction_type_code = fields.Char(
		string="Typ korekty",
		help="Typ korekty z XML (1-9): 1=wartość, 2=dane podmiotów, 3=dane pozycji, ...",
		copy=False,
		tracking=True,
	)

	# 2. Pole pomocnicze dla debugowania
	ksef_stan_przed = fields.Char(
		string="Stan przed (debug)",
		help="Pole pomocnicze do debugowania przetwarzania korekt",
		copy=False,
	)

	# pole dla wierszy (opcjonalnie)
	ksef_is_before_correction = fields.Boolean(
		string="Stan przed korektą",
		help="Czy wiersz reprezentuje stan przed korektą",
		default=False,
		copy=False,
	)

	ksef_correction_info = fields.Char(
		string="Info korekty",
		help="Dodatkowe informacje o korekcie",
		copy=False,
	)

	ksef_line_correction_type = fields.Selection([
		('before', 'Stan przed korektą'),
		('after', 'Stan po korekcie'),
		('note', 'Wiersz informacyjny'),
	], string="Typ wiersza korekty",
		copy=False,
	)

	# Specjalne pola dla korekt zaliczkowych
	ksef_p15zk = fields.Float(
		string="P_15ZK - Wartość przed korektą",
		help="Dla faktur KOR_ZAL - kwota zapłaty przed korektą",
		copy=False,
	)

	ksef_wartosc_zamowienia = fields.Float(
		string="Wartość zamówienia",
		help="Wartość zamówienia z pola WartoscZamowienia",
		copy=False,
	)

	ksef_is_advance_line = fields.Boolean(
		string="Wiersz zaliczkowy",
		help="Czy wiersz dotyczy faktury zaliczkowej",
		default=False,
		copy=False,
	)



	@api.onchange("company_id")
	def _onchange_invoice_city(self):
		if self.company_id and self.company_id.city:
			self.invoice_city = self.company_id.city

	@api.onchange("ksef_podmiot3_partner_id")
	def _onchange_podmiot3_address(self):
		p = self.ksef_podmiot3_partner_id
		if p:
			parts = filter(None, [p.street, p.street2, f"{p.zip} {p.city}"])
			self.ksef_podmiot3_address_line = ", ".join(parts)


	# ---------------------------------------------------------------------------
	# Obsługa faktury ROZ dla sekcji: FakturaZaliczkowa / NrKSeFFaZaliczkowej
	# ---------------------------------------------------------------------------
	ksef_related_zal_ids = fields.Many2many(
		'account.move',
		'ksef_roz_zal_rel',
		'roz_id',
		'zal_id',
		string='Rozliczane faktury zaliczkowe',
		domain="[('ksef_rodzaj_faktury','=','ZAL')]",
		copy=False
	)

	ksef_import_zal_numbers = fields.Json(
		string='Numery ZAL z importu (tymczasowe)',
		copy=False
	)

	def _link_zal_from_order(self):
		for move in self:
			if move.ksef_rodzaj_faktury != 'ROZ':
				continue

			if not move.order_id:
				continue

			zal_moves = self.env['account.move'].search([
				('company_id', '=', move.company_id.id),
				('order_id', '=', move.order_id.id),
				('ksef_rodzaj_faktury', '=', 'ZAL'),
				('state', '!=', 'cancel')
			])

			move.ksef_related_zal_ids = [(6, 0, zal_moves.ids)]

	def _link_imported_zal(self, zal_numbers):
		self.ensure_one()

		_logger.info(f"\n📢 zal_numbers = {zal_numbers}")

		if self.ksef_rodzaj_faktury != 'ROZ':
			return

		if not zal_numbers:
			return

		zal_moves = self.env['account.move'].search([
			('company_id', '=', self.company_id.id),
			('ksef_number', 'in', zal_numbers),
			('ksef_rodzaj_faktury', '=', 'ZAL')
		])

		found = set(zal_moves.mapped('ksef_number'))
		missing = set(zal_numbers) - found

		if missing:
			self.message_post(
				body=(
					"Nie znaleziono w systemie faktur ZAL o numerach:<br/>"
					f"<b>{', '.join(missing)}</b>"
				)
			)

		if zal_moves:
			self.ksef_related_zal_ids = [(6, 0, zal_moves.ids)]

		_logger.info(f"\n📢 zal_moves = {zal_moves}")


	# ---------------------------------------------------------------------------
	# Obsługa Korekty KSeF
	# ---------------------------------------------------------------------------
	def _prepare_ksef_correction_lines(self):
		"""
		Zwraca recordset linii faktury: [źródłowa, bieżąca], [źródłowa, bieżąca], ...
		Wyłącznie dla faktur korekt typu KOR, typ 2/3.
		"""
		self.ensure_one()
		if (
			self.ksef_rodzaj_faktury != 'KOR'
			or self.move_type != 'out_invoice'
			or self.ksef_correction_type not in ['2', '3']
		):
			return self.invoice_line_ids

		result = self.env['account.move.line']
		for line in self.invoice_line_ids:
			if line.ksef_corrected_line_id and line.ksef_line_correction_type:
				# dodaj najpierw linię źródłową (stan przed)
				result += line.ksef_corrected_line_id
			# dodaj bieżącą linię (stan po)
			result += line
		return result

	def action_create_ksef_correction(self):
		self.ensure_one()
		if self.move_type != 'out_invoice' or self.state != 'posted' or not self.ksef_number:
			raise UserError(_(
				"Korektę można utworzyć tylko dla zakończonej "
				"faktury sprzedażowej wysłanej do KSeF."
			))

		# 1. Wywołanie standardowego wizardu Odoo (identycznie jak z UI)
		wizard = self.env['account.move.reversal'].with_context(
			active_ids=[self.id],
			active_model='account.move',
		).create({
			'date': fields.Date.context_today(self),
			'journal_id': self.journal_id.id,
			'reason': _('Korekta KSeF: %s') % self.name,
		})

		wizard.modify_moves()

		# 2. Pobranie utworzonych dokumentów
		new_moves = wizard.new_move_ids

		refund = new_moves.filtered(lambda m: m.move_type == 'out_refund')[:1]
		correction = new_moves.filtered(lambda m: m.move_type == 'out_invoice')[:1]

		if not correction:
			raise UserError(_("Nie udało się utworzyć faktury korekty."))

		# 3. Ustawienie danych KSeF na nowej fakturze
		correction.write({
			'ksef_rodzaj_faktury': 'KOR',
			'ksef_corrects_move_id': self.id,
			'ksef_numer_korygowanej': self.ksef_number,
			'ksef_creation_datetime': fields.Datetime.now(),
		})

		# 4. Powiązanie linii korekty z oryginałem
		orig_lines = self.invoice_line_ids.sorted('sequence')
		corr_lines = correction.invoice_line_ids.sorted('sequence')

		for i, (corr_line, orig_line) in enumerate(zip(corr_lines, orig_lines), start=1):
			line_number = str(i)

			# przypisz numer wiersza korekty (stan po)
			corr_line.write({
				'ksef_corrected_line_id': orig_line.id,
				'ksef_corrects_move_id': self.id,
				'ksef_line_correction_type': 'after',
				'ksef_is_before_correction': False,
				'ksef_nr_wiersza_fa': line_number,
			})

			# aktualizacja wierszy oryginału
			orig_line.update({
				'ksef_line_correction_type': 'before',
				'ksef_is_before_correction': True,
			})

			# przypisz ten sam numer do oryginału, jeśli nie miał
			if not orig_line.ksef_nr_wiersza_fa:
				orig_line.ksef_nr_wiersza_fa = line_number


		# 5. Powiązanie refundu ze źródłem (opcjonalne, jeśli masz takie pole)
		if refund and hasattr(self, 'reversal_move_id'):
			self.reversal_move_id = refund.id

		# 6. Zwrot widoku nowej faktury korekty
		return {
			'type': 'ir.actions.act_window',
			'res_model': 'account.move',
			'res_id': correction.id,
			'view_mode': 'form',
			'target': 'current',
		}




#################################################################################
# ResPartnerKsef – pełna wersja z compute
#################################################################################
class ResPartnerKsef(models.Model):
	_inherit = "res.partner"

	ksef_address_line = fields.Char(compute="_compute_ksef_address_line", store=True, copy=False,)
	ksef_is_foreign = fields.Boolean(compute="_compute_ksef_is_foreign", store=True, copy=False,)

	@api.depends("street", "street2", "zip", "city")
	def _compute_ksef_address_line(self):
		for rec in self:
			parts = filter(None, [rec.street, rec.street2 or "", f"{rec.zip or ''} {rec.city or ''}"])
			rec.ksef_address_line = ", ".join(parts)

	@api.depends("country_id", "vat")
	def _compute_ksef_is_foreign(self):
		for rec in self:
			if rec.country_id and rec.country_id.code != "PL":
				rec.ksef_is_foreign = True
			else:
				rec.ksef_is_foreign = False


#################################################################################
# ResCompanyKsef – pełna wersja z compute
#################################################################################
class ResCompanyKsef(models.Model):
	_inherit = "res.company"

	vat_clean = fields.Char(compute="_compute_vat_clean", store=True, copy=False,)
	ksef_address_line = fields.Char(compute="_compute_ksef_address_line", store=True, copy=False,)

	@api.depends("vat")
	def _compute_vat_clean(self):
		for rec in self:
			if rec.vat:
				rec.vat_clean = rec.vat.replace("PL", "").replace("-", "").replace(" ", "")
			else:
				rec.vat_clean = False

	@api.depends("street", "street2", "zip", "city")
	def _compute_ksef_address_line(self):
		for rec in self:
			parts = filter(None, [rec.street, rec.street2, f"{rec.zip} {rec.city}"])
			rec.ksef_address_line = ", ".join(parts)

#################################################################################
#EoF

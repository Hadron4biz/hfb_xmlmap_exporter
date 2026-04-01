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
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import re
from odoo import release
import io
import uuid
from lxml import etree

import logging
_logger = logging.getLogger(__name__)


"""
	Każdy provider musi implementować:

		authenticate(channel)
		send_document(log)
		fetch_documents(channel)
		get_status(log)
"""
class CommunicationProvider(models.Model):
	_name = "communication.provider"
	_description = "Base Communication Provider"
	_inherit = ["mail.thread", "mail.activity.mixin"]
	_order = "name"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=True,  # <-- wymagane
		default=lambda self: self.env.company,
		ondelete='cascade'
	)

	# -------------------------------------------------------------------------
	# IDENTYFIKACJA PROVIDERA
	# -------------------------------------------------------------------------
	name = fields.Char(required=True, tracking=True)
	code = fields.Char(required=True, index=True, tracking=True)
	active = fields.Boolean(default=True)
	description = fields.Text()

	def _compute_display_name(self):
		for record in self:
			record.display_name = f"{record.name} ({record.code})"

	display_name = fields.Char(compute='_compute_display_name', store=True)

	# -------------------------------------------------------------------------
	#  KLUCZOWE: Typ providera rozszerzany dynamicznie przez provider.*
	# -------------------------------------------------------------------------
	provider_type = fields.Selection(
		selection=[
			('localdir', 'Lokalny katalog (LocalDir)'),
			("ksef", "Krajowy System e-Faktur (KSeF)"),
			# Provider.* będzie dodawał swoje wpisy przez selection_add
		],
		string="Typ providera",
		default='localdir',
		required=True,
		tracking=True,
		help="Typ providera, rozszerzany dynamicznie przez moduły provider.*"
	)

	# 2. MODEL pluginu (obliczane, nie edytowalne)
	provider_model = fields.Char(
		string="Model pluginu",
		compute="_compute_provider_model",
		store=True,
		help="Model określony przez provider_type"
	)
	# 3. KONKRETNY rekord z wybranego modelu
	provider_config_id = fields.Many2oneReference(
		string="Konfiguracja",
		model_field="provider_model",  # ✅
		# string_field="name",  # ✅ opcjonalne
		help="Wybierz konkretną konfigurację dla tego providera",
		#tracking=True,
	)
	# Pole pomocnicze do trackingu (opcjonalne)
	provider_config_name = fields.Char(
		string="Nazwa konfiguracji",
		compute="_compute_provider_config_name",
		store=True,
		tracking=True,  # ✅ Możesz trackować to pole zamiast
		help="Nazwa wybranej konfiguracji (do śledzenia zmian)"
	)

	dynamic_config_name = fields.Selection(
		selection=lambda x: x._selection_config_name(),
	)

	def _selection_config_name(self):
		_logger.info(
			f"\n[SELECT] provider_model = {self.provider_model}"
			f"\n[SELECT] provider_config_name = {self.provider_config_name}"
		)
		if self.provider_model:
			provider_model = self.provider_model
			fields = (
				self.env[self.provider_model]
				.sudo()
				.search(
					[
						("active", "!=", False),
					]
				)
			)
			return sorted(
				[(field.code, field.name) for field in fields], key=lambda f: f[1]
			)
		return [('none','Brak wyboru')]

	# -------------------------------------------------------------------------
	# 3. KIEDY WYSYŁAĆ? (AUTOMATYZACJA) - TO JEST KLUCZOWE!
	# -------------------------------------------------------------------------
	trigger_type = fields.Selection([
		('manual', 'Ręcznie (tylko przez akcję)'),
		('immediate', 'Natychmiast po wygenerowaniu'),
		('on_document_validate', 'Po zatwierdzeniu dokumentu'),
		('on_document_post', 'Po zaksięgowaniu dokumentu'),
		('cron_scheduled', 'Według harmonogramu (CRON)'),
		('batch_nightly', 'Partiami nocnymi'),
	], 
		string="Tryb wysyłki",
		default='manual',
		required=True,
		tracking=True,
		help="""
			manual - tylko ręcznie przez przycisk
			immediate - od razu po wygenerowaniu XML
			on_document_validate - po zatwierdzeniu dokumentu w Odoo
			on_document_post - po zaksięgowaniu (dla faktur)
			cron_scheduled - według harmonogramu CRON
			batch_nightly - partiami w nocy (np. 02:00)
		"""
	)
	
	cron_id = fields.Many2one(
		"ir.cron",
		string="Harmonogram CRON",
		help="Ustaw jeśli trigger_type = 'cron_scheduled'",
		domain="[('model_id.model', '=', 'communication.provider')]",
		ondelete="set null"
	)
	
	batch_time = fields.Char(
		string="Czas batcha",
		default="02:00",
		help="Czas wykonywania batcha (format HH:MM), np. '02:00' dla nocnego",
		#attrs='invisible="{ trigger_type != batch_nightly}"'
	)
	
	batch_size = fields.Integer(
		string="Rozmiar batcha",
		default=50,
		help="Ile dokumentów przetwarzać na raz w trybie batch",
		#attrs='invisible="{ trigger_type != batch_nightly }"'
	)
	
	# -------------------------------------------------------------------------
	# 4. DODATKOWE OPCJE
	# -------------------------------------------------------------------------
	auto_retry = fields.Boolean(
		string="Auto-ponawianie",
		default=True,
		help="Automatycznie ponawiaj wysyłkę przy błędzie"
	)
	
	retry_attempts = fields.Integer(
		string="Liczba ponownych prób",
		default=3,
		help="Maksymalna liczba ponownych prób wysyłki"
	)
	
	retry_delay = fields.Integer(
		string="Opóźnienie między próbami (min)",
		default=5,
		help="Minuty pomiędzy kolejnymi próbami wysyłki"
	)
	
	notification_users = fields.Many2many(
		"res.users",
		string="Powiadom użytkowników",
		help="Kogo powiadomić o błędach wysyłki"
	)
	
	# -------------------------------------------------------------------------
	# 5. SZABLONY (opcjonalnie - jeśli provider ma domyślny szablon)
	# -------------------------------------------------------------------------
	default_template_id = fields.Many2one(
		"xml.export.template",
		string="Domyślny szablon",
		help="Szablon używany jeśli dokument nie wskazuje konkretnego"
	)
	
	allowed_template_ids = fields.Many2many(
		"xml.export.template",
		"provider_template_rel",
		"provider_id",
		"template_id",
		string="Dozwolone szablony",
		help="Które szablony mogą używać tego providera"
	)
	
	# -------------------------------------------------------------------------
	# 6. STATYSTYKI/MONITORING
	# -------------------------------------------------------------------------
	log_count = fields.Integer(
		compute="_compute_log_stats",
		string="Liczba logów"
	)

	def _compute_log_stats(self):
		"""Oblicza statystyki logów dla tego providera"""
		Log = self.env['communication.log']
		for provider in self:
			logs = Log.search([('provider_id', '=', provider.id)])
			
			provider.log_count = len(logs)
			
			success_logs = logs.filtered(lambda l: l.status == 'success')
			provider.success_count = len(success_logs)
			
			error_logs = logs.filtered(lambda l: l.status == 'error')
			provider.error_count = len(error_logs)
			
			if success_logs:
				provider.last_success_date = max(success_logs.mapped('send_date'))
			else:
				provider.last_success_date = False
	
	success_count = fields.Integer(
		compute="_compute_log_stats",
		string="Udane wysyłki"
	)
	
	error_count = fields.Integer(
		compute="_compute_log_stats",
		string="Błędy wysyłki"
	)
	
	last_success_date = fields.Datetime(
		compute="_compute_log_stats",
		string="Ostatnia udana wysyłka"
	)

	# -------------------------------------------------------------------------
	# SELECTION DLA FIELDS.Reference – DOSTĘPNE MODELE PLUGINÓW
	# -------------------------------------------------------------------------
	@api.depends('provider_type')
	def _compute_provider_model(self):
		"""Mapuje provider_type na nazwę modelu pluginu"""
		type_to_model = {
			'ksef': 'communication.provider.ksef',
			'localdir': 'communication.provider.localdir',
			# mapowanie dla innych typów
		}
		for record in self:
			record.provider_model = type_to_model.get(record.provider_type)
			if record.provider_model:
				#dynamic_config_name
				_logger.info(f"\n[SELECTION _compute_provider_model] record.provider_model = {record.provider_model}")
				for config in self.env[record.provider_model].search([('active','!=', False),('company_id', '=', record.company_id.id)]):
					_logger.info(f"\n[SELECTION _compute_provider_model] FOUND name = {config.name}")
					if release.version_info[0] == 18:
						# Kod dla Odoo 18
						_logger.info("\n[SELECTION] Wersja Odoo 18 – wykonuję ścieżkę A")
					elif release.version_info[0] == 17:
						# Kod dla Odoo 17
						_logger.info("\n[SELECTION] Wersja Odoo 17 – wykonuję ścieżkę B")

	@api.depends('provider_config_id', 'provider_model')
	def _compute_provider_config_name(self):
		for record in self:
			if record.provider_config_id and record.provider_model:
				try:
					config = self.env[record.provider_model].browse(record.provider_config_id)
					record.provider_config_name = config.name
				except:
					record.provider_config_name = "Błąd"
			else:
				record.provider_config_name = "Nie wybrano"
	
	
	# Wersja 2: Dynamiczne wyświetlanie w UI
	@api.onchange('provider_type')
	def _onchange_provider_type(self):
		"""Czyści konfigurację przy zmianie typu"""
		if self.provider_type and hasattr(self, '_origin'):
			# Sprawdź czy typ się zmienił
			if self._origin.provider_type != self.provider_type:
				self.provider_config_id = False
		
	# -------------------------------------------------------------------------
	# METODY
	# -------------------------------------------------------------------------

	# -------------------------------------------------------------------------
	# MAPOWANIE: provider_type -> model pluginu
	# -------------------------------------------------------------------------
	@api.model
	def _provider_model_map(self):
		"""
		Słownik mapujący typ providera na nazwę modelu pluginu.
		Pluginy mogą tę metodę rozszerzać przez _inherit (update słownika).
		"""
		return {
			"localdir": "communication.provider.localdir",
			"ksef": "communication.provider.ksef",
		}


	# -------------------------------------------------------------------------
	#  METODY WYMAGANE DO IMPLEMENTACJI W MODELACH PROVIDER.*
	# -------------------------------------------------------------------------
	def authenticate(self, **kwargs):
		"""
		Deleguje proces uwierzytelnienia do odpowiedniego pluginu.
		Wywołanie z zewnątrz: provider.authenticate(...)
		"""
		self.ensure_one()
		plugin = self._get_plugin_record()
		if not plugin:
			raise UserError(
				_(
					"Brak skonfigurowanego pluginu dla providera %s (typ %s). "
					"Ustaw pole 'Konfiguracja szczegółowa'."
				)
				% (self.display_name, self.provider_type)
			)

		if not hasattr(plugin, "authenticate"):
			# Dla providerów, które nie wymagają uwierzytelniania (np. LocalDir),
			# możesz albo przyjąć True, albo rzucić błąd – decyzja zależy od Ciebie.
			_logger.info(
				"Plugin %s (id=%s) dla providera %s nie implementuje authenticate() – przyjmuję brak uwierzytelniania.",
				plugin._name,
				plugin.id,
				self.display_name,
			)
			return True

		_logger.info(
			"Delegacja authenticate do pluginu %s (id=%s) dla providera %s",
			plugin._name,
			plugin.id,
			self.display_name,
		)
		return plugin.authenticate(**kwargs)

	# -------------------------------------------------------------------------
	# WYSZUKIWANIE KONKRETNEGO REKORDU PLUGINU
	# -------------------------------------------------------------------------
	def _get_plugin_record(self):
		"""
		Zwraca konkretny rekord pluginu dla providera.
		
		NOWA ARCHITEKTURA:
		1. provider_type → określa typ (ksef, localdir, ...)
		2. provider_model → obliczany model pluginu
		3. provider_config_id → konkretny rekord z tego modelu
		"""
		self.ensure_one()

		# 1. Sprawdź czy provider ma ustawiony typ
		if not self.provider_type:
			raise UserError(
				_("Provider %s nie ma ustawionego typu.") % self.display_name
			)

		# 2. Sprawdź czy obliczono model
		if not self.provider_model:
			# Powinno być obliczone, ale na wszelki wypadek
			model_map = {
				'ksef': 'communication.provider.ksef',
				'localdir': 'communication.provider.localdir',
			}
			model_name = model_map.get(self.provider_type)
			if not model_name:
				raise UserError(
					_("Nieznany typ providera: %s") % self.provider_type
				)
		else:
			model_name = self.provider_model

		# 3. Sprawdź czy wybrano konfigurację
		if not self.provider_config_id:
			raise UserError(
				_("Provider %s nie ma wybranej konfiguracji. Ustaw pole 'Konfiguracja'.")
				% self.display_name
			)

		# 4. Pobierz rekord pluginu
		try:
			plugin = self.env[model_name].browse(self.provider_config_id)
			
			# Sprawdź czy rekord istnieje
			if not plugin.exists():
				raise UserError(
					_("Wybrana konfiguracja (ID: %s) nie istnieje w modelu %s.")
					% (self.provider_config_id, model_name)
				)
			
			# Opcjonalnie: sprawdź czy plugin jest aktywny
			if hasattr(plugin, 'active') and not plugin.active:
				_logger.warning(
					"Plugin %s (id=%s) dla providera %s jest nieaktywny.",
					model_name, plugin.id, self.display_name
				)
			
			return plugin
			
		except Exception as e:
			_logger.error(
				"Błąd pobierania pluginu dla providera %s: %s",
				self.display_name, e
			)
			raise UserError(
				_("Błąd pobierania konfiguracji: %s") % str(e)
			)

	# -------------------------------------------------------------------------
	# PUBLICZNE API – DELEGACJA DO PLUGINÓW
	# -------------------------------------------------------------------------
	def provider_test(self):
		self.ensure_one()
		plugin = self._get_plugin_record()
		_logger.info(f'\nPUBLICZNE API – DELEGACJA DO PLUGINÓW\nplugin = {plugin}')
		if not plugin or (not hasattr(plugin, 'provider_test')):
			raise UserError(
				_(
					"Brak skonfigurowanego pluginu dla providera %s (typ %s). "
					"Ustaw pole 'Konfiguracja szczegółowa'."
				)
				% (self.display_name, self.provider_type)
			)
		
		return plugin.provider_test()

	def send_document(self, log):
		"""
		Deleguje wysyłkę dokumentu do odpowiedniego pluginu.
		Wywołanie z zewnątrz: provider.send_document(log)
		"""
		self.ensure_one()
		plugin = self._get_plugin_record()
		if not plugin:
			raise UserError(
				_(
					"Brak skonfigurowanego pluginu dla providera %s (typ %s). "
					"Ustaw pole 'Konfiguracja szczegółowa'."
				)
				% (self.display_name, self.provider_type)
			)

		_logger.info(
			"Delegacja send_document do pluginu %s (id=%s) dla providera %s",
			plugin._name,
			plugin.id,
			self.display_name,
		)
		return plugin.send_document( log)

	def get_status(self, log):
		"""
		Delegacja sprawdzenia statusu (np. UPO w KSeF) do pluginu.
		"""
		self.ensure_one()
		plugin = self._get_plugin_record()
		if not plugin:
			raise UserError(
				_(
					"Brak skonfigurowanego pluginu dla providera %s (typ %s). "
					"Ustaw pole 'Konfiguracja szczegółowa'."
				)
				% (self.display_name, self.provider_type)
			)

		_logger.info(
			"Delegacja get_status do pluginu %s (id=%s) dla providera %s",
			plugin._name,
			plugin.id,
			self.display_name,
		)
		return plugin.get_status(log)

	def fetch_documents(self, log):
		"""
		Pobranie dokumentu (np. faktury z kanału przychodzącego) – delegacja.
		"""
		self.ensure_one()
		plugin = self._get_plugin_record()
		if not plugin:
			raise UserError(
				_(
					"Brak skonfigurowanego pluginu dla providera %s (typ %s). "
					"Ustaw pole 'Konfiguracja szczegółowa'."
				)
				% (self.display_name, self.provider_type)
			)

		_logger.info(
			"Delegacja get_document do pluginu %s (id=%s) dla providera %s",
			plugin._name,
			plugin.id,
			self.display_name,
		)
		return plugin.fetch_documents( log)

	def search_documents(self, **kwargs):
		"""
		Wyszukiwanie dokumentów w zewnętrznym systemie – delegacja.
		"""
		self.ensure_one()
		plugin = self._get_plugin_record()
		if not plugin:
			raise UserError(
				_(
					"Brak skonfigurowanego pluginu dla providera %s (typ %s). "
					"Ustaw pole 'Konfiguracja szczegółowa'."
				)
				% (self.display_name, self.provider_type)
			)

		_logger.info(
			"Delegacja search_documents do pluginu %s (id=%s) dla providera %s",
			plugin._name,
			plugin.id,
			self.display_name,
		)
		return plugin.search_documents( **kwargs)


#EoF

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
""" @version	17.2.1
	@owner  Hadron for Business
	@author andrzej wiśniewski warp3r
	@date   2026.03.12
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

class CommunicationProviderConfigWizard(models.TransientModel):
	_name = 'communication.provider.config.wizard'
	_description = 'Wizard wyboru konfiguracji'

	provider_id = fields.Many2one(
		'communication.provider',
		string="Provider",
		required=False,
		ondelete='cascade'
	)

	selected_config_id = fields.Many2one(
		'communication.provider.config.wizard.list',
		string="Wybierz konfigurację",
		required=False,
		domain="[('provider_id', '=', provider_id)]"
	)

	def action_confirm(self):
		self.ensure_one()
		if not self.selected_config_id:
			return {
				'type': 'ir.actions.act_window_close',
				'warning': {'title': 'Błąd', 'message': 'Musisz wybrać konfigurację'}
			}

		original_id = self.selected_config_id.original_id
		self.provider_id.write({
			'provider_config_id': original_id
		})

		return {'type': 'ir.actions.act_window_close'}

class CommunicationProviderConfigWizardList(models.TransientModel):
	_name = 'communication.provider.config.wizard.list'
	_description = 'Lista konfiguracji do wyboru'

	original_id = fields.Integer(
		string="ID oryginalnego rekordu",
		required=True,
		help="ID rekordu w docelowym modelu"
	)

	name = fields.Char(
		string="Nazwa",
		required=True,
		help="Nazwa konfiguracji do wyświetlenia"
	)

	provider_id = fields.Many2one(
		'communication.provider',
		string="Provider",
		required=True,
		ondelete='cascade'
	)


class CommunicationProvider(models.Model):
	_inherit = 'communication.provider'  # lub _name jeśli tworzysz nowy model

	def action_open_config_wizard(self):
		self.ensure_one()

		# Wyczyść stare rekordy listy dla tego providera
		self.env['communication.provider.config.wizard.list'].search([
			('provider_id', '=', self.id)
		]).unlink()

		# Skopiuj rekordy z docelowego modelu
		target_model = self.provider_model
		if target_model and target_model in self.env:
			Model = self.env[target_model]
			for record in Model.search([('active', '!=', False)]):
				self.env['communication.provider.config.wizard.list'].create({
					'original_id': record.id,
					'name': record.name,
					'provider_id': self.id,
				})

		# Utwórz główny rekord wizarda
		wizard = self.env['communication.provider.config.wizard'].create({
			'provider_id': self.id,
		})

		# Otwórz wizarda
		return {
			'type': 'ir.actions.act_window',
			'name': 'Wybierz konfigurację',
			'res_model': 'communication.provider.config.wizard',
			'res_id': wizard.id,
			'view_mode': 'form',
			'target': 'new',
		}

#EoF

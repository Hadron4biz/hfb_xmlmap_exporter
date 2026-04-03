# -*- coding: utf-8 -*-
#################################################################################
#
# Odoo, Open ERP Source Management Solution
# Copyright (C) 17-26 Hadron for business sp. z o.o. (http://www.hadron.eu.com)
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
""" @version	16.0.1
	@owner  Hadron for Business
	@author andrzej wiśniewski warp3r
	@date   2026.03.10
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import re
import base64
import json
from odoo import release
import io
import uuid
from lxml import etree

import logging
_logger = logging.getLogger(__name__)

class JsonField(fields.Field):
	type = 'json'
	column_type = ('jsonb', 'jsonb')
	
	def convert_to_column(self, value, record, values=None, validate=True):
		if value is None:
			return None
		try:
			return json.dumps(value, ensure_ascii=False)
		except (TypeError, ValueError) as e:
			_logger.warning("Nie można zserializować do JSON: %s", e)
			return None
	
	def convert_to_cache(self, value, record, validate=True):
		if value is None or value == '':
			return {}
		if isinstance(value, str):
			try:
				return json.loads(value)
			except (ValueError, TypeError) as e:
				_logger.warning("Nie można zdeserializować JSON: %s", e)
				return {}
		return value

# Model testowy
class TestModel(models.Model):
	_name = 'test.model'
	_description = 'Test Model'
	
	name = fields.Char()
	json_field = fields.Json('pole JSON')
	#json_field = JsonField('pole JSON')
	jf = fields.Json('pole JS')

#EoF

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

from odoo.tests.common import TransactionCase
from odoo import fields
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import logging

_logger = logging.getLogger(__name__)

class TestKsefCrons(TransactionCase):
	
	def setUp(self):
		super(TestKsefCrons, self).setUp()
		
		# Przygotuj providera testowego
		self.provider_config = self.env['communication.provider.ksef'].create({
			'name': 'Test KSeF Config',
			'code': 'TEST_KSEF',
			'environment': 'test',
			'auth_type': 'jet_token',
			'jet_api_key': 'test_key',
			'jet_api_token': 'test_token',
			'company_nip': '1234567890',
			'jar_directory': '/tmp/test_jar',
		})
		
		self.provider = self.env['communication.provider'].create({
			'name': 'Test KSeF Provider',
			'code': 'TEST_KSEF_PROV',
			'provider_type': 'ksef',
			'provider_config_id': self.provider_config.id,
			'provider_model': 'communication.provider.ksef',
		})
		
		# Przygotuj kontakt alarmowy
		self.alert_contact = self.env['res.partner'].create({
			'name': 'Test Alert Contact',
			'email': 'test@example.com',
		})
		self.provider_config.alert_contact_id = self.alert_contact
		
	def test_01_monitor_failures_stuck_logs(self):
		"""Test czy cron znajduje zablokowane logi"""
		# Utwórz zablokowany log
		stuck = self.env['communication.log'].create({
			'provider_id': self.provider.id,
			'direction': 'export',
			'ksef_operation': 'send_invoice',
			'is_processing': True,
			'processing_lock_until': fields.Datetime.now() - timedelta(minutes=31),
			'write_date': fields.Datetime.now() - timedelta(minutes=31),
		})
		
		# Uruchom cron
		with patch.object(type(self.env['communication.log']), '_notify_ksef_failure') as mock_notify:
			self.env['communication.log'].cron_ksef_monitor_failures()
			
			# Sprawdź czy powiadomienie zostało wysłane
			mock_notify.assert_called_once()
			args, kwargs = mock_notify.call_args
			self.assertIn(stuck, args[1])  # logs powinny zawierać stuck
			
	def test_02_daily_report_stats(self):
		"""Test czy raport dzienny poprawnie liczy statystyki"""
		# Utwórz logi z ostatnich 24h
		now = fields.Datetime.now()
		
		for i in range(5):
			self.env['communication.log'].create({
				'provider_id': self.provider.id,
				'direction': 'export',
				'ksef_operation': 'send_invoice',
				'ksef_status': 'success',
				'create_date': now - timedelta(hours=i),
			})
		
		# Uruchom cron
		with patch.object(type(self.env['communication.log']), '_send_ksef_daily_report') as mock_report:
			self.env['communication.log'].cron_ksef_daily_report()
			
			# Sprawdź czy raport został wysłany
			mock_report.assert_called_once()
			args, kwargs = mock_report.call_args
			provider, stats, logs = args
			
			self.assertEqual(stats['sent'], 5)
			
	def test_03_environment_check_healthy(self):
		"""Test sprawdzania środowiska - healthy"""
		# Mockuj odpowiedź API
		mock_response = MagicMock()
		mock_response.status_code = 200
		mock_response.json.return_value = {'status': 'Healthy'}
		
		with patch('requests.get', return_value=mock_response):
			with patch.object(type(self.env['communication.log']), '_notify_ksef_environment_alert') as mock_alert:
				self.env['communication.log'].cron_ksef_environment_check()
				
				# Nie powinno być alertu
				mock_alert.assert_not_called()
	
	def test_04_environment_check_unhealthy(self):
		"""Test sprawdzania środowiska - unhealthy"""
		mock_response = MagicMock()
		mock_response.status_code = 503
		mock_response.reason = "Service Unavailable"
		
		with patch('requests.get', return_value=mock_response):
			with patch.object(type(self.env['communication.log']), '_notify_ksef_environment_alert') as mock_alert:
				self.env['communication.log'].cron_ksef_environment_check()
				
				# Powinien być alert
				mock_alert.assert_called_once()

#EoF

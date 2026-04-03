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
""" @version 16.1.3
    @owner  Hadron for Business
    @author andrzej wiśniewski warp3r
    @date   2025.10.15
"""
#################################################################################
#   Provider LocalDir – zapis/odczyt plików XML/JSON na lokalnym dysku
#   W pełni zgodny z bazowym modelem communication.provider
#################################################################################
import os
import base64
import json
import logging
import uuid
from datetime import datetime
import fnmatch

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# rozbudowa
# W communication_log.py - rozszerzamy model o nowe metody
class CommunicationLog(models.Model):
	_inherit = "communication.log"
	
	# -------------------------------------------------------------------------
	# AKCJE SPECJALNE DLA LOCALDIR
	# -------------------------------------------------------------------------
	
	def action_send_localdir(self):
		"""Specjalna akcja dla wysyłki LocalDir"""
		self.ensure_one()
		
		# Walidacja
		if not self.provider_id:
			raise UserError("Log nie ma przypisanego providera")
		
		if self.provider_id.provider_type != 'localdir':
			raise UserError("Ta akcja jest tylko dla providerów typu 'localdir'")
		
		if not self.file_data:
			raise UserError("Brak pliku do wysyłki")
		
		if self.state not in ['generated', 'queued', 'draft']:
			raise UserError(
				f"Dokument musi być w stanie 'generated', 'queued' lub 'draft'. "
				f"Obecny: {self.state}"
			)
		
		# Ustaw operację jako wysyłkę
		self.operation = "send"
		
		# Wyślij przez providera
		try:
			success = self.provider_id.send_document(self)
			
			if success:
				# Powiadomienie o sukcesie
				return {
					'type': 'ir.actions.client',
					'tag': 'display_notification',
					'params': {
						'title': 'Wysyłka LocalDir',
						'message': f'Dokument wysłany do {self.external_id or "katalogu LocalDir"}',
						'type': 'success',
						'sticky': False,
					}
				}
			else:
				raise UserError("Wysyłka nie powiodła się - sprawdź szczegóły w logu")
				
		except Exception as e:
			_logger.error(f"Błąd wysyłki LocalDir dla logu {self.id}: {e}")
			raise UserError(f"Błąd wysyłki: {str(e)}")
	
	def action_check_localdir_status(self):
		"""Sprawdza status dokumentu w LocalDir"""
		self.ensure_one()
		
		# Walidacja
		if not self.provider_id:
			raise UserError("Log nie ma przypisanego providera")
		
		if self.provider_id.provider_type != 'localdir':
			raise UserError("Ta akcja jest tylko dla providerów typu 'localdir'")
		
		# Sprawdź status przez providera
		try:
			success = self.provider_id.get_status(self)
			
			if success and self.payload_response:
				# Parsuj odpowiedź
				import json
				try:
					status_info = json.loads(self.payload_response)
					message = f"Status: {status_info.get('status', 'unknown')}"
					
					if status_info.get('file_exists'):
						message += f"\nPlik istnieje: {status_info.get('file_path')}"
						message += f"\nRozmiar: {status_info.get('file_size', 0)} bajtów"
				except:
					message = "Status sprawdzony"
				
				return {
					'type': 'ir.actions.client',
					'tag': 'display_notification',
					'params': {
						'title': 'Status LocalDir',
						'message': message,
						'type': 'info',
						'sticky': True,
					}
				}
			else:
				raise UserError("Nie udało się sprawdzić statusu")
				
		except Exception as e:
			_logger.error(f"Błąd sprawdzania statusu LocalDir dla logu {self.id}: {e}")
			raise UserError(f"Błąd sprawdzania statusu: {str(e)}")
	
	def action_import_from_localdir(self):
		"""
		Ręczny import z LocalDir.
		Używane gdy provider ma ustawiony input_path.
		"""
		self.ensure_one()
		
		if not self.provider_id:
			raise UserError("Log nie ma przypisanego providera")
		
		if self.provider_id.provider_type != 'localdir':
			raise UserError("Ta akcja jest tylko dla providerów typu 'localdir'")
		
		# Pobierz plugin LocalDir
		plugin = self.provider_id._get_plugin_record()
		if not plugin:
			raise UserError("Brak konfiguracji LocalDir dla tego providera")
		
		# Sprawdź czy ma input_path
		if not hasattr(plugin, 'input_path') or not plugin.input_path:
			raise UserError("Ten provider LocalDir nie ma skonfigurowanego katalogu importu")
		
		# Importuj dokumenty
		imported_logs = plugin.fetch_documents(channel=None)
		
		return {
			'type': 'ir.actions.client',
			'tag': 'display_notification',
			'params': {
				'title': 'Import z LocalDir',
				'message': f'Zaimportowano {len(imported_logs)} dokumentów',
				'type': 'success',
				'sticky': False,
			}
		}


# communication_provider_localdir.py
class CommunicationProviderLocalDir(models.Model):
	_name = "communication.provider.localdir"
	_description = "Local Directory Provider"
	
	# -------------------------------------------------------------------------
	# IDENTYFIKACJA
	# -------------------------------------------------------------------------
	name = fields.Char(string="Nazwa konfiguracji", required=True)
	code = fields.Char(string="Kod", required=True)
	active = fields.Boolean(string="Aktywny", default=True)
	
	# -------------------------------------------------------------------------
	# KONFIGURACJA ŚCIEŻEK
	# -------------------------------------------------------------------------
	output_path = fields.Char(
		string="Ścieżka wyjściowa",
		required=True,
		help="Katalog, do którego zapisywane będą dokumenty eksportowane"
	)
	
	input_path = fields.Char(
		string="Ścieżka wejściowa",
		help="Katalog, z którego importowane będą dokumenty. "
			 "Puste = tylko eksport."
	)
	
	# -------------------------------------------------------------------------
	# OPCJE ZAPISU
	# -------------------------------------------------------------------------
	file_naming = fields.Selection([
		('original', 'Oryginalna nazwa z logu'),
		('timestamp', 'Znacznik czasowy'),
		('uuid', 'Unikalny UUID'),
		('document_id', 'ID dokumentu'),
	],
		string="Nazewnictwo plików",
		default='original',
		help="Jak nazywać zapisywane pliki"
	)
	
	subdirectory_format = fields.Char(
		string="Format podkatalogów",
		default="%Y/%m/%d",
		help="Format podkatalogów np. %Y/%m/%d → 2023/12/08"
	)
	
	overwrite_existing = fields.Boolean(
		string="Nadpisuj istniejące",
		default=False,
		help="Nadpisz plik jeśli już istnieje"
	)
	
	auto_create_dirs = fields.Boolean(
		string="Twórz katalogi automatycznie",
		default=True
	)
	
	# -------------------------------------------------------------------------
	# OPCJE IMPORTU
	# -------------------------------------------------------------------------
	import_pattern = fields.Char(
		string="Wzorzec importu",
		default="*.xml",
		help="Wzorzec plików do importu, np. *.xml lub faktura_*.xml"
	)
	
	delete_after_import = fields.Boolean(
		string="Usuń po imporcie",
		default=False,
		help="Usuń plik po pomyślnym zaimportowaniu"
	)
	
	# -------------------------------------------------------------------------
	# METODY PLUGINU (WYMAGANE!)
	# -------------------------------------------------------------------------
	
	def send_document(self, log):
		"""
		Wysyła dokument (zapisuje do katalogu).
		
		Args:
			log: communication.log z danymi do wysłania
			
		Returns:
			bool: True jeśli sukces, False jeśli błąd
		"""
		_logger.info(f"[LocalDir] Wysyłka logu {log.id} do {self.output_path}")
		
		try:
			# 1. Sprawdź czy są dane do wysłania
			if not log.file_data:
				_logger.error(f"[LocalDir] Log {log.id} nie ma danych pliku")
				log.mark_error("Brak danych pliku do wysłania", operation="send")
				return False
			
			# 2. Przygotuj ścieżkę
			file_path = self._prepare_file_path(log)
			
			# 3. Zapis pliku
			success = self._save_file(log.file_data, file_path)
			
			if success:
				# 4. Aktualizuj log
				log.mark_sent(external_id=file_path)
				log.payload_response = f"Zapisano do: {file_path}"
				_logger.info(f"[LocalDir] Zapisano plik: {file_path}")
				return True
			else:
				log.mark_error(f"Błąd zapisu do {file_path}", operation="send")
				return False
				
		except Exception as e:
			_logger.error(f"[LocalDir] Błąd wysyłki logu {log.id}: {e}")
			log.mark_error(f"Błąd wysyłki LocalDir: {str(e)}", operation="send")
			return False
	
	def authenticate(self, **kwargs):
		"""
		LocalDir nie wymaga autoryzacji.
		Zwraca zawsze True.
		"""
		_logger.info(f"[LocalDir] authenticate (brak autoryzacji)")
		return True
	
	def get_status(self, log):
		"""
		Sprawdza status dokumentu w LocalDir.
		Weryfikuje czy plik istnieje w systemie plików.
		"""
		_logger.info(f"[LocalDir] Sprawdzanie statusu dla logu {log.id}")
		
		try:
			if not log.external_id:
				# Brak ścieżki - dokument nie został wysłany
				status_info = {
					'status': 'not_sent',
					'message': 'Dokument nie został wysłany',
					'timestamp': fields.Datetime.now().isoformat(),
				}
			else:
				# Sprawdź czy plik istnieje
				file_path = log.external_id
				file_exists = os.path.exists(file_path)
				
				status_info = {
					'status': 'exists' if file_exists else 'missing',
					'file_path': file_path,
					'file_exists': file_exists,
					'timestamp': fields.Datetime.now().isoformat(),
				}
				
				if file_exists:
					# Dodaj informacje o pliku
					stat_info = os.stat(file_path)
					status_info.update({
						'file_size': stat_info.st_size,
						'modified_date': datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
					})
			
			# Aktualizuj log
			log.mark_status_checked(json.dumps(status_info))
			return True
			
		except Exception as e:
			_logger.error(f"[LocalDir] Błąd sprawdzania statusu: {e}")
			log.mark_error(f"Błąd sprawdzania statusu: {str(e)}", operation="status")
			return False
	
	def fetch_documents(self, channel):
		"""
		Importuje dokumenty z katalogu wejściowego.
		
		Args:
			channel: communication.channel (jeśli używany) lub None
			
		Returns:
			list: Lista utworzonych communication.log
		"""
		if not self.input_path:
			_logger.info("[LocalDir] Brak input_path - pomijam import")
			return []
		
		_logger.info(f"[LocalDir] Import z: {self.input_path}")
		
		if not os.path.exists(self.input_path):
			_logger.warning(f"[LocalDir] Katalog nie istnieje: {self.input_path}")
			return []
		
		imported_logs = []
		
		try:
			# Znajdź pliki zgodne ze wzorcem
			pattern = self.import_pattern
			for filename in fnmatch.filter(os.listdir(self.input_path), pattern):
				file_path = os.path.join(self.input_path, filename)
				
				if not os.path.isfile(file_path):
					continue
				
				# Importuj plik
				log = self._import_file(file_path, channel)
				if log:
					imported_logs.append(log)
					
					# Usuń plik jeśli ustawione
					if self.delete_after_import:
						os.remove(file_path)
						_logger.info(f"[LocalDir] Usunięto po imporcie: {filename}")
		
		except Exception as e:
			_logger.error(f"[LocalDir] Błąd importu: {e}")
		
		return imported_logs
	
	def provider_test(self):
		"""Testuje konfigurację LocalDir"""
		_logger.info(f"[LocalDir] Test konfiguracji: {self.name}")
		
		test_results = []
		
		# 1. Test ścieżki wyjściowej
		if self.output_path:
			if os.path.exists(self.output_path):
				test_results.append(("Ścieżka wyjściowa", "OK", self.output_path))
			elif self.auto_create_dirs:
				test_results.append(("Ścieżka wyjściowa", "Utworzona przy zapisie", self.output_path))
			else:
				test_results.append(("Ścieżka wyjściowa", "BŁĄD - nie istnieje", self.output_path))
		
		# 2. Test ścieżki wejściowej
		if self.input_path:
			if os.path.exists(self.input_path):
				test_results.append(("Ścieżka wejściowa", "OK", self.input_path))
			else:
				test_results.append(("Ścieżka wejściowa", "BŁĄD - nie istnieje", self.input_path))
		
		# 3. Test zapisu tymczasowego pliku
		try:
			test_content = b"Test LocalDir plugin"
			test_path = os.path.join(self.output_path or "/tmp", f"test_{uuid.uuid4().hex[:8]}.txt")
			
			with open(test_path, 'wb') as f:
				f.write(test_content)
			
			if os.path.exists(test_path):
				os.remove(test_path)
				test_results.append(("Zapis pliku", "OK", "Możliwość zapisu"))
			else:
				test_results.append(("Zapis pliku", "BŁĄD", "Nie można zapisać"))
				
		except Exception as e:
			test_results.append(("Zapis pliku", "BŁĄD", str(e)))
		
		# Formatuj wynik
		result_text = "\n".join([f"• {name}: {status} ({info})" for name, status, info in test_results])
		
		return {
			'type': 'ir.actions.client',
			'tag': 'display_notification',
			'params': {
				'title': f'Test LocalDir: {self.name}',
				'message': result_text,
				'type': 'success' if all(t[1] == 'OK' for t in test_results) else 'warning',
				'sticky': True,
			}
		}
	
	# -------------------------------------------------------------------------
	# METODY POMOCNICZE (PRYWATNE)
	# -------------------------------------------------------------------------
	
	def _prepare_file_path(self, log):
		"""Przygotowuje pełną ścieżkę do pliku"""
		# 1. Ustal nazwę pliku
		if self.file_naming == 'original' and log.file_name:
			filename = log.file_name
		elif self.file_naming == 'timestamp':
			timestamp = fields.Datetime.now().strftime('%Y%m%d_%H%M%S')
			filename = f"{timestamp}_{log.id}.xml"
		elif self.file_naming == 'uuid':
			filename = f"{uuid.uuid4()}.xml"
		elif self.file_naming == 'document_id':
			filename = f"doc_{log.document_id or log.id}.xml"
		else:
			filename = f"document_{log.id}.xml"
		
		# 2. Ustal podkatalogi
		base_path = self.output_path
		if self.subdirectory_format:
			subdir = fields.Datetime.now().strftime(self.subdirectory_format)
			base_path = os.path.join(base_path, subdir)
		
		# 3. Pełna ścieżka
		full_path = os.path.join(base_path, filename)
		
		# 4. Utwórz katalogi jeśli trzeba
		if self.auto_create_dirs:
			os.makedirs(os.path.dirname(full_path), exist_ok=True)
		
		return full_path
	
	def _save_file(self, file_data, file_path):
		"""Zapisuje dane do pliku"""
		try:
			# Sprawdź czy plik już istnieje
			if os.path.exists(file_path) and not self.overwrite_existing:
				_logger.warning(f"[LocalDir] Plik już istnieje: {file_path}")
				# Możesz rzucić wyjątek lub nadać inną nazwę
				counter = 1
				base, ext = os.path.splitext(file_path)
				while os.path.exists(file_path):
					file_path = f"{base}_{counter}{ext}"
					counter += 1
			
			# Zapis danych
			with open(file_path, 'wb') as f:
				f.write(base64.b64decode(file_data))
			
			return True
			
		except Exception as e:
			_logger.error(f"[LocalDir] Błąd zapisu pliku {file_path}: {e}")
			return False
	
	def _import_file(self, file_path, channel):
		"""Importuje pojedynczy plik"""
		try:
			with open(file_path, 'rb') as f:
				file_content = f.read()
			
			# Utwórz log importu
			log_vals = {
				'direction': 'import',
				'operation': 'fetch',
				'state': 'received',
				'status': 'success',
				'provider_id': self.id,  # To się może różnić w zależności od architektury
				'file_name': os.path.basename(file_path),
				'file_data': base64.b64encode(file_content),
				'receive_date': fields.Datetime.now(),
			}
			
			log = self.env['communication.log'].create(log_vals)
			
			_logger.info(f"[LocalDir] Zaimportowano: {file_path} jako log {log.id}")
			return log
			
		except Exception as e:
			_logger.error(f"[LocalDir] Błąd importu pliku {file_path}: {e}")
			return None

#EoF

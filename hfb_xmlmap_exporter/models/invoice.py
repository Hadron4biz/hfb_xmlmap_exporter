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
"""@version 17.2.3
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
import base64
from markupsafe import Markup, escape

import logging
_logger = logging.getLogger(__name__)


"""
Faktura (account.move) 
	→ Szablon (xml.export.template) 
	→ generate_preview_xml() [walidacja]
	→ generate_xml() [eksport]
	→ Załącznik XML
"""
class AccountMove(models.Model):
	_inherit = "account.move"

	validation_log_ids = fields.One2many(
		"xml.validation.log",
		"move_id",
		string="Historia walidacji XML",
		readonly=True,
		copy=False,
	)

	# 🔹 Powiązanie z szablonem eksportu XML (np. KSeF / PEPPOL)
	xml_export_template_id = fields.Many2one(
		"xml.export.template",
		string="Szablon eksportu XML",
		help="Określa schemat i mapowanie eksportu XML dla tej faktury.",
		tracking=True,
		copy=False,
	)

	# 🔹 Wynik ostatniej walidacji (status)
	xsd_validation_state = fields.Selection(
		[
			("none", "Niezweryfikowano"),
			("valid", "Poprawny wg XSD"),
			("invalid", "Błędy walidacji"),
		],
		string="Stan walidacji XSD",
		default="none",
		tracking=True,
		copy=False,
	)

	# 🔹 Obsługa Logu Komunikacji
	log_ids = fields.One2many(
		"communication.log",
		compute="_compute_log_ids",
		string="Logi komunikacji",
		copy=False,
	)

	log_count = fields.Integer(
		compute="_compute_log_ids",
		string="Ilość logów",
		copy=False,
	)

	# 🔹 Obliczenie rekordów
	def _compute_log_ids(self):
		for move in self:
			logs = self.env["communication.log"].search([
				("document_model", "=", "account.move"),
				("document_id", "=", move.id)
			])
			move.log_ids = logs
			move.log_count = len(logs)

	# 🔹 Wyświetlenie listy rekordów
	def action_open_logs(self):
		self.ensure_one()
		return {
			"type": "ir.actions.act_window",
			"name": "Logi komunikacji",
			"res_model": "communication.log",
			"view_mode": "list,form",
			"domain": [
				("document_model", "=", "account.move"),
				("document_id", "=", self.id)
			],
			"context": {"default_document_model": "account.move",
						"default_document_id": self.id},
		}

	########################################################################################################
	# pomocnicze
	def _parse_xsd_errors_with_schema(self, raw_errors, schema_doc, xml_doc):
		"""
		Parsuje błędy XSD korzystając z informacji zawartych w samej schemie.
		
		Args:
			raw_errors (list): Lista surowych komunikatów błędów
			schema_doc (etree._Element): Drzewo schemy XSD
			xml_doc (etree._Element): Drzewo XML dokumentu
		
		Returns:
			list: Lista słowników z czytelnymi komunikatami błędów
		"""
		error_details = []
		namespace_map = {
			'xs': 'http://www.w3.org/2001/XMLSchema',
			'xsd': 'http://www.w3.org/2001/XMLSchema'
		}
		
		# 🔹 Zbuduj mapę elementów i ich opisów z schemy
		element_docs = {}
		for elem in schema_doc.xpath('//xs:element', namespaces=namespace_map):
			elem_name = elem.get('name')
			if elem_name:
				# Szukaj dokumentacji w annotation/documentation
				doc = elem.xpath('xs:annotation/xs:documentation', namespaces=namespace_map)
				if doc and doc[0].text:
					element_docs[elem_name] = doc[0].text.strip()
		
		for error in raw_errors:
			error_detail = {
				'raw_error': error,
				'element': 'Nieznany element',
				'user_message': self._create_user_friendly_error(error, element_docs),
				'field_name': None,
			}
			
			try:
				# 🔹 Wyodrębnij nazwę elementu
				import re
				elem_match = re.search(r"Element '([^']+)':", error)
				if elem_match:
					full_elem_name = elem_match.group(1)
					# Usuń namespace dla czytelności
					elem_name = full_elem_name.split('}')[-1] if '}' in full_elem_name else full_elem_name
					error_detail['element'] = elem_name
					
					# 🔹 Pobierz opis pola z schemy jeśli istnieje
					if elem_name in element_docs:
						error_detail['field_description'] = element_docs[elem_name]
						error_detail['field_name'] = f"{elem_name} ({element_docs[elem_name]})"
					else:
						error_detail['field_name'] = elem_name
					
			except Exception as e:
				_logger.warning(f"Błąd podczas parsowania błędu XSD: {e}")
			
			error_details.append(error_detail)
		
		return error_details

	def _create_user_friendly_error(self, error_msg, element_docs):
		"""
		Tworzy czytelny dla użytkownika komunikat błędu.
		"""
		import re
		
		# 🔹 Wyodrębnij podstawowe informacje
		elem_match = re.search(r"Element '([^']+)':", error_msg)
		value_match = re.search(r"value '([^']+)'", error_msg)
		pattern_match = re.search(r"pattern '([^']+)'", error_msg)
		type_match = re.search(r"atomic type '([^']+)'", error_msg)
		
		elem_name = "Nieznane pole"
		if elem_match:
			full_name = elem_match.group(1)
			elem_name = full_name.split('}')[-1] if '}' in full_name else full_name
		
		# 🔹 Pobierz opis pola
		field_desc = element_docs.get(elem_name, "")
		field_display = f"{elem_name} ({field_desc})" if field_desc else elem_name
		
		# 🔹 W zależności od typu błędu
		if "SCHEMAV_CVC_PATTERN_VALID" in error_msg:
			current_value = value_match.group(1) if value_match else "(brak wartości)"
			pattern = pattern_match.group(1) if pattern_match else ""
			
			# 🔹 Specjalne przypadki dla znanych pól
			if elem_name == "NIP":
				if not current_value.isdigit():
					return f"Pole {field_display}: '{current_value}' zawiera nieprawidłowe znaki. NIP musi składać się wyłącznie z cyfr."
				elif len(current_value) != 10:
					return f"Pole {field_display}: '{current_value}' ma nieprawidłową długość. NIP musi mieć dokładnie 10 cyfr."
				else:
					return f"Pole {field_display}: '{current_value}' ma nieprawidłowy format NIP. Sprawdź poprawność numeru."
			
			# 🔹 Dla innych pól numerycznych
			elif "P_" in elem_name or "V_" in elem_name:
				if pattern and '\\d' in pattern:
					return f"Pole {field_display}: '{current_value}' musi być liczbą."
			
			return f"Pole {field_display}: Wartość '{current_value}' ma nieprawidłowy format."
		
		elif "SCHEMAV_CVC_DATATYPE_VALID" in error_msg:
			current_value = value_match.group(1) if value_match else "(puste)"
			data_type = type_match.group(1) if type_match else ""
			type_name = data_type.split('}')[-1] if '}' in data_type else data_type
			
			# 🔹 Dla typów kwotowych
			if type_name == "TKwotowy":
				if not current_value or current_value == "(puste)":
					return f"Pole {field_display}: Brak wartości. Wprowadź kwotę (np. 100.00)."
				elif not re.match(r'^-?\d+(\.\d{1,2})?$', str(current_value)):
					return f"Pole {field_display}: '{current_value}' nie jest poprawną kwotą. Wprowadź liczbę z maksymalnie 2 miejscami po przecinku."
			
			# 🔹 Dla typów liczbowych
			elif "Liczbowy" in type_name:
				if not re.match(r'^-?\d+$', str(current_value)):
					return f"Pole {field_display}: '{current_value}' nie jest liczbą całkowitą."
			
			return f"Pole {field_display}: Wartość '{current_value}' ma nieprawidłowy typ danych."
		
		elif "SCHEMAV_CVC_MINLENGTH_VALID" in error_msg:
			return f"Pole {field_display}: Wartość jest zbyt krótka. Sprawdź minimalną długość."
		
		elif "SCHEMAV_CVC_MAXLENGTH_VALID" in error_msg:
			return f"Pole {field_display}: Wartość jest zbyt długa. Sprawdź maksymalną długość."
		
		# 🔹 Domyślny komunikat
		if elem_match:
			return f"Pole {field_display}: Nieprawidłowa wartość."
		
		return "Wystąpił błąd walidacji danych."

	# ########################################################################
	def action_validate_template(self):
		"""
		Walidacja danych faktury względem szablonu XML.
		Jeśli szablon zawiera schemę XSD — wykonuje walidację XSD.
		W przeciwnym wypadku — walidację logicznej struktury węzłów (bez XSD).
		"""
		self.ensure_one()
		template = self.xml_export_template_id

		if not template:
			raise UserError(_("Brak przypisanego szablonu eksportu XML do tej faktury."))

		# 🔹 Tryb 1: Walidacja logiczna (brak XSD)
		if not template.xsd_attachment_id:
			_logger.info(f"🧩 Walidacja logiczna faktury {self.name} dla szablonu {template.name}")
			return self._validate_structure(template)

		# 🔹 Tryb 2: Walidacja względem XSD
		_logger.info(f"🧩 Walidacja faktury {self.name} względem schemy XSD z szablonu {template.name}")

		try:
			xml_bytes = template.generate_xml(self, in_memory=True)
			if not xml_bytes:
				raise UserError(_("Nie udało się wygenerować pliku XML z szablonu."))
		except Exception as e:
			_logger.exception("❌ Błąd podczas generacji XML")
			raise UserError(_("Błąd podczas generowania XML: %s") % str(e))

		try:
			# Pobierz zawartość XSD
			xsd_content = base64.b64decode(template.xsd_attachment_id.datas)
			schema_doc = etree.XML(xsd_content)
			xml_doc = etree.XML(xml_bytes)
			schema = etree.XMLSchema(schema_doc)
		except Exception as e:
			_logger.exception("❌ Błąd inicjalizacji schemy XSD")
			raise UserError(_("Nie można wczytać schemy XSD: %s") % str(e))

		# 🔹 Przetwarzanie błędów z użyciem informacji ze schemy
		user_messages = []
		if schema.validate(xml_doc):
			self.xsd_validation_state = "valid"
			msg = _("✅ Dokument spełnia wymagania schemy XSD.")
			color = "success"
			_logger.info(f"✅ Faktura {self.name} poprawna wg schemy XSD.")
			state = "valid"
		else:
			self.xsd_validation_state = "invalid"
			raw_errors = [str(e) for e in schema.error_log]
			
			# 🔹 Parsuj błędy z użyciem informacji ze schemy
			error_details = self._parse_xsd_errors_with_schema(raw_errors, schema_doc, xml_doc)
			
			# 🔹 Zbierz tylko czytelne komunikaty
			for error in error_details[:10]:  # Ogranicz do 10 pierwszych błędów
				if error.get('user_message'):
					user_messages.append(error['user_message'])
			
			# 🔹 Formatuj ostateczny komunikat
			if user_messages:
				error_list = "\n".join([f"• {msg}" for msg in user_messages])
				msg = _("❌ Znaleziono błędy w danych:\n\n%s") % error_list
			else:
				# Fallback - pokaż oryginalne błędy
				error_list = "\n".join([f"• {e}" for e in raw_errors[:5]])
				msg = _("❌ Znaleziono błędy walidacji:\n\n%s") % error_list
			
			color = "danger"
			_logger.warning(f"⚠️  Faktura {self.name} nie spełnia wymagań XSD, błędy: {len(raw_errors)}")
			state = "invalid"

		if xml_bytes:
			_logger.warning("❌❌❌  źródło XML:\n%s", xml_bytes.decode("utf-8"))

		# Zapisz log walidacji
		try:
			self.env["xml.validation.log"].sudo().create({
				"move_id": self.id,
				"template_id": template.id,
				"state": state,
				"validation_date": fields.Datetime.now(),
				"user_id": self.env.user.id,
				"error_log": "\n".join(user_messages[:50]) if user_messages else "",
				"xml_snapshot": xml_bytes,
				'company_id': self.company_id.id,
			})
		except Exception as e:
			_logger.warning(f"⚠️  Nie udało się zapisać logu walidacji: {e}")


		return {
			"type": "ir.actions.act_window",
			"res_model": "account.move",
			"res_id": self.id,
			"view_mode": "form",
			"target": "current",
			"tag": "display_notification",
			"params": {
				"title": _("Weryfikacja XSD"),
				"message": msg,
				"type": color,
				"sticky": True,
				"exec_reload": True,
			},
		}

		return {
			"type": "ir.actions.act_window",
			"res_model": "account.move",
			"res_id": self.id,
			"view_mode": "form",
			"target": "current",
		}

		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"title": _("Weryfikacja XSD"),
				"message": msg,
				"type": color,
				"sticky": True,
				"exec_reload": True,
			},
		}

	########################################################################################################

	def _validate_structure(self, template):
		"""
		Walidacja struktury szablonu XML bez użycia XSD.
		Sprawdza kompletność definicji węzłów i powiązania z polami Odoo.
		"""
		self.ensure_one()
		missing = []

		def _check_node(node):
			# Sprawdź czy node ma źródło danych jeśli nie jest stałą lub none
			if node.value_source not in ("none", "constant"):
				if not node.src_rel_path and not node.value_expr:
					missing.append(f"{node.name} — brak źródła danych (src_rel_path lub value_expr)")

			# Sprawdź konfigurację pętli
			if node.loop_mode != "none":
				if node.loop_mode in ["one2many", "many2many"] and not node.loop_rel_field_id:
					missing.append(f"{node.name} — brak loop_rel_field_id dla pętli {node.loop_mode}")
				elif node.loop_mode == "domain" and (not node.loop_model_id or not node.loop_domain):
					missing.append(f"{node.name} — brak loop_model_id lub loop_domain dla pętli domain")

			# Sprawdź dzieci
			children = template.node_ids.filtered(lambda c: c.parent_id.id == node.id)
			for child in children:
				_check_node(child)

		# Sprawdź root nodes
		root_nodes = template.node_ids.filtered(lambda n: not n.parent_id)
		if not root_nodes:
			missing.append("Brak węzła głównego (root node)")

		for root in root_nodes:
			_check_node(root)

		if missing:
			msg = _("❌ Wykryto braki w definicji szablonu XML:\n") + "\n".join(f"• {m}" for m in missing)
			color = "danger"
			state = "invalid"
			_logger.warning(f"⚠️ Walidacja logiczna: {len(missing)} braków w szablonie {template.name}")
		else:
			msg = _("✅ Szablon XML jest logicznie kompletny (bez XSD).")
			color = "success"
			state = "valid"
			_logger.info(f"✅ Walidacja logiczna szablonu {template.name} zakończona pomyślnie.")

		self.xsd_validation_state = state

		# Zapisz log walidacji
		try:
			self.env["xml.validation.log"].sudo().create({
				"move_id": self.id,
				"template_id": template.id,
				"state": state,
				"validation_date": fields.Datetime.now(),
				"user_id": self.env.user.id,
				"error_log": "\n".join(missing[:50]),
				'company_id': self.company_id.id,
			})
		except Exception as e:
			_logger.warning(f"⚠️ Nie udało się zapisać logu walidacji logicznej: {e}")

		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"title": _("Weryfikacja struktury XML"),
				"message": msg,
				"type": color,
				"sticky": True,  # Zmienione na True
			},
		}

	def action_export_xml(self):
		"""
		Eksportuje bieżącą fakturę do XML na podstawie przypisanego szablonu
		`xml.export.template` oraz przekazuje wynik do systemu komunikacji
		(`communication.log`) w celu dalszego przetwarzania / wysyłki
		(np. do KSeF).

		Przebieg operacji:
		1) Weryfikacja konfiguracji:
		   - sprawdza, czy do faktury przypisany jest szablon XML,
		   - sprawdza, czy szablon ma przypisanego provider'a.

		2) Generowanie XML:
		   - wywołuje `template.generate_xml(self, in_memory=True)`,
		   - XML jest generowany w pamięci (bez zapisu do pliku tymczasowego),
		   - w przypadku błędu generowania rzucany jest `UserError`.

		3) Rejestracja komunikacji:
		   - tworzony jest rekord `communication.log` z kierunkiem `export`
			 i stanem początkowym `generated`,
		   - XML zapisywany jest w logu w postaci base64,
		   - log zawiera pełne powiązanie z dokumentem źródłowym
			 (`account.move`) oraz użytym szablonem i providerem.

		4) Kolejkowanie do wysyłki:
		   - wywoływana jest metoda `log.queue_for_sending()`,
		   - dalsze przetwarzanie (wysyłka, sesje, UPO, retry)
			 realizowane jest asynchronicznie przez mechanizmy provider'a.

		5) Informacja zwrotna dla użytkownika:
		   - wyświetlana jest notyfikacja o poprawnym wygenerowaniu XML
			 i umieszczeniu dokumentu w kolejce do wysyłki.

		Uwagi architektoniczne:
		- metoda NIE wysyła XML bezpośrednio do systemu zewnętrznego,
		- pełni rolę punktu wejścia UI → logika eksportu → kolejka komunikacji,
		- obsługa błędów zatrzymuje proces przed utworzeniem logu
		  lub przed kolejkowaniem, aby nie pozostawiać niespójnych rekordów.

		:return: akcja klienta `display_notification`
		"""
		self.ensure_one()

		# -----------------------------------------------------------------------
		# 0. Sprawdzamy minimalne wymagania
		# -----------------------------------------------------------------------
		template = self.xml_export_template_id
		if not template:
			raise UserError(_("Nie przypisano szablonu eksportu XML."))

		if not template.provider_id:
			raise UserError(_("Wybrany szablon XML nie ma przypisanego provider'a."))

		provider = template.provider_id

		_logger.info(f"🚀 Eksport faktury {self.name} przy użyciu szablonu {template.name}")

		# ----------------------------------------------------------------------
		# 1. Generujemy XML (in_memory=True)
		# ----------------------------------------------------------------------
		try:
			xml_bytes = template.generate_xml(self, in_memory=True)
			if not xml_bytes:
				raise UserError(_("Nie udało się wygenerować XML z szablonu."))

		except Exception as e:
			_logger.exception("❌ Błąd podczas generowania XML do eksportu")
			raise UserError(_("Błąd podczas eksportu: %s") % str(e))

		# ----------------------------------------------------------------------
		# 2. PRZYGOTOWANIE DANYCH LOGU
		# ----------------------------------------------------------------------
		file_name = f"{template.name}_{self.id}.xml"
		log_vals = {
			'company_id': self.company_id.id,
			"direction": "export",
			"state": "generated",
			"provider_id": provider.id,
			"template_id": template.id,

			# Powiązanie z fakturą
			"document_model": self._name,
			"document_id": self.id,

			# Dane pliku
			"file_name": file_name,
			"file_data": base64.b64encode(xml_bytes),

			# Kontekst dodatkowy
			"context_json": {
				"invoice_id": self.id,
				"invoice_name": self.name,
				"template": template.name,
			}
		}

		# ----------------------------------------------------------------------
		# 3. UTWORZENIE REKORDU communication.log
		# ----------------------------------------------------------------------
		try:
			log = self.env["communication.log"].sudo().create(log_vals)
		except Exception as e:
			msg = f'❌ Błąd podczas tworzenia Communication.LOG: {e}"'
			_logger.exception( msg)
			raise UserError(_( msg))
		try:
			log.queue_for_sending()
		except Exception as e:
			msg = f"❌ Błąd podczas kolejkowania w Communication.LOG: {e}"
			_logger.exception( msg)
			raise UserError(_( msg))

		_logger.info(
			f"📄 Utworzono log komunikacji ID={log.id} "
			f"provider={provider.code}, state=queued")

		# 🔴 KLUCZOWE DLA UI
		self.write({
			"ksef_log_id": log.id
		})

		# ----------------------------------------------------------------------
		# 4. NOTYFIKACJA DLA UŻYTKOWNIKA
		# ----------------------------------------------------------------------
		return {
			"type": "ir.actions.client",
			"tag": "display_notification",
			"params": {
				"title": _("Eksport XML"),
				"message": _("Plik XML wygenerowany i umieszczony w kolejce do wysyłki."),
				"type": "success",
				"sticky": False,
				"next": {"type": "ir.actions.act_window_close"},  # Zamknij okno dialogowe jeśli istnieje
			},
		}

	def _get_fa_line_data(self, line, sequence_number):
		"""
		Mapuje dane linii faktury na pola P_1, P_2, etc.
		"""
		return {
			'NrWiersza': sequence_number,  # To jest numer sekwencji!
			'P_1': line.date or self.invoice_date,  # Data
			'P_2': line.name,  # Nazwa towaru/usługi
			'P_6': line.date or self.invoice_date,  # Data wykonania
			'P_7': line.product_id.default_code if line.product_id else '',  # GTU/etc.
			'P_8A': line.product_uom_id.name if line.product_uom_id else '',  # Jednostka
			'P_8B': line.quantity,  # Ilość
			'P_9A': line.price_unit,  # Cena jednostkowa netto
			'P_11': line.price_subtotal,  # Wartość netto
			'P_12': line.tax_ids[0].amount if line.tax_ids else 0,  # Stawka VAT
			'P_11Vat': line.price_tax,  # Kwota VAT
			'P_15': line.price_total,  # Wartość brutto
			# ... inne pola P_* według potrzeb
		}
	
	def _get_fa_xml_data(self):
		"""
		Przygotowuje dane dla szablonu XML FA
		"""
		fa_data = {
			'invoice': self,
			'lines': []
		}
		
		# Pozycje faktury z numeracją
		for i, line in enumerate(self.invoice_line_ids, 1):
			line_data = self._get_fa_line_data(line, i)
			fa_data['lines'].append(line_data)
			
		# Podsumowanie VAT (jeśli wymagane - inne pola niż V_)
		# ... do implementacji po analizie dalszej części schematu
		
		return fa_data



#EoF

# -*- coding: utf-8 -*-

import logging
from odoo import api, fields, models, _
_logger = logging.getLogger(__name__)


TIMELINE_STATE_SELECTION = [
	("none", "Nie wykonano"),
	("success", "Zakończono poprawnie"),
	("error", "Zatrzymano z błędem"),
]


#####################################################################################
class AccountMove(models.Model):
	_inherit = "account.move"

	ksef_validation_date = fields.Datetime(
		string="KSeF Validation Date",
		help="Data i czas weryfikacji faktury do KSeF",
		copy=False,
	)

	ksef_validation_state = fields.Char(
		string="KSeF Validation State",
		help="Status weryfikacji faktury do KSeF",
		copy=False,
	)

	ksef_sent_date = fields.Datetime(
		string="KSeF Sent Date",
		help="Data i czas wysłania faktury do KSeF",
		copy=False,
	)

	ksef_sent_state = fields.Char(
		string="KSeF Sent State",
		help="Status wysłania faktury do KSeF",
		copy=False,
	)

	ksef_accepted_date = fields.Datetime(
		string="KSeF Accepted Date",
		help="Data i czas przyjęcia faktury do KSeF",
		copy=False,
	)

	ksef_accepted_state = fields.Char(
		string="KSeF Accepted State",
		help="Status przyjęcia faktury do KSeF",
		copy=False,
	)

	ksef_upo_date = fields.Datetime(
		string="KSeF UPO Date",
		help="Data i czas pobrania UPO",
		copy=False,
	)

	ksef_upo_state = fields.Char(
		string="KSeF UPO State",
		help="Status pobrania UPO",
		copy=False,
	)


	@api.onchange(
		'xsd_validation_state',
	)
	def _update_ksef_validation_state(self):
		for move in self:
			if move.xsd_validation_state == "valid":
				move.ksef_validation_state = "success"
				move.ksef_validation_date = move.xsd_validation_date

			elif move.xsd_validation_state == "invalid":
				move.ksef_validation_state = "error"
				move.ksef_validation_date = move.xsd_validation_date

			else:
				move.ksef_validation_state = "none"
				move.ksef_validation_date = False

	def _ksef_timeline_set_sent(self, state):
		"""
		Krok: Wysłanie do KSeF

		state:
			success - operacja send_invoice zakończona poprawnie technicznie
			error   - operacja send_invoice zakończona błędem
		"""
		now = fields.Datetime.now()

		for move in self:
			move.write({
				"ksef_sent_state": state,
				"ksef_sent_date": now,
			})

	def _ksef_timeline_set_accepted(self, state):
		"""
		Krok: Przyjęcie przez KSeF

		state:
			success - check_status potwierdził przyjęcie / gotowość UPO
			error   - check_status potwierdził błąd / odrzucenie
		"""
		now = fields.Datetime.now()

		for move in self:
			move.write({
				"ksef_accepted_state": state,
				"ksef_accepted_date": now,
			})

class CommunicationLogKsefTimeline(models.Model):
	_inherit = "communication.log"

	"""
	Krok: Pobranie UPO
	"""	
	def _attach_upo_to_move(self, upo_binary):		
		attachment = super(CommunicationLogKsefTimeline, self)._attach_upo_to_move(upo_binary)		
		if attachment:
			move = self.import_move_id
			if move:
				move.ksef_upo_state = "success"
				move.ksef_upo_date = fields.Datetime.now()

		return attachment

	def _execute_python_download_upo(self, ksef_config, input_data):
		result = super(CommunicationLogKsefTimeline, self)._execute_python_download_upo( ksef_config, input_data)
		if result and result.get('data'):
			attachment_id = result.get('data').get('attachment_id')
			if attachment_id:
				move = self.env[self.document_model].search([('id','=', self.document_id)])
				move.ksef_upo_state = "success"
				move.ksef_upo_date = fields.Datetime.now()

		return result


	"""
	Krok: Wysłanie do KSeF i Przyjęcie przez KSeF
		tylko backend JAVA
		backend PYTHON w communication_provider_ksef_apiservice
	"""
	def _execute_ksef_java_operation(self, provider):
		operation = self.ksef_operation
		if operation in ['send_invoice', 'check_status']:
			move = self.env[self.document_model].search([('id','=', self.document_id)])

		result = super(CommunicationLogKsefTimeline, self)._execute_ksef_java_operation(provider)

		operation = self.ksef_operation	
		if operation in ['send_invoice', 'check_status']:
			if move:
				if operation in ['send_invoice'] and result.get("success") == True:
					move.ksef_sent_state = "success"
					move.ksef_sent_date = fields.Datetime.now()
				elif operation in ['send_invoice'] and result.get("success") != True:
					move.ksef_sent_state = "error"
					move.ksef_sent_date = fields.Datetime.now()

				if operation in ['check_status'] and result.get("success") == True:
					move.ksef_accepted_state = "success"
					move.ksef_accepted_date = fields.Datetime.now()
				elif operation in ['check_status'] and result.get("success") != True:
					move.ksef_accepted_state = "error"
					move.ksef_accepted_date = fields.Datetime.now()

		return result


#####################################################################################

#####################################################################################


# EoF

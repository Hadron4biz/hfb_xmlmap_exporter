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
"""@version 17.2.1
   @owner  Hadron for Business Sp. z o.o.
   @author Andrzej Wiśniewski (warp3r)
   @date   2026-03-07
"""
import re
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)

def safe_int(pattern):
	try:
		return int(pattern)
	except:
		return 0

# Stały regex na całą nazwę (kompatybilny w dół)
_NAME_REGEX = re.compile(
	r"^odoo-\d+(?:\.\d+)?-[a-z0-9_]+-[a-z0-9._]+-[a-z][a-z0-9_]*-\d+\.\d+\.\d+$"
)

def _sanitize_token(val, allow_dot=False):
	"""Zamiana na lowercase i ograniczenie znaków.
	   Utrzymane celowo 'prosto', aby działało identycznie w Odoo 14–19."""
	if not val:
		return ""
	val = (val or "").strip().lower()
	allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
	if allow_dot:
		allowed += "."
	return "".join(ch if ch in allowed else "_" for ch in val)

class XmlTemplateNameWizard(models.TransientModel):
	_name = "xml.template.name.wizard"
	_description = "Kreator nazwy szablonu (z wersją) i wskazania XSD"

	company_id = fields.Many2one(
		'res.company',
		string='Firma',
		required=False,  # <-- opcjonalne
		default=lambda self: self.env.company,
		ondelete='set null'
	)

	# 1) Plik schemy (wymagany)
	xsd_attachment_id = fields.Many2one(
		"ir.attachment",
		string="Schemat XSD",
		required=True,
		help="Załącz plik XSD (ir.attachment)."
	)

	# 2) Składowe nazwy
	#	(Selection + Char — proste typy, stabilne w dół)
	odoo_version_major = fields.Selection(
		selection=[("14","14"), ("15","15"), ("16","16"), ("17","17"), ("18","18"), ("19","19")],
		required=True, default="19", string="Odoo major"
	)
	odoo_version_minor = fields.Char(string="Odoo minor", help="np. 0 (opcjonalnie)")

	system_id = fields.Char(
		string="System",
		required=True,
		default="peppol",
		help="np. peppol / efaktura / ubl / x12 / custom"
	)
	system_ver = fields.Char(
		string="Wersja systemu",
		required=True,
		help="np. 3.0 / bis3 / 2.3 / 4010 / 2025.10"
	)

	doc_type = fields.Selection(
		selection=[
			("bill", "bill (invoice)"),
			("order", "order"),
			("despatch", "despatch"),
			("creditnote", "creditnote"),
			("debitnote", "debitnote"),
			("remittance", "remittance"),
			("statement", "statement"),
			("catalog", "catalog"),
		],
		required=True,
		default="bill",
		string="Typ dokumentu",
	)

	tpl_ver_major = fields.Integer(string="Tpl major", required=True, default=1)
	tpl_ver_minor = fields.Integer(string="Tpl minor", required=True, default=0)
	tpl_ver_patch = fields.Integer(string="Tpl patch", required=True, default=0)

	# 3) Podgląd (compute bez store – działa identycznie 14–19)
	preview_name = fields.Char(string="Podgląd nazwy", compute="_compute_preview_name", readonly=True)

	@api.depends(
		"odoo_version_major", "odoo_version_minor",
		"system_id", "system_ver",
		"doc_type",
		"tpl_ver_major", "tpl_ver_minor", "tpl_ver_patch"
	)
	def _compute_preview_name(self):
		for w in self:
			ver = w.odoo_version_major or ""
			minor = _sanitize_token(w.odoo_version_minor) if w.odoo_version_minor else ""
			if minor:
				ver = "%s.%s" % (ver, minor)
			system = _sanitize_token(w.system_id)
			sysver = _sanitize_token(w.system_ver, allow_dot=True)
			doc = (w.doc_type or "bill").strip().lower()
			semver = "%d.%d.%d" % (
				int(w.tpl_ver_major or 0),
				int(w.tpl_ver_minor or 0),
				int(w.tpl_ver_patch or 0),
			)
			w.preview_name = "odoo-%s-%s-%s-%s-%s" % (ver, system, sysver, doc, semver)

	@api.constrains("tpl_ver_major", "tpl_ver_minor", "tpl_ver_patch")
	def _check_semver_nonnegative(self):
		for w in self:
			for v in (w.tpl_ver_major, w.tpl_ver_minor, w.tpl_ver_patch):
				if v is None or v < 0:
					raise ValidationError(_("Wersja szablonu (semver) musi być złożona z nieujemnych liczb."))

	@api.constrains("preview_name")
	def _check_preview_format(self):
		for w in self:
			if not w.preview_name or not _NAME_REGEX.match(w.preview_name):
				raise ValidationError(_("Nazwa '%s' nie spełnia wymaganego formatu.") % (w.preview_name or ""))

	def action_confirm(self):
		"""Utwórz rekord szablonu z nazwą oraz wskazanym XSD.
		Po utworzeniu dopilnuj automatycznego złożenia nazwy, jeśli nie spełnia formatu.
		Dalsza logika (import XSD -> node) jest poza tym wizardem.
		"""
		self.ensure_one()

		# (1) weryfikacja podglądu nazwy (jeśli ją masz u siebie – zostaw jak jest)
		if not self.preview_name:
			raise ValidationError(_("Brak złożonej nazwy szablonu. Uzupełnij dane wejściowe."))

		# (2) utworzenie minimalnego szablonu
		template_vals = {
			"name": self.preview_name,				 # lub inna Twoja zmienna z nazwą
			"xsd_attachment_id": self.xsd_attachment_id.id,
			"model_id": self.model_id.id if 'model_id' in self._fields else False,
			"root_tag": self.root_tag if 'root_tag' in self._fields else False,
			"namespace": self.namespace if 'namespace' in self._fields else False,
			"ns_prefix": self.ns_prefix if 'ns_prefix' in self._fields else False,
			"active": True,
		}
		# usuwamy klucze z False, żeby nie nadpisać niczego zbędnie
		template_vals = {k: v for k, v in template_vals.items() if v}

		template = self.env["xml.export.template"].with_company( self.company_id).create(template_vals)
		# Po podpięciu XSD — złóż nazwę, jeśli pusta/niepoprawna:
		if hasattr(template, "_ensure_name_after_xsd_and_direction"):
			template._ensure_name_after_xsd_and_direction()

		# (3) KLUCZOWE: po podpięciu XSD dopilnuj automatycznego złożenia nazwy,
		#	 jeśli jest pusta/niepoprawna wg formatu.
		#	 Metoda jest w modelu xml.export.template (dodana wcześniej).
		if hasattr(template, "_ensure_name_after_xsd_and_direction"):
			template._ensure_name_after_xsd_and_direction()

		# (4) Otwórz utworzony szablon
		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.export.template",
			"res_id": template.id,
			"view_mode": "form",
			"target": "current",
		}


	def xxx_action_confirm(self):
		"""Zwróć gotową nazwę i ustaw XSD na szablonie – reszta logiki w modelu szablonu."""
		self.ensure_one()
		if not self.preview_name or not _NAME_REGEX.match(self.preview_name):
			raise ValidationError(_("Nazwa jest niepoprawna — sprawdź pola wejściowe."))

		# Minimalne utworzenie szablonu (tylko nazwa + XSD).
		template_vals = {
			"name": self.preview_name,
			"xsd_attachment_id": self.xsd_attachment_id.id,
			"active": True,
			'company_id': self.company_id.id,
		}
		tmpl = self.env["xml.export.template"].create(template_vals)

		# Otwórz świeżo utworzony szablon (widok form) – działa tak samo 14–19
		return {
			"type": "ir.actions.act_window",
			"res_model": "xml.export.template",
			"view_mode": "form",
			"res_id": tmpl.id,
			"target": "current",
		}

#EoF

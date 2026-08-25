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
   @date   2026-03-07
"""
import json
import logging
import re

from datetime import date, datetime
from decimal import (
	Decimal,
	InvalidOperation,
	ROUND_CEILING,
	ROUND_DOWN,
	ROUND_FLOOR,
	ROUND_HALF_EVEN,
	ROUND_HALF_UP,
	ROUND_UP,
)

from odoo import _, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


# ============================================================
# Rozszerzenie modelu typów XSD o brakujące facety
# ============================================================

class XmlXsdTypeExtension(models.Model):
	_inherit = "xml.xsd.type"

	length = fields.Integer(
		string="Length",
		default=-1,
		help="-1 oznacza brak facetu xsd:length.",
	)

	total_digits = fields.Integer(
		string="Total Digits",
		default=-1,
		help="-1 oznacza brak facetu xsd:totalDigits.",
	)

	fraction_digits = fields.Integer(
		string="Fraction Digits",
		default=-1,
		help="-1 oznacza brak facetu xsd:fractionDigits.",
	)

	min_inclusive = fields.Char(
		string="Min Inclusive",
	)

	max_inclusive = fields.Char(
		string="Max Inclusive",
	)

	min_exclusive = fields.Char(
		string="Min Exclusive",
	)

	max_exclusive = fields.Char(
		string="Max Exclusive",
	)

	white_space = fields.Selection(
		selection=[
			("preserve", "Preserve"),
			("replace", "Replace"),
			("collapse", "Collapse"),
		],
		string="White Space",
	)


# ============================================================
# Rozszerzenie parametrów formatowania node
# ============================================================

class XmlExportNodeFormatExtension(models.Model):
	_inherit = "xml.export.node"

	fmt_decimal_precision_enabled = fields.Boolean(
		string="Użyj precyzji dziesiętnej",
		default=False,
		help=(
			"Pozwala odróżnić brak lokalnego formatowania od jawnie "
			"ustawionej precyzji równej 0."
		),
	)

	fmt_decimal_rounding = fields.Selection(
		selection=[
			("half_up", "ROUND_HALF_UP"),
			("half_even", "ROUND_HALF_EVEN"),
			("down", "ROUND_DOWN"),
			("up", "ROUND_UP"),
			("ceiling", "ROUND_CEILING"),
			("floor", "ROUND_FLOOR"),
		],
		string="Zaokrąglanie dziesiętne",
		default="half_up",
	)


# ============================================================
# Formatter i walidator wartości XML/XSD
# ============================================================

class XmlExportTemplateXsdFormatter(models.Model):
	_inherit = "xml.export.template"

	# ============================================================
	# FORMATOWANIE WEDŁUG PATTERN
	# ============================================================
	def _format_value_by_xsd_pattern(
		self,
		node,
		xsd_type,
		result,
		record=None,
	):
		"""
		Próbuje przygotować wartość zgodną z pattern typu XSD.

		Pattern decyduje, która reprezentacja leksykalna jest właściwa.
		Jeżeli żadna reprezentacja nie pasuje, zwracana jest wartość
		wejściowa bez zmian.
		"""

		pattern = (xsd_type.pattern or "").strip()

		if not pattern:
			return result

		candidates = []

		def add_candidate(candidate):
			"""Dodaje niepustego i niepowtórzonego kandydata."""
			if candidate is None:
				return

			if not isinstance(candidate, str):
				candidate = str(candidate)

			if candidate not in candidates:
				candidates.append(candidate)

		# --------------------------------------------------------
		# STRING
		# --------------------------------------------------------

		if isinstance(result, str):
			add_candidate(result)

			stripped_result = result.strip()
			add_candidate(stripped_result)

			# Tekst może już reprezentować datetime.
			try:
				parsed_datetime = datetime.fromisoformat(
					stripped_result.replace("Z", "+00:00")
				)
			except (TypeError, ValueError):
				parsed_datetime = None

			if parsed_datetime is not None:
				add_candidate(parsed_datetime.isoformat())

			# Tekst może reprezentować samą datę.
			try:
				parsed_date = date.fromisoformat(stripped_result)
			except (TypeError, ValueError):
				parsed_date = None

			if parsed_date is not None:
				date_value = parsed_date.isoformat()

				add_candidate(date_value)
				add_candidate(f"{date_value}T00:00:00")

		# --------------------------------------------------------
		# DATETIME
		# datetime sprawdzamy przed date, ponieważ dziedziczy po date.
		# --------------------------------------------------------

		elif isinstance(result, datetime):
			add_candidate(result.isoformat())

		# --------------------------------------------------------
		# DATE
		# --------------------------------------------------------

		elif isinstance(result, date):
			date_value = result.isoformat()

			add_candidate(date_value)
			add_candidate(f"{date_value}T00:00:00")

		# --------------------------------------------------------
		# BOOLEAN
		# bool sprawdzamy przed int, ponieważ dziedziczy po int.
		# --------------------------------------------------------

		elif isinstance(result, bool):
			add_candidate("true" if result else "false")
			add_candidate("1" if result else "0")

		# --------------------------------------------------------
		# DECIMAL
		# --------------------------------------------------------

		elif isinstance(result, Decimal):
			add_candidate(format(result, "f"))

		# --------------------------------------------------------
		# INTEGER
		# --------------------------------------------------------

		elif isinstance(result, int):
			add_candidate(str(result))

		# --------------------------------------------------------
		# FLOAT
		# --------------------------------------------------------

		elif isinstance(result, float):
			try:
				decimal_value = Decimal(str(result))
				add_candidate(format(decimal_value, "f"))
			except (InvalidOperation, ValueError):
				pass

			add_candidate(str(result))

		# --------------------------------------------------------
		# POZOSTAŁE TYPY
		# --------------------------------------------------------

		else:
			add_candidate(str(result))

		try:
			for candidate in candidates:
				if re.fullmatch(pattern, candidate):
					_logger.info(
						"🔧 FORMAT_XSD_PATTERN: "
						"node=%s, xsd_type=%s, pattern=%r, "
						"original=%r, final=%r",
						node.name,
						xsd_type.name,
						pattern,
						result,
						candidate,
					)

					result = candidate
					return result

		except re.error as error:
			_logger.warning(
				"⚠️ FORMAT_XSD_PATTERN: invalid or unsupported pattern: "
				"node=%s, xsd_type=%s, pattern=%r, error=%s",
				node.name,
				xsd_type.name,
				pattern,
				error,
			)

			return result

		_logger.info(
			"🔧 FORMAT_XSD_PATTERN: no matching representation: "
			"node=%s, xsd_type=%s, pattern=%r, "
			"value=%r, candidates=%r",
			node.name,
			xsd_type.name,
			pattern,
			result,
			candidates,
		)

		return result

	# ============================================================
	# FORMATOWANIE WEDŁUG TYPU XSD
	# ============================================================
	def _format_value_by_xsd_type(
		self,
		node,
		xsd_type,
		result,
		record=None,
	):
		"""
		Formatuje wartość według wbudowanego typu XSD wynikającego
		z base_type.

		Jeżeli base_type jest typem niestandardowym lub nieobsługiwanym,
		wartość jest zwracana bez zmian.
		"""

		if not xsd_type:
			return result

		if xsd_type.category != "simple":
			return result

		base_type = (xsd_type.base_type or "").strip()

		if not base_type:
			return result

		# QName analizujemy bez zgadywania po samej nazwie lokalnej.
		if ":" in base_type:
			prefix, local_type = base_type.split(":", 1)

			# Na tym etapie bezpośrednio obsługujemy tylko typy
			# wbudowane XML Schema.
			if prefix not in ("xsd", "xs"):
				_logger.info(
					"🔧 FORMAT_XSD_TYPE: unresolved custom base type: "
					"node=%s, xsd_type=%s, base_type=%s",
					node.name,
					xsd_type.name,
					base_type,
				)
				return result
		else:
			local_type = base_type

		string_types = {
			"string",
			"normalizedString",
			"token",
			"language",
			"Name",
			"NCName",
			"NMTOKEN",
			"anyURI",
		}

		integer_types = {
			"integer",
			"int",
			"long",
			"short",
			"byte",
			"nonNegativeInteger",
			"positiveInteger",
			"nonPositiveInteger",
			"negativeInteger",
			"unsignedLong",
			"unsignedInt",
			"unsignedShort",
			"unsignedByte",
		}

		# --------------------------------------------------------
		# STRING
		# --------------------------------------------------------

		if local_type in string_types:
			result = str(result)

		# --------------------------------------------------------
		# BOOLEAN
		# --------------------------------------------------------

		elif local_type == "boolean":
			if isinstance(result, bool):
				result = "true" if result else "false"

			elif isinstance(result, int) and result in (0, 1):
				result = str(result)

			elif isinstance(result, str):
				normalized = result.strip().lower()

				if normalized in ("true", "1"):
					result = "true" if normalized == "true" else "1"

				elif normalized in ("false", "0"):
					result = "false" if normalized == "false" else "0"

		# --------------------------------------------------------
		# INTEGER
		# --------------------------------------------------------

		elif local_type in integer_types:
			if isinstance(result, bool):
				return result

			try:
				decimal_value = Decimal(str(result))
			except (InvalidOperation, ValueError, TypeError):
				return result

			if decimal_value != decimal_value.to_integral_value():
				return result

			result = format(
				decimal_value.to_integral_value(),
				"f",
			)

		# --------------------------------------------------------
		# DECIMAL
		# --------------------------------------------------------

		elif local_type == "decimal":
			if isinstance(result, bool):
				return result

			try:
				decimal_value = Decimal(str(result))
			except (InvalidOperation, ValueError, TypeError):
				return result

			result = format(decimal_value, "f")

		# --------------------------------------------------------
		# FLOAT / DOUBLE
		# --------------------------------------------------------

		elif local_type in ("float", "double"):
			if isinstance(result, bool):
				return result

			try:
				float_value = float(result)
			except (ValueError, TypeError):
				return result

			result = str(float_value)

		# --------------------------------------------------------
		# DATE
		# --------------------------------------------------------

		elif local_type == "date":
			if isinstance(result, datetime):
				result = result.date().isoformat()

			elif isinstance(result, date):
				result = result.isoformat()

			elif isinstance(result, str):
				try:
					result = date.fromisoformat(
						result.strip()
					).isoformat()
				except ValueError:
					return result

		# --------------------------------------------------------
		# DATETIME
		# --------------------------------------------------------

		elif local_type == "dateTime":
			if isinstance(result, datetime):
				result = result.isoformat()

			elif isinstance(result, date):
				result = datetime.combine(
					result,
					time.min,
				).isoformat()

			elif isinstance(result, str):
				lexical_value = result.strip()

				try:
					parsed_value = datetime.fromisoformat(
						lexical_value.replace("Z", "+00:00")
					)
				except ValueError:
					return result

				result = parsed_value.isoformat()

		# --------------------------------------------------------
		# TIME
		# --------------------------------------------------------

		elif local_type == "time":
			if isinstance(result, datetime):
				result = result.timetz().isoformat()

			elif isinstance(result, time):
				result = result.isoformat()

			elif isinstance(result, str):
				try:
					result = time.fromisoformat(
						result.strip()
					).isoformat()
				except ValueError:
					return result

		_logger.info(
			"🔧 FORMAT_XSD_TYPE: "
			"node=%s, xsd_type=%s, base_type=%s, final=%r",
			node.name,
			xsd_type.name,
			base_type,
			result,
		)

		return result


	# ============================================================
	# FORMATOWANIE WEDŁUG OPCJI NODE
	# ============================================================

	def _format_value_by_node_options(
		self,
		node,
		result,
		record=None,
	):
		"""
		Formatuje wartość według ustawień zapisanych bezpośrednio
		na xml.export.node.

		Jeżeli dane ustawienie nie dotyczy typu wartości, result
		pozostaje bez zmian.
		"""

		# --------------------------------------------------------
		# DATETIME
		# --------------------------------------------------------

		if isinstance(result, datetime):
			if node.fmt_datetime:
				try:
					result = result.strftime(node.fmt_datetime)
				except (TypeError, ValueError):
					return result

			elif node.fmt_date:
				try:
					result = result.strftime(node.fmt_date)
				except (TypeError, ValueError):
					return result

		# --------------------------------------------------------
		# DATE
		# --------------------------------------------------------

		elif isinstance(result, date):
			if node.fmt_date:
				try:
					result = result.strftime(node.fmt_date)
				except (TypeError, ValueError):
					return result

			elif node.fmt_datetime:
				try:
					result = datetime.combine(
						result,
						time.min,
					).strftime(node.fmt_datetime)
				except (TypeError, ValueError):
					return result

		# --------------------------------------------------------
		# BOOLEAN
		# --------------------------------------------------------

		elif isinstance(result, bool):
			if result:
				result = node.fmt_bool_true or "true"
			else:
				result = node.fmt_bool_false or "false"

		# --------------------------------------------------------
		# DECIMAL / INTEGER / FLOAT
		# --------------------------------------------------------

		elif isinstance(result, (Decimal, int, float)):
			# Obecne pole Integer nie rozróżnia:
			# - brak konfiguracji,
			# - jawnej precyzji 0.
			#
			# Dlatego na tym etapie stosujemy tylko wartości > 0.
			precision = node.fmt_decimal_precision

			if precision and precision > 0:
				try:
					decimal_value = Decimal(str(result))
					quantizer = Decimal("1").scaleb(-precision)

					result = format(
						decimal_value.quantize(
							quantizer,
							rounding=ROUND_HALF_UP,
						),
						"f",
					)
				except (InvalidOperation, ValueError, TypeError):
					return result

		# --------------------------------------------------------
		# OPCJE TEKSTOWE
		# --------------------------------------------------------

		if isinstance(result, str):
			if node.fmt_strip:
				result = result.strip()

			if node.fmt_upper and not node.fmt_lower:
				result = result.upper()

			elif node.fmt_lower and not node.fmt_upper:
				result = result.lower()

			elif node.fmt_upper and node.fmt_lower:
				_logger.warning(
					"⚠️ FORMAT_NODE_OPTIONS: "
					"fmt_upper and fmt_lower enabled simultaneously: "
					"node=%s",
					node.name,
				)

			if node.fmt_pad_left and node.fmt_pad_left > 0:
				pad_char = node.fmt_pad_char or "0"
				pad_char = pad_char[0]

				result = result.rjust(
					node.fmt_pad_left,
					pad_char,
				)

		_logger.info(
			"🔧 FORMAT_NODE_OPTIONS: node=%s, final=%r",
			node.name,
			result,
		)

		return result


#EoF

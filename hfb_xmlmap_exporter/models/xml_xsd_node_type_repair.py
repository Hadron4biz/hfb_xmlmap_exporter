# -*- coding: utf-8 -*-

from markupsafe import Markup, escape

from odoo import models, _


class XmlExportTemplate(models.Model):
	_inherit = "xml.export.template"

	def _repair_node_type_relations_from_xsd(
		self,
		apply=False,
		post_message=True,
	):
		"""
		Przygotowuje lub wykonuje naprawę relacji type_id na podstawie
		niezmienionego raportu _validate_nodes_against_xsd().

		Metoda:
		- nie modyfikuje walidatora ani importerów,
		- nie analizuje XSD ponownie własnym algorytmem,
		- nie tworzy i nie usuwa node'ów ani typów,
		- nie zmienia parent_id, sequence ani pozostałych metadanych XSD,
		- zapisuje wyłącznie xml.export.node.type_id,
		- domyślnie działa jako dry-run (apply=False).
		"""
		self.ensure_one()

		xsd_report = self._validate_nodes_against_xsd()
		Node = self.env["xml.export.node"]
		XsdType = self.env["xml.xsd.type"]

		result = {
			"apply": apply,
			"report_before": xsd_report,
			"report_after": xsd_report,
			"planned": [],
			"repaired": [],
			"unchanged": [],
			"skipped": [],
		}

		# Raport walidatora wskazuje node przez path. Budujemy mapę bez
		# zakładania, że każda ścieżka jest unikalna. Przy kolizji helper
		# nie wybiera rekordu samodzielnie.
		nodes_by_path = {}
		for node in self.node_ids:
			path = node.xpath or node.name
			nodes_by_path.setdefault(path, Node)
			nodes_by_path[path] |= node

		def add_result(bucket, issue, node=False, reason=None, target_type=False):
			entry = {
				"path": issue.get("path") or "",
				"actual": issue.get("actual") or "brak",
				"expected": issue.get("expected") or "brak",
				"node_id": node.id if node else False,
				"target_type_id": target_type.id if target_type else False,
				"reason": reason or "",
			}
			result[bucket].append(entry)
			return entry

		for issue in xsd_report.get("mismatches", []):
			path = issue.get("path")
			nodes = nodes_by_path.get(path, Node)

			if not nodes:
				add_result(
					"skipped",
					issue,
					reason="Nie odnaleziono node'a o ścieżce wskazanej w raporcie.",
				)
				continue

			if len(nodes) != 1:
				add_result(
					"skipped",
					issue,
					reason=(
						f"Ścieżka nie jest jednoznaczna — znaleziono "
						f"{len(nodes)} node'y."
					),
				)
				continue

			node = nodes
			expected = (issue.get("expected") or "").strip()

			# Typy wbudowane xs:* i typy anonimowe nie mają odpowiadającego
			# rekordu xml.xsd.type. Poprawną relacją jest type_id = False.
			expects_empty_type_id = (
				expected.startswith("xs:")
				or expected == "typ anonimowy (bez type_id)"
				or expected.endswith("(bez type_id)")
			)

			if expects_empty_type_id:
				if not node.type_id:
					add_result(
						"unchanged",
						issue,
						node=node,
						reason="Relacja type_id jest już pusta.",
					)
					continue

				planned = add_result(
					"planned",
					issue,
					node=node,
					reason="XSD wskazuje typ bez rekordu xml.xsd.type.",
				)
				if apply:
					node.write({"type_id": False})
					result["repaired"].append(planned)
				continue

			# Dla typu nazwanego walidator zwraca zwykle nazwę lokalną.
			# Usunięcie prefiksu zabezpiecza również raporty w formie tns:Type.
			expected_type_name = expected.split(":")[-1]
			if not expected_type_name:
				add_result(
					"skipped",
					issue,
					node=node,
					reason="Raport nie zawiera nazwy oczekiwanego typu XSD.",
				)
				continue

			type_candidates = XsdType.with_company(self.company_id).search([
				("template_id", "=", self.id),
				("company_id", "=", self.company_id.id),
				("name", "=", expected_type_name),
			])

			if not type_candidates:
				add_result(
					"skipped",
					issue,
					node=node,
					reason=(
						f"Brak zaimportowanego typu XSD "
						f"„{expected_type_name}” w tym szablonie."
					),
				)
				continue

			if len(type_candidates) != 1:
				add_result(
					"skipped",
					issue,
					node=node,
					reason=(
						f"Typ XSD „{expected_type_name}” nie jest jednoznaczny "
						f"— znaleziono {len(type_candidates)} rekordy."
					),
				)
				continue

			target_type = type_candidates
			if node.type_id == target_type:
				add_result(
					"unchanged",
					issue,
					node=node,
					target_type=target_type,
					reason="Node wskazuje już właściwy rekord typu.",
				)
				continue

			planned = add_result(
				"planned",
				issue,
				node=node,
				target_type=target_type,
				reason="Jednoznacznie dopasowano typ w katalogu tego szablonu.",
			)
			if apply:
				node.write({"type_id": target_type.id})
				result["repaired"].append(planned)

		if apply:
			result["report_after"] = self._validate_nodes_against_xsd()

		if post_message:
			mode_label = (
				"wykonanie naprawy"
				if apply
				else "próba bez zapisu (dry-run)"
			)
			html = (
				"<b>Relacje typów XET ↔ XSD</b><br><br>"
				f"• Tryb: <b>{escape(mode_label)}</b><br>"
				f"• Niezgodności wskazane przez walidator: "
				f"{len(xsd_report.get('mismatches', []))}<br>"
				f"• Możliwe jednoznaczne operacje: "
				f"{len(result['planned'])}<br>"
				f"• Wykonane naprawy: {len(result['repaired'])}<br>"
				f"• Bez zmian: {len(result['unchanged'])}<br>"
				f"• Pominięte: {len(result['skipped'])}<br>"
			)

			if apply:
				html += (
					f"• Niezgodności pozostałe po naprawie: "
					f"{len(result['report_after'].get('mismatches', []))}<br>"
				)

			html += "<br><b>Niezgodności typów XET ↔ XSD:</b><br>"

			entries_by_path = {}
			for bucket, label in (
				("repaired", "naprawiono"),
				("planned", "można naprawić"),
				("unchanged", "bez zmian"),
				("skipped", "pominięto"),
			):
				for entry in result[bucket]:
					# W trybie apply wpis naprawiony znajduje się również
					# w planned, dlatego status repaired ma pierwszeństwo.
					if (
						entry["path"] not in entries_by_path
						or bucket == "repaired"
					):
						entries_by_path[entry["path"]] = (entry, label)

			for issue in xsd_report.get("mismatches", []):
				entry, label = entries_by_path.get(
					issue.get("path"),
					(
						{
							"reason": "Brak rozstrzygnięcia.",
						},
						"pominięto",
					),
				)
				html += (
					f"• <b>{escape(issue.get('path') or '')}</b>: "
					f"XET = <code>{escape(issue.get('actual') or 'brak')}</code>, "
					f"XSD = <code>{escape(issue.get('expected') or 'brak')}</code> "
					f"— {escape(label)}: {escape(entry['reason'])}<br>"
				)

			if not xsd_report.get("mismatches"):
				html += (
					"<span style='color:green;'>"
					"Nie znaleziono relacji wymagających naprawy."
					"</span><br>"
				)

			if xsd_report.get("errors"):
				html += "<br><b style='color:red;'>Błędy walidacji XSD:</b><br>"
				for error in xsd_report["errors"]:
					html += f"• {escape(error)}<br>"

			self.message_post(
				body=Markup(html),
				subject=_("Relacje typów XET ↔ XSD"),
				message_type="comment",
				subtype_xmlid="mail.mt_note",
			)

		return result
#EoF

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
{
    "name": "eXtensible Exchange Template (XET) - KSeF, XML, EDI Integration for Odoo 17",
    "summary": "Integracja KSeF, wymiana danych XML, szablony XET, eksport/import faktur, komunikacja z systemami zewnętrznymi",
    "version": "17.1.2",
    "license": "AGPL-3",
    "author": "Hadron for Business",
    'category': 'Accounting/Invoicing',
    "website": "https://ksef.odoo.com",
    "depends": [
        "base",
        "mail",
        "sale",
        "account",
    ],
    "data": [
        # --- security zawsze pierwsze ---
        "security/security.xml",
        "security/ir.model.access.csv",

        # --- widoki modeli, które tworzą modele ---
        "views/xml_node_views.xml",
        "views/xml_template_views.xml",
        "views/actions.xml",
        "wizard/template_name_wizard_views.xml",
        "wizard/wizard_xsd_upload_views.xml",
        "views/account_move_view.xml",
        "wizard/wizard_template_import_json.xml",

        # --- dane, które odwołują się do modeli ---
        "views/xml_types_views.xml",
        #"data/communication_provider_data.xml",

        # --- a po nich widoki modeli ---
        "views/communication_log_views.xml",
        "views/communication_provider_views.xml",
        "views/communication_provider_localdir_views.xml",
        "views/communication_provider_ksef_views.xml",
        'views/xml_xsd_import_wizard_views.xml',

        # --- menu dla wszystkich operacji ---
        "views/menu.xml",
        "views/communication_provider_localdir_menu.xml",
        "views/communication_provider_ksef_menu.xml",
        "wizard/wizard_template_import_json_menu.xml",

        # --- addons
        "views/upo_pdf_templates.xml",
        "views/report_invoice_ksef_qr.xml",
        "views/cron.xml",

		# --- patch dla niedziałającego pola Many2oneReference w Odoo 17-
		"wizard/communication_provider_config_wizard_view.xml",

    ],
    "demo": [
        "data/communication_channel_demo.xml",
    ],
    'images': [
        'static/description/Banner.png',
        'hfb_xmlmap_exporter/static/description/icon.png',
    ],
    'icon': 'hfb_xmlmap_exporter/static/description/icon.png',
    "application": True,
    "installable": True,
}
#EoF

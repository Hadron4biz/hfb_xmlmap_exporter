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

# 1. MODELE BAZOWE / ABSTRAKCYJNE (najpierw zależności)
from . import xml_template
from . import xml_export_template
from . import xml_import_template
from . import xml_validation_log
from . import xml_xsd_import_wizard

# 2. MODELE CORE (komunikacja bazowa)
from . import communication_provider				# Model bazowy providerów
from . import communication_log						# Model bazowy logów

# 3. MODUŁY API / NARZĘDZIA (bez zależności od Odoo models)
#from . import ksef_constants           			# Tylko stałe, nie dziedziczy z models.Model
#from . import ksef_exceptions						# Tylko wyjątki
#from . import ksef_api_client						# KSEFAPICLIENT Z OBSŁUGĄ X-SESSION-ID
#from . import ksef_xades_signer_v2					# kod generujący podpis XAdES dla KSeF v2
#from . import ksef_crypto_utils					# helper do kryptografii

# 4. SPECJALIZOWANE PROVIDERY (dziedziczą z communication_provider)
from . import communication_provider_localdir		# Dziedziczy/wykorzystuje communication_provider
from . import communication_provider_ksef_apiservice # Natywna obsługa API
from . import communication_provider_ksef_base		# KLASA rozbudowy modeli bazowych
from . import communication_provider_ksef      		# Dziedziczy/wykorzystuje communication_provider + ksef_api_client
from . import communication_provider_ksef_addons	# Rozszerzenia dla importu/konwersji faktury ksef xml do odoo
from . import communication_provider_ksef_qrcode	# Obsługa QR Type I
from . import communication_provider_ksef_offline	# Obsługa Trybu Offline i QR Type II
#from . import communication_provider_ksef_workflow # Rozszerzenie CommunicationProviderKsef o pełny workflow sesji kwalifikowanej
#from . import communication_provider_peppol		# Rozszerzenie dla obsługo PEPPOL

# 5. MODELE BIZNESOWE (używają providerów)
from . import invoice								# Używa providerów do wysyłki faktur
from . import account_move_ksef_qr					# Rozszezenia obsługi QR Type I
from . import upo_pdf								# Wizualizacja UPO

#EoF

# Changelog

## [Unreleased]

### Added

#### communication.provider.ksef

- Dodano pole `api_backend` (Selection: `java | python`)
  - Umożliwia wybór klienta API KSeF.
  - Domyślna wartość: `java`.

---

#### communication.log

Dodano wsparcie dla danych kryptograficznych sesji oraz technicznych statusów API.

Nowe pola:

- `ksef_session_key` (Binary)  
  Klucz sesji AES-256 wykorzystywany do szyfrowania faktur (backend Python).

- `ksef_session_iv` (Binary)  
  Wektor inicjujący (IV) dla szyfrowania AES.

- `ksef_http_status` (Integer)  
  Kod odpowiedzi HTTP zwracany przez API KSeF.

- `ksef_api_status_code` (Integer)  
  Kod statusu logicznego zwracany przez API KSeF.

- `ksef_api_status_message` (Text)  
  Szczegółowy komunikat odpowiedzi API KSeF.

- `ksef_sent_datetime` (Datetime)  
  Data i czas skutecznego przesłania dokumentu do KSeF.

---

### Architecture

- Zachowano istniejący mechanizm powiązania dokumentu:
  - `document_model`
  - `document_id`
  - `import_move_id`

- Nie wprowadzono duplikacji pól:
  - `ksef_reference_number`
  - `ksef_session_token`
  - `ksef_invoice_number`
  - `ksef_number` (account.move)
  - `ksef_sent_date` (account.move)

- Tokeny (access/refresh) pozostają przechowywane na poziomie firmy.
- `communication.log` pozostaje źródłem prawdy dla stanu procesu KSeF.
- Pola w `account.move` pełnią funkcję odzwierciedlenia biznesowego.

---

### Technical Notes

Zmiany przygotowują system do:

- obsługi backendu Python (pełnej lub hybrydowej),
- rozdzielenia statusów HTTP i statusów logicznych API,
- bezpiecznej obsługi równoległych sesji,
- spójnego modelu retry i harmonogramowania.

---

## [18.0.1.12] — 2026-07-31 — Porządkowanie kodu

### Removed

- Usunięto 5 plików `views/*.xml`, których nie było w `__manifest__.py`
  (nigdy się nie ładowały): `communication_provider_peppol_views.xml`,
  `communication_provider_poweroffice_views.xml` (odwoływały się do
  nieistniejących modeli), `ksef_connection_test_result_views.xml`
  (nieistniejący model), `report_invoice.xml` (odwoływał się do
  usuniętych pól QR, zastąpiony przez `report_invoice_ksef_qr.xml`),
  `ksef_invoice_offline.xml` (nigdy niepodpięty do manifestu).
- Usunięto zdublowane/martwe definicje metod i pól, które w Pythonie
  były cicho nadpisywane przez późniejszą definicję w tej samej klasie
  (m.in. `_get_next_operation`, dwie z trzech kopii `_handle_ksef_error`,
  martwą wersję `_is_token_valid`, `_call_python_http` wraz z zależną od
  niej `check_status`, `XXX_import_xsd_types_from_attachments`,
  `XXX_process_invoice_lines_fawiersz`, `xxx_action_confirm`) —
  w `communication_provider_ksef.py`, `communication_provider_ksef_apiservice.py`,
  `xml_template.py`, `communication_provider_ksef_addons.py`,
  `wizard/wizard_template_name.py`.

### Fixed

- Pole `ksef_session_token` miało dwie definicje w tej samej klasie —
  późniejsza (bez `groups="base.group_system"`) cicho nadpisywała
  wcześniejszą, przez co token sesji KSeF nie miał ograniczonego dostępu.
  Przywrócono `groups="base.group_system"`.
- Pole `executed_by` w `communication.log` analogicznie traciło
  `tracking=True` — przywrócono, żeby zmiana wykonawcy operacji trafiała
  do chattera.
- `cron_ksef_offline_monitor` (auto-wznowienie faktur z trybu OFFLINE)
  filtrował logi po `self.company_id`, mimo że jest wołany na
  `AbstractModel` bez kontekstu firmy — cron nigdy nic by nie znalazł.
  Naprawiono przekazywanie `company_id` z konkretnego logu.

### Added

- Dodano brakujący wpis `ir.cron` (`ir_cron_ksef_offline_monitor`,
  `active=False`, co 15 minut) aktywujący `cron_ksef_offline_monitor`.



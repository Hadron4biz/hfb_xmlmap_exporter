# hfb_xmlmap_exporter – uwagi i rozbieżności do dalszych prac

Stan na 19.10.2026.

**Źródła**
- kod modułu, gałąź `15.0`, commit `d02c4e7` (wersja 15.1.6), github.com/Hadron4biz/hfb_xmlmap_exporter (lustro wewnętrznego GitLaba),
- istniejące opisy w repozytorium (`README.md`, `ARCHITECTURE.md`, `docs/*.md`) – specyfikacje zewnętrzne (KSeF API, FA(3)) nie były porównywane,
- kod Odoo 15 (`odoo/addons/base/models/ir_module.py`, `odoo/tools/mail.py`) – obsługa opisu modułu,
- dane instancji Odoo15 (firma KAPE), odczytane przez konektor w trybie tylko do odczytu.

Numery linii odnoszą się do commitu `d02c4e7`. Plik bez nazwy w polu „Gdzie” = `models/communication_provider_ksef.py`.

**Oznaczenia**
- **[kod]** – fakt wynikający bezpośrednio z kodu modułu,
- **[dane]** – fakt odczytany z danych instancji,
- **[hipoteza]** – przypuszczenie do sprawdzenia; nie zostało zweryfikowane.

---

## IMP – import faktur z KSeF

### IMP-01 · Duplikaty logów potomnych · [kod] [dane]
- **Gdzie:** l. 1619–1629 (`_process_import_list`).
- **Stan:** w 15.1.6 warunek `('parent_id', '=', self.id)` zakomentowany (l. 1623); wyszukiwanie obejmuje wszystkie logi importu z numerem KSeF, bez filtra stanu i providera. Wcześniej każdy log listy tworzył logi potomne dla tych samych faktur.
- **Dane Odoo15:** 23 numery KSeF, każdy w jednym logu importu.
- **[hipoteza]** w bazie `kape15_rc1_231221` (zrzut z 20 kopiami na numer) duplikaty pozostają; konektor wskazuje inną bazę.

### IMP-02 · `import_last_success_date` nie jest zapisywane · [kod] [dane]
- **Gdzie:** odczyt l. 4819, 4911, 5116; pole l. 5073; widok `communication_provider_ksef_views.xml` l. 174 (readonly).
- **Stan:** brak zapisu w module. `_calculate_import_date_range` zawsze używa bufora `import_days_back` („First import”), `_should_create_import_list_job` zawsze zwraca „First import ever”.
- **Dane Odoo15:** konfiguracja 18 – pole puste.

### IMP-03 · Kontrola aktywnej listy · [kod]
- **Gdzie:** l. 4806–4816.
- **Stan:** uwzględnia tylko logi z `ksef_operation = 'import_list'` utworzone w ostatniej godzinie; wykluczenie `state in ['completed', 'failed', 'error']` – wartości `completed` i `failed` nie występują w `state`. Log listy w kroku `auth` nie jest uwzględniany.

### IMP-04 · Zakres i stronicowanie zapytania · [kod]
- **Gdzie:** `communication_provider_ksef_apiservice.py` l. 939, 950–952; l. 1550.
- **Stan:** jedna strona wyników (bez `pageOffset`), `dateType: INVOICING`, daty z sufiksem `+01:00`. `ksef_import_params` logu listy nie jest używane – zakres liczony od nowa w chwili przetwarzania.

### IMP-05 · `ksef_discovered_count` · [kod] [dane]
- **Gdzie:** l. 1582 (`data.get('invoiceCount', 0)`), także l. 4341, 4458.
- **Dane Odoo15:** logi list 374, 376, 387 – „0 znaleziono” przy 1, 11, 11 pozycjach utworzonych lub pominiętych.

### IMP-06 · Gałąź `import_invoices` bez kontroli duplikatów · [kod]
- **Gdzie:** l. 4474–4489 (`_handle_ksef_success`, backend java).
- **Stan:** `create` logu potomnego dla każdego `ksefNumber`, bez sprawdzenia faktury ani logu.

### IMP-07 · Sprawdzenie istniejącej faktury · [kod]
- **Gdzie:** l. 1609, l. 4350.
- **Stan:** `move_type = 'in_invoice'`; dokumenty `in_refund` nie są uwzględniane.

### IMP-08 · Log listy po zakończeniu · [kod] [dane]
- **Stan:** `ksef_operation = completed`, `state` pozostaje `draft` (utworzenie l. 4866).
- **Dane Odoo15:** 352 logi list w `draft`, wszystkie `completed`.

---

## KOL – kolejka i obsługa błędów

### KOL-01 · Limit prób nie jest sprawdzany w ścieżce python · [kod]
- **Gdzie:** l. 1703, 2019, 2075, 2202, 2266 (`ksef_retry_count + 1`, `ksef_next_execution + 5 min`); pole `ksef_max_retries` l. 378 (domyślnie 3).
- **Stan:** `ksef_max_retries` sprawdzane w `_handle_ksef_error` (l. 4569, backend java) i w `cron_ksef_monitor_failures` (l. 758). Domena kolejki (l. 844–850) nie uwzględnia liczby prób.
- **Dane `kape15_rc1_231221`** (rekord 805, przekazany przez użytkownika): `ksef_retry_count = 10`, `ksef_max_retries = 3`, `ksef_status = failed`, `ksef_operation = import_list`, utworzony 10.10.2026.

### KOL-02 · Brak rozróżnienia HTTP 429 · [kod]
- **Gdzie:** `communication_provider_ksef_apiservice.py` l. 1167 (`raise UserError(f"KSeF API Error: …")`); `get_received_invoices` l. 939.
- **Stan:** kod HTTP i nagłówki odpowiedzi nie są przekazywane dalej; 429 obsługiwane jak każdy błąd (ponowienie po 5 min). `context_updates` z `_process_import_list` (l. 1565–1580) nie są zapisywane.
- **Uwaga użytkownika:** potrzebny rejestr błędów według typu z sugerowanym postępowaniem.

### KOL-03 · Licznik przetworzonych w cronie · [kod]
- **Gdzie:** l. 874 (`if success:`), l. 878 (limit 5).
- **Stan:** `_process_single_ksef_step` zwraca słownik; `{"success": False}` też zwiększa licznik.

### KOL-04 · Kolejność kandydatów · [kod]
- **Gdzie:** l. 859 (`order='create_date, parent_id asc, create_date asc'`, `limit=20`).
- **Stan:** najstarsze rekordy, także ponawiane bez końca (KOL-01), są pobierane jako pierwsze.

---

## ST – stany

### ST-01 · Stany opisane, a niewystępujące · [kod]
- **Gdzie:** `ARCHITECTURE.md` l. 123–127; `communication_log.py` l. 133.
- **Stan:** opis wymienia `retry` i `waiting_delay` jako stany; pole `state` ich nie ma. `waiting_delay` jest wartością `ksef_status` i nie jest ustawiane w kodzie Python modułu.

### ST-02 · Stany i metody nieużywane · [kod]
- **Stan:** `mark_generated`, `mark_validated`, `mark_queued` (`communication_log.py`) nie są wywoływane; `validated` nie jest ustawiany; `generated` ustawia tylko `invoice.py` l. 564.

### ST-03 · Nieprawidłowa wartość `status` · [kod]
- **Gdzie:** `communication_provider_ksef_offline.py` l. 159 (`"status": "superseded"`); pole `status` w `communication_log.py` l. 109 (success, warning, error).
- **[hipoteza]** zapis kończy się błędem walidacji pola wyboru przy przejściu w tryb offline; nie testowano.

### ST-04 · `ksef_process_state` faktury · [kod]
- **Gdzie:** `communication_provider_ksef_base.py` l. 269–270.
- **Stan:** compute zależy tylko od `ksef_log_id.ksef_status`; zmiany `state`, `ksef_operation`, `is_processing` bez zmiany `ksef_status` nie przeliczają pola. Wartość `offline` nie jest ustawiana.

### ST-05 · Stany sprawdzane przy offline · [kod]
- **Gdzie:** `account_move_ksef_qr.py` l. 585.
- **Stan:** `last_online_log.state in ("sent", "confirmed", "completed")` – `confirmed` i `completed` nie są wartościami `state`.

### ST-06 · Stany szablonu · [kod]
- **Gdzie:** `xml_template.py` l. 77.
- **Stan:** `ready`, `error`, `cancel` nie są ustawiane; `imported` w `xml_import_template.py` l. 93, 107; `draft` w `xml_template.py` l. 1605.

---

## SEC – uprawnienia

### SEC-01 · `communication.log` tylko dla administratora · [kod]
- **Gdzie:** `security/ir.model.access.csv`; `invoice.py` l. 588 (`sudo().create(log_vals)`).
- **Stan:** prawa do `communication.log` tylko `base.group_system`; eksport z faktury tworzy log przez `sudo()`.

### SEC-02 · Menu importu JSON · [kod]
- **Gdzie:** `wizard/wizard_template_import_json_menu.xml`; `views/menu.xml`.
- **Stan:** pozycja z grupą `base.group_user` pod menu `base.group_system`. ACL kreatora bez grupy (wszyscy, pełny dostęp).

---

## DEAD – kod nieużywany lub niedokończony

### DEAD-01 · Klienci API nieimportowani · [kod]
- **Gdzie:** `models/__init__.py` l. 36 (import `ksef_api_client` zakomentowany); `ksef_v2_client.py` – brak importu.

### DEAD-02 · Wielokrotne definicje metod · [kod]
- **Stan:** `_is_token_valid` l. 1090, 1227; `_handle_ksef_error` l. 1416, 1423, 4538 (działa ostatnia); `_get_xml_value` w `communication_provider_ksef_addons.py` l. 289, 1850; `map_invoice_type` w addons l. 1935 i w l. 182.

### DEAD-03 · Pola bez użycia w logice · [kod]
- **Stan:** `communication.provider.trigger_type` (l. 142) i `cron_id` (l. 164) w `communication_provider.py`; `communication.provider.ksef.api_mode` (l. 5000).

### DEAD-04 · Widoki spoza manifestu · [kod]
- **Stan:** `views/communication_channel_views.xml`, `communication_provider_peppol_views.xml`, `communication_provider_poweroffice_views.xml`, `ksef_connection_test_result_views.xml`, `ksef_invoice_offline.xml`, `report_invoice.xml`.

### DEAD-05 · Cron trybu offline · [kod]
- **Gdzie:** `communication_provider_ksef_offline.py` l. 187 (`cron_ksef_offline_monitor`).
- **Stan:** brak rekordu `ir.cron`; przejście `offline_pending → queued` nie jest uruchamiane cyklicznie.

---

## DOC – dokumentacja w repozytorium

### DOC-01 · Wersja Odoo w README · [kod]
- **Gdzie:** `README.md` l. 127 („Odoo 18+”) w gałęzi 15.0.

### DOC-02 · `docs/README.rst` · [kod]
- **Stan:** treść w Markdown w pliku `.rst`.

---

## Obserwacje z danych (Odoo15, KAPE, 19.10.2026)

| Element | Wartość |
|---|---|
| Providery KSeF | 4, aktywny 1 (id 4, konfiguracja 18) |
| Konfiguracja 18 | `api_backend = python`, `api_mode = java_only`, `import_days_back = 4`, `import_frequency_hours = 12`, `import_page_size = 100` |
| Crony 41–45 | nieaktywne; 41 i 42 – `lastcall` 19.10.2026 11:33 i 11:32 |
| `communication.log` | 375 (import): 352 listy `draft`, 23 dzieci `received`; wszystkie `completed`/`success` |
| Logi eksportu | 0 |
| `xml.export.template` | 4, `draft` |

## Do weryfikacji na instancji

1. ST-03 – zachowanie zapisu `status = superseded` przy wystawieniu offline.
2. IMP-01 – duplikaty w bazie `kape15_rc1_231221`: grupowanie po `ksef_invoice_number` i `parent_id`.
3. Czy wysyłka do KSeF (eksport) jest używana na 15.0 – brak logów eksportu na Odoo15.
4. Czy backend `java` jest używany na którejkolwiek instancji 15.0 (IMP-06, KOL-01).
5. DEAD-04 – czy widoki spoza manifestu są pozostałością, czy planowanym elementem.

## Dokumentacja – stan i otwarte punkty

| Element | Stan |
|---|---|
| Strony HTML (7) | gotowe, `static/description/doc/` |
| BPMN (3) | gotowe, `docs/bpmn/`; import bez ostrzeżeń |
| README.md | gotowe, po polsku |
| `static/description/index.html` | gotowe, po polsku, klasy zgodne z Bootstrap 4 (Odoo 15) |
| Dane instancji na stronach HTML | do decyzji: dokumentacja w `static/` jest publiczna |
| Stare pliki (`ARCHITECTURE.md`, `docs/*.md`, `docs/README.rst`) | do usunięcia przez użytkownika |
| Rejestr błędów KSeF (KOL-02) | do zaprojektowania |

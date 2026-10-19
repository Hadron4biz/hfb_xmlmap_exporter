# eXtensible Exchange Template Base Provider (`hfb_xmlmap_exporter`)

Moduł Odoo 15 do mapowania pól modeli Odoo na strukturę XML opisaną schematem XSD (XET – eXtensible Exchange Template), rejestrowania wymiany dokumentów w kolejce komunikacji i obsługi Krajowego Systemu e-Faktur (KSeF 2.0): wysyłki faktur, pobierania UPO, importu faktur zakupowych, trybu offline i kodów QR.

---

## Informacje o module

| | |
|---|---|
| Nazwa techniczna | `hfb_xmlmap_exporter` |
| Wersja | 15.1.6 |
| Autor | Andrzej Wiśniewski |
| Strona | https://wisand.eu |
| Licencja | AGPL-3 |
| Aplikacja | tak |

### Zależności

`base`, `mail`, `sale`, `account`

---

## Funkcje

**XET**
- szablon `xml.export.template` z drzewem węzłów `xml.export.node`, przestrzeniami nazw i typami XSD,
- tworzenie szablonu z pliku XSD (kreator „Konwersja XSD → XET”, import struktury i typów),
- import i eksport szablonu w formacie `.xet.json` (w `data/` szablony FA(3): VAT, KOR, ROZ),
- generowanie XML dla rekordu (`generate_xml`) i walidacja faktury względem XSD z dziennikiem `xml.validation.log`.

**Komunikacja**
- `communication.provider` – dostawca z typem `localdir` lub `ksef` i wskazaniem konfiguracji,
- `communication.log` – jeden rekord na operację wymiany (eksport lub import),
- provider LocalDir – zapis pliku w katalogu serwera.

**KSeF**
- wysyłka faktury: `auth → open_session → send_invoice → check_status → download_upo → close_session`,
- import faktur: log listy (zapytanie o metadane) i logi potomne (pobranie XML, odtworzenie `account.move`),
- dwa backendy: `python` (`ProviderKsefApiService`) i `java` (klient JAR uruchamiany z Odoo),
- tryb offline (`communication.provider.ksef.offline`), kody QR, raport UPO, podgląd faktury z XML,
- import certyfikatów (kreator `ksef.certificate.import.wizard`), pobranie kluczy publicznych MF.

---

## Model danych

| Model | Przeznaczenie |
|---|---|
| `xml.export.template` | szablon XET |
| `xml.export.node` | węzeł szablonu (źródło wartości, pętle) |
| `xml.export.namespace` | przestrzeń nazw szablonu |
| `xml.xsd.type`, `xml.xsd.element` | typy i elementy zaimportowane z XSD |
| `xml.validation.log` | wynik walidacji faktury |
| `xml.template.exporter` | eksporter szablonu |
| `communication.provider` | dostawca komunikacji |
| `communication.log` | operacja wymiany (kolejka, stan, kroki KSeF) |
| `communication.provider.localdir` | konfiguracja LocalDir |
| `communication.provider.ksef` | konfiguracja KSeF |
| `communication.provider.ksef.offline` | tryb offline KSeF |

Rozszerzenia modeli standardowych:

| Model | Dodane |
|---|---|
| `account.move` | `ksef_number`, `ksef_log_id`, `ksef_process_state`, `ksef_issue_mode`, `xml_export_template_id`, `xsd_validation_state`, pola korekt i zaliczek; akcje eksportu, walidacji, offline, korekty, podglądu |
| `account.move.line` | pola korekt i pola pomocnicze FA(3) |
| `sale.order`, `sale.advance.payment.inv`, `res.partner`, `res.company` | pola pomocnicze KSeF |

---

## Przepływ

### Stany `communication.log`

```
eksport: generated → queued → sent → received
         (error, superseded – tryb offline, offline_pending → queued)
import:  draft → queued → received   (log potomny)
         draft                        (log listy)
```

| Stan | Etykieta |
|---|---|
| `draft` | Szkic |
| `generated` | Wygenerowano |
| `validated` | Zwalidowano |
| `queued` | W kolejce |
| `sent` | Wysłano |
| `received` | Odebrano |
| `superseded` | Zastąpiony inną operacją |
| `offline_pending` | Offline – oczekuje na dosłanie |
| `error` | Błąd |

Kroki KSeF są w polach `ksef_operation`, `ksef_next_operation` i `ksef_status` (`pending`, `in_progress`, `success`, `failed`, `waiting_delay`).

### Zadania cykliczne (`views/cron.xml`, domyślnie nieaktywne)

| Nazwa | Metoda | Interwał |
|---|---|---|
| Provider KSeF: Communication Queue | `_cron_process_ksef_queue` | 1 min |
| Provider KSeF: Schedule Import List | `_cron_ksef_schedule_import_list` | 1 h |
| Provider KSeF – Environment Health Check | `cron_ksef_environment_check` | 1 h |
| Provider KSeF – Communication Report | `cron_ksef_daily_report` | 1 dzień |
| Provider KSeF – Monitor Health Check | `cron_ksef_monitor_failures` | 1 h |

---

## Interfejsy

- API KSeF 2.0: adres w polu `base_url` konfiguracji (domyślnie `https://api-test.ksef.mf.gov.pl/api/v2`), środowisko `test` lub `production`,
- klient Java: katalog z plikami JAR w polu `jar_directory` (backend `java`),
- katalog lokalny: konfiguracja `communication.provider.localdir`.

---

## Konfiguracja

1. Konfiguracja → Konfiguracja Dostawców → Provider KSeF: środowisko, adres API, typ autoryzacji, backend (`python` lub `java`), parametry importu.
2. Na konfiguracji KSeF: „Importuj certyfikaty” lub token, „Pobierz klucze publiczne MF”.
3. Konfiguracja → Dostawcy Usług: provider typu `ksef` i wybór konfiguracji.
4. Szablony: szablon XET (z XSD lub JSON) z przypisanym providerem; szablon na fakturze w polu `xml_export_template_id`.
5. Zadania cykliczne KSeF: włączenie w Ustawieniach technicznych.

---

## Menu

```
🧩 XET Provider
├── 📑 Szablony
├── ✨ Kreatory
│   ├── 📋 Import szablonu XET JSON
│   └── 💠 Konwersja XSD → XET
├── ♻️ Logi komunikacji
└── 🦺 Konfiguracja
    ├── Dostawcy Usług
    ├── Konfiguracja Dostawców
    │   ├── Provider KSeF
    │   └── Provider LocalDir
    └── Węzły [node]
```

Menu główne i pozycje mają grupę `base.group_system`, z wyjątkiem „Import szablonu XET JSON” (`base.group_user`).

---

## Prawa dostępu

| Grupa | Dostęp |
|---|---|
| `base.group_user` | szablony, węzły, przestrzenie nazw (R/W/C); konfiguracje LocalDir, KSeF, offline (pełny); odczyt `xml.validation.log`; kreatory |
| `hfb_xmlmap_exporter.group_xml_export_admin` | szablony, węzły, przestrzenie nazw, eksporter (pełny) |
| `base.group_system` | `communication.log`, `communication.provider`, typy XSD, kreator importu XSD, `xml.validation.log` (pełny) |

Reguła `rule_communication_provider_read`: odczyt `communication.provider` dla `base.group_user`.

---

## Struktura modułu

```
hfb_xmlmap_exporter/
├── __manifest__.py
├── models/       XET, komunikacja, KSeF
├── wizard/       kreatory XSD, JSON, konfiguracji, certyfikatów
├── reports/      podgląd faktury KSeF z XML
├── views/        widoki, menu, crony, szablony UPO i QR
├── data/         szablony XET FA(3) w JSON
├── security/     grupy, ACL, reguły
└── static/       opis modułu, dokumentacja, zasoby JS
```

---

## Dokumentacja

Dokumentacja UML i BPMN (po polsku): `static/description/doc/index.html`, w zainstalowanym module pod adresem `/hfb_xmlmap_exporter/static/description/doc/index.html`. Pliki BPMN 2.0 dla Camunda Modeler: `docs/bpmn/*.bpmn`. Uwagi i rozbieżności: `DALSZE_PRACE.md`.

---

## Licencja

AGPL-3 – GNU Affero General Public License v3, https://www.gnu.org/licenses/agpl-3.0.html

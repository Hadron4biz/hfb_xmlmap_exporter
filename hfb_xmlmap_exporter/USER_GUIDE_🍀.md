# Integracja Odoo z KSeF 2.0 / Odoo Integration with KSeF 2.0

---

## Spis treści / Table of Contents

1. [Wymagania przed instalacją / Prerequisites](#wymagania-przed-instalacją--prerequisites)
2. [Instalacja / Installation](#instalacja--installation)
3. [Weryfikacja po instalacji / Post-Installation Verification](#weryfikacja-po-instalacji--post-installation-verification)
4. [Konfiguracja Odoo (globalna) / Odoo Global Configuration](#konfiguracja-odoo-globalna--odoo-global-configuration)
5. [Konfiguracja modułu / Module Configuration](#konfiguracja-modułu--module-configuration)
6. [Operacje użytkownika (faktura) / User Operations (Invoice)](#operacje-użytkownika-faktura--user-operations-invoice)
7. [Automatyzacja / Automation](#automatyzacja--automation)
8. [Kontrola procesu / Process Monitoring](#kontrola-procesu--process-monitoring)
9. [Rozwiązywanie problemów / Troubleshooting](#rozwiązywanie-problemów--troubleshooting)
10. [Testowanie / Testing](#testowanie--testing)
11. [Struktura repozytorium / Repository Structure](#struktura-repozytorium--repository-structure)
12. [Wsparcie / Support](#wsparcie--support)
13. [Licencja / License](#licencja--license)
14. [Zmiany / Changelog](#zmiany--changelog)

---

## Wymagania przed instalacją / Prerequisites

### Systemowe / System
- Odoo 18+ (Community / Enterprise)
- Python 3.8 lub nowszy / Python 3.8 or newer
- OpenSSL (do generowania certyfikatów / for certificate generation)
- Dostęp do Internetu (endpointy KSeF) / Internet access (KSeF endpoints)

### Zależności Odoo / Odoo Dependencies
- `lxml` (wbudowane / built-in)
- `cryptography` (do obsługi certyfikatów / for certificate handling)
- `requests` (do komunikacji API / for API communication)

### Wymagane uprawnienia / Required Permissions
- Dostęp do konsoli systemowej (dla instalacji zależności) / System console access (for dependency installation)
- Uprawnienia administratora w Odoo / Odoo administrator privileges
- Certyfikaty do autentykacji i podpisu wystawione w środowisku Aplikacji Podatnika KSeF 2.0 https://ksef.podatki.gov.pl/informacje-ogolne-ksef-20/certyfikaty-ksef/
  https://github.com/CIRFMF/ksef-docs/blob/main/certyfikaty-KSeF.md

---

## Instalacja / Installation

### Metoda 1: Z repozytorium GitHub / Method 1: From GitHub Repository

- Klonowanie repozytorium do katalogu addons
- Clone repository to addons directory
cd /path/to/odoo/addons
git clone https://github.com/Hadron4biz/hfb_xmlmap_exporter.git

- Instalacja zależności Python
- Install Python dependencies
pip install cryptography requests

- Restart Odoo
sudo systemctl restart odoo

### Metoda 2: Jako archiwum ZIP / Method 2: As ZIP Archive

- Pobierz ZIP z / Download ZIP from: https://github.com/Hadron4biz/hfb_xmlmap_exporter
- Rozpakuj do katalogu addons Odoo / Extract to Odoo addons directory
- Zainstaluj zależności / Install dependencies: pip install cryptography requests
- Restart Odoo

### Instalacja modułu w Odoo / Module Installation in Odoo
- Przejdź do Aplikacje → odśwież listę modułów / Go to Apps → refresh module list
- Wyszukaj hfb_xmlmap_exporter / Search for hfb_xmlmap_exporter
- Kliknij Instaluj / Click Install

### Weryfikacja po instalacji / Post-Installation Verification
- Po instalacji wykonaj skrypt weryfikacyjny, który sprawdzi poprawność konfiguracji środowiska:
- After installation, run the verification script to check environment configuration:

cd /path/to/odoo/addons/hfb_xmlmap_exporter
python3 sprawdz-po-instalacji.py

- Skrypt weryfikuje / The script verifies:
✔️ Wersję Pythona i wymagane biblioteki / Python version and required libraries
✔️ Połączenie z testowymi endpointami KSeF / Connection to KSeF test endpoints
✔️ Istnienie wymaganych katalogów / Required directories existence
✔️ Poprawność konfiguracji Odoo / Odoo configuration correctness

Oczekiwany wynik / Expected output:

	# ./sprawdz-po-instalacji.py --mode host .

	🔧 Rozpoczynanie weryfikacji dla trybu: HOST

	🔍 Sprawdzanie: System operacyjny... ✅
	🔍 Sprawdzanie: Zasoby sprzętowe... ✅
	🔍 Sprawdzanie: Java... ✅
	🔍 Sprawdzanie: Struktura modułu... ✅
	🔍 Sprawdzanie: Pakiety Python... 
	📦 Analizowanie zależności Python w module...
		ℹ️  Moduł communication_provider_ksef_apiservice - pominięto (lokalny moduł własny)

		Znaleziono 6 zewnętrznych zależności
		Pominięto 1 modułów standardowych/własnych
	✅
	🔍 Sprawdzanie: Biblioteki systemowe... ✅

	============================================================
	📋 RAPORT WERYFIKACJI MODUŁU ODOO
	============================================================
	Moduł: .
	Tryb instalacji: host
	Status: ✅ System gotowy do instalacji!
	------------------------------------------------------------
	Podsumowanie:
	  ✅ Przeszło: 6
	  ⚠️  Ostrzeżenia: 0
	  ❌ Błędy: 0
	------------------------------------------------------------

## Konfiguracja modułu / Module Configuration

### 4.1 Schemy i mapowanie / Schemas and Mapping

#### Import schemy XSD / Import XSD Schema

1. Przejdź do **KSeF → Konfiguracja → Schemy XSD** / Go to **KSeF → Configuration → XSD Schemas**
2. Kliknij **Importuj** / Click **Import**
3. Wprowadź / Enter:
   - **Nazwa / Name**: `KSeF FA (2.0)`
   - **Wersja / Version**: `2.0`
   - **URL**: `https://ksef.mf.gov.pl/scheme/fa/2.0/FA.xsd`
4. Kliknij **Pobierz i zweryfikuj** / Click **Download and Validate**

#### Konfiguracja XET (XML Export Template) / Configure XET (XML Export Template)

XET to szablon mapowania danych z modeli Odoo do struktury XML KSeF / XET is a mapping template from Odoo models to KSeF XML structure.

1. Przejdź do **KSeF → Konfiguracja → Szablony XET** / Go to **KSeF → Configuration → XET Templates**
2. Kliknij **Utwórz** / Click **Create**
3. Wprowadź / Enter:
   - **Nazwa / Name**: `Faktura KSeF 2.0` / `Invoice KSeF 2.0`
   - **Model źródłowy / Source Model**: `account.move` (faktury / invoices)
   - **XSD Schema**: wybierz wcześniej zaimportowaną / select previously imported schema

#### Import istniejącego XET / Import Existing XET

Jeśli posiadasz gotowy plik XET (`.xet` lub `.xml`) / If you have a ready XET file (`.xet` or `.xml`):

1. W formularzu szablonu kliknij **Importuj XET** / In the template form, click **Import XET**
2. Wybierz plik z dysku / Select file from disk
3. Kliknij **Zweryfikuj strukturę** / Click **Validate Structure**

#### Eksport XET / Export XET

Aby wyeksportować szablon do ponownego użycia / To export template for reuse:

1. Otwórz szablon XET / Open XET template
2. Kliknij **Eksportuj XET** / Click **Export XET**
3. Zapisz plik na dysku / Save file to disk

---

### 4.2 Warstwa integracyjna (Provider) / Integration Layer (Provider)

Provider definiuje połączenie z rzeczywistym środowiskiem KSeF / Provider defines connection to actual KSeF environment.

#### Krok 1: Generowanie certyfikatów / Step 1: Certificate Generation

Szczegółowy opis procesu generowania certyfikatów dla KSeF 2.0 znajduje się w pliku / Detailed description of the certificate generation process for KSeF 2.0 is available in the file:

**`docs/przygotowanie-certyfikatow.md`**

Plik zawiera kompletną instrukcję przygotowania certyfikatów PKCS#12 (.p12) na potrzeby integracji z KSeF, obejmującą:

- Wymagania techniczne – certyfikaty muszą być oparte o algorytm RSA
- Sprawdzanie algorytmu certyfikatu przed użyciem
- Tworzenie plików .p12 dla certyfikatów AUTH i SIGN
- Weryfikację poprawności utworzonych plików
- Wgrywanie certyfikatów do konfiguracji Providera
- Rozwiązywanie najczęstszych problemów

The file contains complete instructions for preparing PKCS#12 (.p12) certificates for KSeF integration, including:

- Technical requirements – certificates must use RSA algorithm
- Certificate algorithm verification before use
- Creating .p12 files for AUTH and SIGN certificates
- Verification of created files
- Uploading certificates to Provider configuration
- Troubleshooting common issues

> ⚠️ **Ważne / Important**: Klucz prywatny musi być w formacie PEM i może być zabezpieczony hasłem (do skonfigurowania w Providerze) / Private key must be in PEM format and can be password-protected (configurable in Provider).

#### Krok 2: Utworzenie Providera / Step 2: Create Provider

1. Przejdź do **KSeF → Konfiguracja → Providerzy** / Go to **KSeF → Configuration → Providers**
2. Kliknij **Utwórz** / Click **Create**
3. Wprowadź / Enter:
   - **Nazwa / Name**: `KSeF Produkcja` / `KSeF Production` lub / or `KSeF Test`
   - **Tryb / Mode**: `Test` / `Produkcja` / `Production`
   - **Endpoint / Endpoint**: 
     - Test: `https://ksef-test.mf.gov.pl/api/online`
     - Produkcja / Production: `https://ksef.mf.gov.pl/api/online`
   - **NIP / Tax ID**: numer NIP firmy / company Tax ID

#### Krok 3: Wgranie certyfikatów / Step 3: Upload Certificates

W formularzu Providera / In the Provider form:

1. W sekcji **Certyfikaty** / In **Certificates** section:
   - **Klucz prywatny / Private Key**: wklej zawartość pliku `klucz_prywatny.pem` / paste content of `private_key.pem`
   - **Hasło klucza / Key Password**: jeśli klucz jest zabezpieczony / if key is password-protected
   - **Certyfikat publiczny / Public Certificate**: wklej zawartość otrzymanego certyfikatu / paste received certificate content

2. Kliknij **Zweryfikuj certyfikaty** / Click **Validate Certificates**

Moduł sprawdzi / Module checks:
- Poprawność formatu PEM / Correct PEM format
- Ważność certyfikatu (daty) / Certificate validity (dates)
- Zgodność klucza z certyfikatem / Key and certificate match

#### Krok 4: Powiązanie Providera z szablonami / Step 4: Link Provider with Templates

1. W formularzu Providera przejdź do zakładki **Szablony XET** / In Provider form, go to **XET Templates** tab
2. Dodaj wiersz i wybierz szablon `Faktura KSeF 2.0` / Add line and select `Invoice KSeF 2.0` template
3. Zapisz / Save

---

## Operacje użytkownika (faktura) / User Operations (Invoice)

### Przypisanie szablonu do faktury / Assign Template to Invoice

Na formularzu faktury (`account.move`) / On invoice form (`account.move`):

1. Przejdź do zakładki **KSeF** / Go to **KSeF** tab
2. Wybierz **Provider** (jeśli więcej niż jeden) / Select **Provider** (if multiple)
3. Wybierz **Szablon XET** (domyślnie przypisany z Providera) / Select **XET Template** (default from Provider)

### Weryfikacja dokumentu / Document Validation

Przed wysyłką możesz sprawdzić poprawność składni / Before sending, you can validate syntax:

1. Na fakturze kliknij **KSeF → Weryfikuj składnię** / On invoice, click **KSeF → Validate Syntax**
2. Moduł sprawdzi / Module checks:
   - Kompletność wymaganych pól / Required fields completeness
   - Poprawność struktur XML / XML structure correctness
   - Zgodność z XSD / XSD compliance

Wynik weryfikacji pojawi się jako komunikat / Validation result appears as message:
- ✅ *Dokument jest poprawny składniowo* / *Document is syntactically correct*
- ❌ *Błędy: [lista brakujących pól]* / *Errors: [list of missing fields]*

### Wysłanie do kolejki / Send to Queue

Aby wysłać fakturę / To send invoice:

1. Kliknij **KSeF → Wyślij do KSeF** / Click **KSeF → Send to KSeF**
2. Dokument trafi do kolejki z statusem `Oczekuje` / Document enters queue with status `Pending`
3. System zwróci identyfikator zadania / System returns task identifier

### Kontrola statusu wysyłki / Send Status Monitoring

Statusy faktury w procesie KSeF / Invoice statuses in KSeF process:

| Status | Opis / Description |
|--------|---------------------|
| `Oczekuje` / `Pending` | W kolejce do wysyłki / In queue for sending |
| `Wysłano` / `Sent` | Wysłano, oczekuje na potwierdzenie / Sent, awaiting confirmation |
| `Zatwierdzono` / `Confirmed` | KSeF potwierdził przyjęcie / KSeF confirmed receipt |
| `Odrzucono` / `Rejected` | Odrzucona – sprawdź komunikat błędu / Rejected – check error message |
| `Błąd` / `Error` | Błąd techniczny – sprawdź logi / Technical error – check logs |

Status widoczny jest na formularzu faktury oraz w widoku **KSeF → Kolejka wysyłek** / Status visible on invoice form and in **KSeF → Send Queue** view.

---

## Automatyzacja / Automation

### Konfiguracja cronów / Cron Configuration

Moduł udostępnia dwa zadania cron / Module provides two cron jobs:

1. **Wysyłka faktur do KSeF** / **Send invoices to KSeF**
   - Zadanie / Job: `ksef.auto.send`
   - Domyślny interwał / Default interval: co 5 minut / every 5 minutes
   - Opis / Description: przetwarza faktury w statusie `Oczekuje` / processes invoices with status `Pending`

2. **Odbiór potwierdzeń z KSeF** / **Receive confirmations from KSeF**
   - Zadanie / Job: `ksef.auto.receive`
   - Domyślny interwał / Default interval: co 10 minut / every 10 minutes
   - Opis / Description: pobiera statusy wysłanych faktur / fetches statuses of sent invoices

#### Konfiguracja w Odoo / Configure in Odoo

1. Przejdź do **Ustawienia → Techniczne → Automatyzacja → Zaplanowane akcje** / Go to **Settings → Technical → Automation → Scheduled Actions**
2. Znajdź zadania z prefiksem `ksef.` / Find jobs with `ksef.` prefix
3. Dostosuj interwał (w minutach) i aktywność / Adjust interval (minutes) and activity status

#### Ręczne uruchomienie / Manual Trigger

W trybie debug / In debug mode:
- **KSeF → Operacje → Wyślij oczekujące** / **KSeF → Operations → Send Pending**
- **KSeF → Operacje → Odśwież statusy** / **KSeF → Operations → Refresh Statuses**

---

## Kontrola procesu / Process Monitoring

### Monitoring statusu wysyłki / Send Status Monitoring

**Widok listy faktur** / **Invoice list view**:
- Dodatkowa kolumna `Status KSeF` / Additional column `KSeF Status`
- Kolorowe oznaczenia / Color coding:
  - 🟡 Żółty / Yellow – oczekuje / pending
  - 🔵 Niebieski / Blue – w trakcie / in progress
  - 🟢 Zielony / Green – zatwierdzono / confirmed
  - 🔴 Czerwony / Red – błąd/odrzucono / error/rejected

**Widok szczegółowy faktury** / **Invoice detail view**:
- Pełna historia komunikacji z KSeF / Full communication history with KSeF
- Data wysyłki, ID referencyjne / Send date, reference ID
- Komunikaty błędów (jeśli wystąpiły) / Error messages (if any)

### Weryfikacja odpowiedzi KSeF / KSeF Response Verification

Dla każdej wysyłki moduł przechowuje / For each send, module stores:

- **Request XML** – wysłany dokument / sent document
- **Response XML** – odpowiedź z KSeF / KSeF response
- **Referencja KSeF** – unikalny identyfikator nadany przez system / unique identifier from system
- **Data potwierdzenia** – timestamp z KSeF / timestamp from KSeF

Dostęp do logów / Log access: **KSeF → Historia wysyłek** / **KSeF → Send History**

---

## Rozwiązywanie problemów / Troubleshooting

### Najczęstsze błędy / Common Errors

#### 1. Błąd certyfikatu: `Invalid certificate format` / Certificate error: `Invalid certificate format`

**Przyczyna / Cause**: Nieprawidłowy format PEM / Incorrect PEM format.

**Rozwiązanie / Solution**:
- Upewnij się, że certyfikat zawiera znaczniki `-----BEGIN CERTIFICATE-----` i `-----END CERTIFICATE-----` / Ensure certificate contains markers
- Klucz prywatny musi być w formacie PKCS#8 / Private key must be in PKCS#8 format

#### 2. Błąd połączenia: `Connection refused` / Connection error: `Connection refused`

**Przyczyna / Cause**: Brak dostępu do endpointów KSeF / No access to KSeF endpoints.

**Rozwiązanie / Solution**:
- Sprawdź ustawienia proxy w Odoo (jeśli stosowane) / Check Odoo proxy settings (if applicable)
- Zweryfikuj firewalle: endpointy KSeF używają portu 443 / Verify firewalls: KSeF endpoints use port 443
- Przetestuj ręcznie / Test manually: `curl https://ksef-test.mf.gov.pl/api/online`

#### 3. Błąd: `Missing required field: Nabywca.NIP` / Error: `Missing required field: Buyer.TaxID`

**Przyczyna / Cause**: Faktura nie zawiera wymaganych danych kontrahenta / Invoice missing required partner data.

**Rozwiązanie / Solution**:
- Uzupełnij NIP, nazwę i adres na fakturze / Fill Tax ID (NIP), name, and address on invoice
- Dla klientów zagranicznych – pole `Kod VAT UE` / For foreign customers – use `EU VAT Code` field

#### 4. Błąd: `XML does not conform to XSD` / Error: `XML does not conform to XSD`

**Przyczyna / Cause**: Struktura XML niezgodna ze schemą KSeF / XML structure not compliant with KSeF schema.

**Rozwiązanie / Solution**:
- Uruchom ponownie weryfikację składni / Run syntax validation again
- Sprawdź logi w **KSeF → Historia wysyłek** / Check logs in **KSeF → Send History**
- Zweryfikuj mapowanie w szablonie XET / Verify mapping in XET template

#### 5. Błąd: `Certificate expired` / Error: `Certificate expired`

**Przyczyna / Cause**: Certyfikat utracił ważność / Certificate has expired.

**Rozwiązanie / Solution**:
- Wygeneruj nowy certyfikat / Generate new certificate
- Zaktualizuj konfigurację Providera / Update Provider configuration
- Sprawdź datę ważności w panelu certyfikatów / Check expiration date in certificate panel

### Logi systemowe / System Logs

Logi Odoo / Odoo logs: `odoo.log` – szukaj wpisów z tagiem `ksef` / look for entries with `ksef` tag

tail -f /var/log/odoo/odoo.log | grep ksef


---

## Testowanie / Testing

### Środowisko testowe / Test Environment

1. Skonfiguruj Provider w trybie **Test** / Configure Provider in **Test** mode
2. Endpoint testowy / Test endpoint: `https://ksef-test.mf.gov.pl/api/online`
3. Użyj certyfikatów testowych (można wygenerować samodzielnie) / Use test certificates (can be self-generated)

### Przykładowa faktura testowa / Sample Test Invoice

Utwórz fakturę z minimalnymi danymi / Create invoice with minimal data:
- **Kontrahent / Partner**: NIP / Tax ID `1234567890`, nazwa / name "Firma Testowa" / "Test Company"
- **Produkt / Product**: "Usługa testowa" / "Test Service", netto / net 100.00, VAT 23%
- **Data wystawienia / Issue Date**: bieżąca / current

### Scenariusze testowe / Test Scenarios

| Scenariusz / Scenario | Oczekiwany rezultat / Expected Result |
|------------------------|--------------------------------------|
| Poprawna faktura / Correct invoice | Status `Zatwierdzono` / `Confirmed` |
| Brak NIP kontrahenta / Missing partner Tax ID | Błąd walidacji przed wysyłką / Validation error before send |
| Przekroczony limit wysyłek (test) / Exceeded send limit (test) | Odrzucenie z komunikatem / Rejection with message |
| Wygaśnięty certyfikat / Expired certificate | Błąd autoryzacji / Authorization error |

---

## Struktura repozytorium / Repository Structure
	.
	├── bash
	├── data 
	├── docs
	│   ├── graph
	│   └── other
	├── models
	├── security
	├── static
	│   ├── description
	│   ├── img
	│   ├── src
	│   │   ├── java
	│   │   │   └── pl
	│   │   │       └── ksef
	│   │   │           ├── auth
	│   │   │           ├── invoice
	│   │   │           └── session
	│   │   └── js
	│   └── tests
	├── tests
	├── views
	└── wizard

- W katalogu `data` znajdują się przykładowe szablony XET / Sample XET templates are located in the `data` directory
- W katalogu `static/src/java` znajdują się kody źródłowe Java do skompilowania klienta KSeF / Java source code for compiling the KSeF client is located in the `static/src/java` directory

---

### Instalacja środowiska Java / Java Environment Installation

Moduł wykorzystuje klienta Java do komunikacji z API KSeF. Przed kompilacją i użyciem należy zainstalować środowisko Java / The module uses a Java client for KSeF API communication. Before compilation and use, install the Java environment.

#### 1. Instalacja Java / Install Java
	sudo apt update
	sudo apt upgrade -y
	sudo apt install -y openjdk-17-jdk openjdk-17-jre
	java -version

#### 2. Ustawienie domyślnej wersji Java / Set default Java version
	sudo update-alternatives --config java
	sudo update-alternatives --config javac

	# Ustaw domyślną wersję (np. OpenJDK 17) / Set default version (e.g., OpenJDK 17)
	sudo update-java-alternatives -s java-1.17.0-openjdk-amd64

#### 3. Ustawienie środowiska / Set environment variables
	# Dodaj JAVA_HOME do ~/.bashrc / Add JAVA_HOME to ~/.bashrc
	echo 'export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"' >> ~/.bashrc
	echo 'export PATH="$JAVA_HOME/bin:$PATH"' >> ~/.bashrc

	# Odśwież / Refresh
	source ~/.bashrc

	# Sprawdź / Verify
	echo $JAVA_HOME

#### 4. Optymalizacja dla klienta KSeF / Optimization for KSeF client
	# Stwórz plik konfiguracyjny dla Java opts / Create configuration file for Java opts
	sudo mkdir -p /etc/odoo/java
	sudo tee /etc/odoo/java/jvm-opts.conf << 'EOF'
	# Optymalizacje dla KSeF JAR / Optimizations for KSeF JAR
	-Xmx2g           # 2GB RAM max
	-Xms512m         # 512MB initial
	-XX:MaxMetaspaceSize=512m
	-XX:+UseG1GC     # Garbage Collector
	-XX:+UseStringDeduplication
	-Dfile.encoding=UTF-8
	-Duser.timezone=Europe/Warsaw
	EOF

#### 5. Weryfikacja instalacji / Installation verification
	# Sprawdź wersję Java dla użytkownika odoo / Check Java version for odoo user
	sudo -u odoo java -version

	# Sprawdź ścieżkę Java / Check Java path
	sudo -u odoo which java

Po poprawnej instalacji środowiska Java można przystąpić do kompilacji klienta KSeF (szczegóły w katalogu static/src/java) / After successful Java environment installation, proceed to compile the KSeF client (details in the static/src/java directory).


---

## Wsparcie / Support

- **GitHub Issues**: https://github.com/Hadron4biz/hfb_xmlmap_exporter/issues
- **Dokumentacja KSeF / KSeF Documentation**: https://www.gov.pl/web/ksef/dokumentacja-techniczna
- **Email**: [twój email / your email]

---

## Licencja / License

MIT License – szczegóły w pliku LICENSE / see LICENSE file for details

---

## Zmiany / Changelog

### wersja 1.0.0 / version 1.0.0 (2026-03-27)
- Pierwsze wydanie / Initial release
- Obsługa KSeF 2.0 / KSeF 2.0 support
- Mapowanie XML przez XET / XML mapping via XET
- Kolejka wysyłek i crona / Send queue and cron jobs
- Obsługa certyfikatów / Certificate handling




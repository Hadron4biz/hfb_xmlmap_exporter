# Klient Java dla integracji KSeF 2.0 / Java Client for KSeF 2.0 Integration

Moduł hfb_xmlmap_exporter wykorzystuje dedykowany klient Java do komunikacji z API KSeF 2.0.
Klient ten realizuje operacje wysyłki, odbioru oraz weryfikacji faktur, zapewniając stabilność
i zgodność z wymaganiami Ministerstwa Finansów.

Dokument ten opisuje proces instalacji środowiska Java, konfiguracji oraz integracji klienta z Odoo.

## Spis treści / Table of Contents

1. [Wymagania / Prerequisites](#wymagania--prerequisites)
2. [Instalacja Java / Java Installation](#instalacja-java--java-installation)
3. [Kompilacja i konfiguracja klienta KSeF / Compilation and Configuration of KSeF Client](#kompilacja-i-konfiguracja-klienta-ksef--compilation-and-configuration-of-ksef-client)
4. [Integracja z modułem Odoo / Integration with Odoo Module](#integracja-z-modułem-odoo--integration-with-odoo-module)
5. [Testowanie / Testing](#testowanie--testing)
6. [Rozwiązywanie problemów / Troubleshooting](#rozwiązywanie-problemów--troubleshooting)

## 1. Wymagania / Prerequisites

- System operacyjny / Operating System: Linux (Debian/Ubuntu)
- Java Development Kit (JDK) 17 lub nowszy / JDK 17 or newer
- Maven (do kompilacji / for compilation)
- Użytkownik odoo z dostępem do wykonywania plików JAR / odoo user with JAR execution permissions

### Pliki źródłowe 
Wraz z modułem dostarczany jest przykładowy klient Java powstały na bazie kodu klienta publikowanego przez Ministerstwo Finansów RP.
Kod źródłowy znajduje się na ścieżce /static/src/java

	├── build.gradle.kts
	├── klient.info
	├── pl
	│   └── ksef
	│       ├── auth
	│       │   └── Main.java
	│       ├── invoice
	│       │   ├── GetReceivedInvoices.java
	│       │   └── Invoice.java
	│       └── session
	│           ├── CheckSessionStatus.java
	│           ├── DownloadUPO.java
	│           ├── SessionClose.java
	│           └── Session.java
	└── settings.gradle.kts

W pierwszej kolejności należy przygotować dostęp do środowiska Gradle zalecana wersja 4.4.1
Przykładowe pliki konfiguracyjne:
	build.gradle.kts
	settings.gradle.kts

#### Przykładowa treść pliku konfiguracji - wyłacznie do testowania. Do pracy klienta Java z Odoo, nie jest to potrzebne i nie należy tego pliku tworzyć.
Plik ksef-auth.yml
	ksef:
	  api:
		publicmfkey: /opt/ksef/certs/ksef-public.pem
		baseUrl: https://api-test.ksef.mf.gov.pl/v2

	  auth:
		keystore:
		  path: /opt/ksef/certs/auth/user-ksef-java-auth.p12
		  password: "TU-WPROWADŹ-HASŁO-CERTYFIKATU"
		  alias: ksef-auth

	  sign:
		keystore:
		  path: /opt/ksef/certs/sign/user-ksef-java-sign.p12
		  password: "TU-WPROWADŹ-HASŁO-CERTYFIKATU"
		  alias: ksef-sign

	  timeouts:
		connectSeconds: 10
		readSeconds: 30

	  context:
		nip: "TU-WPROWADŹ-NIP"

	  baseUrl: https://ksef-test.mf.gov.pl/api/v2

	  online:
		schema:
		  systemCode: KSeF
		  formCode: FA
		  version: 3

	logging:
	  level: INFO

Przykłady użycia znajdują się w pliku 
	klient.info

## 2. Instalacja Java / Java Installation

### 2.1. Instalacja JDK 17 / Install JDK 17
	sudo apt update
	sudo apt upgrade -y
	sudo apt install -y openjdk-17-jdk openjdk-17-jre
	java -version

### 2.2. Ustawienie domyślnej wersji Java / Set Default Java Version
	sudo update-alternatives --config java
	sudo update-alternatives --config javac

#### Ustaw domyślną wersję (np. OpenJDK 17) / Set default version
	sudo update-java-alternatives -s java-1.17.0-openjdk-amd64

### 2.3. Konfiguracja zmiennych środowiskowych / Environment Variables
	echo 'export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"' >> ~/.bashrc
	echo 'export PATH="$JAVA_HOME/bin:$PATH"' >> ~/.bashrc
	source ~/.bashrc
	echo $JAVA_HOME

### 2.4. Optymalizacja dla klienta KSeF / Optimization for KSeF Client
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

### 2.5. Weryfikacja / Verification
# Sprawdź wersję Java dla użytkownika odoo / Check Java version for odoo user
	sudo -u odoo java -version

# Sprawdź ścieżkę / Check Java path
	sudo -u odoo which java

## 3. Kompilacja i konfiguracja klienta KSeF / Compilation and Configuration of KSeF Client

Kod źródłowy klienta Java znajduje się w katalogu /static/src/java modułu.
Przed użyciem należy go skompilować.

### 3.1. Lokalizacja źródeł / Source Location
	/path/to/odoo/addons/hfb_xmlmap_exporter/static/src/java/

	Struktura pakietów / Package structure:
	pl.ksef
	├── auth/      – uwierzytelnianie / authentication
	├── invoice/   – obsługa faktur / invoice handling
	└── session/   – zarządzanie sesją / session management

### 3.2. Kompilacja / Compilation
	Wejdź do katalogu głównego projektu Java / Navigate to Java project root:
	cd /path/to/odoo/addons/hfb_xmlmap_exporter/static/src/java
	mvn clean package

Po udanej kompilacji pliki JAR zostaną utworzone w katalogu target/.

### 3.3. Utworzenie katalogu dla plików binarnych / Create Binaries Directory
	sudo mkdir -p /opt/ksef-integration/bin
	sudo cp target/ksef-*.jar /opt/ksef-integration/bin/
	sudo chown -R odoo:odoo /opt/ksef-integration

## 4. Integracja z modułem Odoo / Integration with Odoo Module

Po skompilowaniu klienta Java należy skonfigurować Provider w Odoo,
aby korzystał z Java Client.

### Krok 1: Utwórz lub edytuj Provider / Create or Edit Provider
Przejdź do: KSeF → Konfiguracja → Providerzy
Wybierz lub utwórz nowego Providera.

### Krok 2: Wybór backendu KSeF / Select KSeF Backend
W sekcji "Środowisko i autoryzacja" / In "Environment and Authorization" section:

- KSeF API Backend → wybierz "Java Client"

### Krok 3: Wskaż ścieżkę do plików JAR / Specify JAR Files Path
- Ścieżka do plików JAR → wpisz: /opt/ksef-integration/bin/

Moduł automatycznie wczyta wszystkie pliki .jar z tego katalogu.

### Krok 4: Zapisz i przetestuj / Save and Test
Kliknij "Zapisz", a następnie użyj przycisku "Test połączenia"
(jeśli dostępny) lub wykonaj próbne wysyłanie faktury w trybie testowym.

## 5. Testowanie / Testing

### 5.1. Ręczne uruchomienie klienta Java / Manual Java Client Test
	cd /opt/ksef-integration/bin
	sudo -u odoo java -jar ksef-auth.jar --help

### 5.2. Test wysyłki faktury przez Odoo / Test Invoice Send via Odoo
------------------------------------------------------------------
- 1. Przygotuj fakturę w trybie testowym / Prepare invoice in test mode.
- 2. Wybierz Providera z backendem "Java Client".
- 3. Kliknij "Wyślij do KSeF".
- 4. Sprawdź logi Odoo / Check Odoo logs:

	tail -f /var/log/odoo/odoo.log | grep -i ksef

## 6. Rozwiązywanie problemów / Troubleshooting

| Problem / Issue                          | Rozwiązanie / Solution                                      |
|------------------------------------------|-------------------------------------------------------------|
| Java not found                           | Upewnij się, że użytkownik odoo ma dostęp do java           |
|                                          | sudo -u odoo which java                                     |
|------------------------------------------|-------------------------------------------------------------|
| JAR not found                            | Sprawdź, czy ścieżka w Providerze wskazuje                  |
|                                          | na katalog z plikami .jar                                   |
|------------------------------------------|-------------------------------------------------------------|
| ClassNotFoundException                   | Kompilacja nie powiodła się – uruchom                       |
|                                          | mvn clean package ponownie                                  |
|------------------------------------------|-------------------------------------------------------------|
| Permission denied                        | Ustaw poprawne uprawnienia:                                 |
|                                          | chown -R odoo:odoo /opt/ksef-integration                    |
|------------------------------------------|-------------------------------------------------------------|
| OutOfMemoryError                         | Zwiększ pamięć w pliku jvm-opts.conf i upewnij się,         |
|                                          | że Odoo go odczytuje                                        |

## Dodatkowe informacje / Additional Information

- Klient Java został przygotowany zgodnie z wymaganiami KSeF 2.0.
- Obsługuje uwierzytelnianie na podstawie certyfikatów (PKCS#12).
- W przypadku aktualizacji klienta Java wystarczy ponownie skompilować
  i skopiować pliki JAR.
- Wszelkie problemy zgłaszaj przez GitHub Issues.

---

Wersja dokumentu / Document Version: 1.0
Ostatnia aktualizacja / Last Updated: 2026-04-01


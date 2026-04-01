# 🧩 eXtensible Exchange Template (XET)
## Base Provider dla Odoo 18

## 📌 Opis projektu

**eXtensible Exchange Template (XET)** to generyczny, oparty o schematy **XSD** silnik wymiany danych dla Odoo, umożliwiający:

- mapowanie pól modeli Odoo do struktur XML,
- generowanie dokumentów XML zgodnych z XSD,
- import danych z XML do modeli Odoo,
- walidację strukturalną dokumentów,
- komunikację z systemami zewnętrznymi poprzez wymienne providery.

Celem projektu jest **rozszycie na warstwy**:
- struktury danych (XSD),
- logiki mapowania (XET),
- mechanizmu komunikacji (provider).

Dzięki temu możliwe jest budowanie integracji **bez trwałego powiązania logiki biznesowej z jednym formatem lub jednym systemem zewnętrznym**.

---

## 🚀 Kluczowe możliwości

- 📤 eksport XML sterowany schematem XSD,
- 📥 import XML → modele Odoo,
- ✅ walidacja XML względem XSD,
- 🔀 warunkowe renderowanie węzłów,
- 🔁 obsługa pętli (one2many / many2many),
- 🔢 pełna kontrola kolejności elementów (sequence),
- 🔌 warstwa komunikacji niezależna od formatu danych,
- 🧾 rejestrowanie komunikacji i walidacji,
- 🖨️ wizualizacja UPO w postaci PDF,
- 🧩 zarządzanie szablonami i XSD z poziomu UI.

---

## 🏗️ Architektura rozwiązania

## 🧠 1. Silnik XET (Core)

Warstwa odpowiedzialna za definicję struktury danych i mapowanie:

- definicje szablonów XML,
- drzewa węzłów XML zgodne z XSD,
- kolejność elementów (sequence),
- warunki występowania węzłów,
- eksport i import danych,
- walidację oraz diagnostykę.

**Modele bazowe:**
- `xml_template`
- `xml_export_template`
- `xml_import_template`
- `xml_validation_log`
- `xml_xsd_import_wizard`

---

## 🔄 2. Framework komunikacyjny

Warstwa pośrednia pomiędzy silnikiem XET a systemami zewnętrznymi:

- wspólny interfejs providerów,
- logi komunikacji i operacji,
- obsługa zadań cyklicznych (cron),
- kanały komunikacyjne.

**Modele:**
- `communication_provider`
- `communication_log`

---

## 🔌 3. Providery (integracje)

Specjalizowane implementacje dziedziczące po bazowym providerze:

- 📁 **LocalDir** – provider referencyjny i testowy,
- 🇵🇱 **KSeF** – integracja z Krajowym Systemem e-Faktur (FA(3), KSeF 2.0),
- 🌍 **PEPPOL / PowerOffice** – providery przygotowane strukturalnie do dalszego rozwoju.

Nowe integracje mogą być dodawane **bez modyfikacji silnika XET**.

---

## 🧾 4. Integracja biznesowa

Modele wykorzystujące warstwę komunikacyjną:

- wysyłka i odbiór faktur,
- przetwarzanie dokumentów przychodzących,
- wizualizacja UPO w formacie PDF.

---

## 🇵🇱 Integracja KSeF (provider referencyjny)

Provider **KSeF** prezentuje pełne możliwości architektury XET:

- generowanie faktur FA(3 na podstawie oficjalnych XSD),
- import faktur przychodzących do `account.move`,
- obsługa sesji i komunikacji z KSeF,
- przetwarzanie oraz wizualizacja UPO,
- wyraźne oddzielenie kryptografii od runtime Odoo.

⚠️ **Uwaga**  
Skrypty bash, certyfikaty, narzędzia Java oraz obsługa podpisów XAdES zawarte w repozytorium mają charakter **narzędzi integracyjnych / developerskich** i **nie są wymagane** do działania samego modułu Odoo.

---

## 🖥️ Interfejs użytkownika

Moduł udostępnia kompletne UI do:

- zarządzania szablonami XET i węzłami XML,
- importu i analizy schematów XSD,
- importu i eksportu szablonów (JSON / XET),
- konfiguracji providerów i kanałów komunikacji,
- przeglądania logów komunikacji i walidacji,
- uruchamiania operacji ręcznych i cyklicznych.

---

## ⚙️ Wymagania

- 🧩 Odoo 18+
- 🐍 Python 3.x
- 🗄️ PostgreSQL

**Opcjonalnie (zależnie od providera):**
- ☕ Java (wybrane operacje kryptograficzne KSeF),
- 🔐 certyfikaty testowe lub kwalifikowane.

---

## 📦 Instalacja

1. Umieść moduł w katalogu `addons` Odoo.
2. Zaktualizuj listę aplikacji.
3. Zainstaluj **eXtensible Exchange Template – Base Provider**.
4. Skonfiguruj providery i szablony z poziomu interfejsu.

Zapoznaj się z treścią pliku USER_GUIDE_🍀.md

---

## 📊 Status projektu

- 🟢 silnik XET – **stabilny**
- 🟢 framework komunikacji – **stabilny**
- 🟢 provider LocalDir – **stabilny**
- 🟡 provider KSeF – **zaawansowany / aktywnie rozwijany**
- 🔧 kolejne providery – **gotowe do rozszerzeń**

---

## 📚 Dokumentacja

Szczegółowa dokumentacja techniczna (PL) zostanie udostępniona w nowej strukturze `/docs` i obejmie m.in.:

- specyfikację formatu XET,
- silnik renderowania XML,
- silnik importu XML,
- tworzenie własnych providerów,
- integrację z KSeF.

---

## 📄 Licencja

AGPL-3  
© 2017–2026 Hadron for business sp. z o.o.


# 🧭 Onboarding konsultanta – eXtensible Exchange Template (XET)

## 🎯 Cel tego dokumentu

Ten dokument ma pomóc nowym konsultantom szybko zrozumieć:
- czym jest XET,
- jaką rolę pełni w projektach Odoo,
- co konsultant **konfiguruje**, a czego **nie musi programować**,
- jak wygląda typowy projekt z użyciem XET (np. KSeF).

Nie jest to dokument techniczny ani developerski.

---

## 🧩 Czym jest XET – w skrócie

**XET (eXtensible Exchange Template)** to mechanizm, który pozwala:
- mapować dane z Odoo do struktur wymaganych przez systemy zewnętrzne,
- robić to **konfiguracyjnie**, bez pisania kodu,
- wielokrotnie używać i przenosić gotowe mapowania.

W praktyce:
> **XET zastępuje „szyte na miarę” integracje jednym wspólnym mechanizmem.**

---

## 🧠 Jak myśleć o XET jako konsultant

### Kluczowa zmiana podejścia

❌ Klasycznie:
- „Trzeba dopisać kod do eksportu faktury”

✅ W XET:
- „Trzeba skonfigurować szablon wymiany danych”

Twoja praca polega na **ustawieniu reguł**, nie na programowaniu.

---

## 🏗️ Podstawowe elementy, które spotkasz

### 📄 Szablon XET
- opisuje **strukturę dokumentu** (np. faktury),
- jest zgodny ze schematem XSD,
- może być używany wielokrotnie i przenoszony między systemami.

### 🧱 Węzeł (node)
Każdy element dokumentu (XML) to osobny węzeł, który ma m.in.:
- warunek wystąpienia,
- sposób pobrania wartości,
- kolejność względem innych elementów.

### 🔌 Provider
- odpowiada za **wysłanie / odebranie danych**,
- przykłady: LocalDir, KSeF,
- konsultant **konfiguruje**, nie implementuje providera.

---

## 🔁 Co konsultant robi w projekcie z XET

### ✅ Zakres odpowiedzialności konsultanta

- analiza wymagań klienta (jakie dane są potrzebne),
- mapowanie pól Odoo → struktura dokumentu,
- ustawianie warunków (kiedy element ma się pojawić),
- testowanie eksportu / importu,
- weryfikacja poprawności danych i logów.

### 🚫 Czego konsultant nie musi robić

- pisać kodu Pythona,
- modyfikować core Odoo,
- znać API systemów zewnętrznych,
- implementować kryptografii czy podpisów.

---

## 🔀 Warunki i logika – kluczowa przewaga XET

XET pozwala:
- włączać lub wyłączać elementy dokumentu w zależności od danych,
- wybierać źródło wartości (pole, stała, wyrażenie),
- obsługiwać wyjątki klientów **bez zmiany kodu**.

Dzięki temu:
- jeden szablon obsługuje wielu klientów,
- nie powstają „specjalne wersje” systemu.

---

## 📦 Przenośność i reużywalność

Szablony XET:
- można eksportować do pliku,
- importować do innej instancji Odoo,
- używać w kolejnych projektach.

Dla konsultanta oznacza to:
- coraz mniej pracy od zera,
- coraz więcej gotowych, sprawdzonych konfiguracji.

---

## 🔍 Diagnostyka i testy

W przypadku problemów:
- sprawdzasz **logi komunikacji**,
- sprawdzasz **logi walidacji struktury**,
- wiesz, czy problem dotyczy:
  - danych,
  - struktury,
  - komunikacji.

Nie debugujesz kodu – analizujesz proces.

---

## 🧾 Przykład: projekt KSeF

Typowy projekt z użyciem XET:
1. wybór gotowego szablonu FA(3),
2. dostosowanie mapowania do klienta,
3. test eksportu i walidacji,
4. konfiguracja providera KSeF,
5. uruchomienie produkcyjne.

Większość pracy to **konfiguracja i testy**, nie development.

---

## 📌 Najważniejsze rzeczy do zapamiętania

- XET = konfiguracja, nie kod,
- szablon = przenośny zasób projektu,
- provider = warstwa techniczna (nie Twoja),
- jeden szablon = wielu klientów,
- logi = Twoje główne narzędzie pracy.

---

## 🎓 Podsumowanie

Dla konsultanta XET:
- upraszcza projekty,
- skraca czas wdrożeń,
- zmniejsza ryzyko błędów,
- pozwala skupić się na biznesie klienta, nie na technikaliach.

XET to narzędzie, które **rośnie razem z Twoim doświadczeniem wdrożeniowym**.


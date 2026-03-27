# ❓ FAQ onboardingowe – eXtensible Exchange Template (XET)

## 1. Czy muszę umieć programować, żeby pracować z XET?
**Nie.**  
XET jest zaprojektowany tak, aby **większość pracy była konfiguracyjna**, nie programistyczna.
Konsultant pracuje na:
- szablonach,
- węzłach,
- warunkach,
- mapowaniu pól.

Kod Python jest potrzebny wyłącznie przy **rozszerzaniu platformy**, nie przy typowych wdrożeniach.

---

## 2. Czym różni się szablon XET od klasycznego raportu / QWeb?
Szablon XET:
- jest **przenośny** (eksport/import),
- nie jest związany z jedną instancją Odoo,
- posiada logikę warunkową i iteracyjną,
- może być używany przez różne providery.

QWeb to głównie prezentacja – XET to **kontrakt wymiany danych**.

---

## 3. Co zrobić, gdy klient ma „nietypowy przypadek”?
Najpierw:
- sprawdź, czy da się go obsłużyć **warunkiem (`condition_expr`)**,
- albo alternatywnym źródłem wartości (`value_expr`).

W większości przypadków **nie trzeba zmieniać kodu**.
Dopiero gdy wymóg jest systemowy (np. nowy typ komunikacji), angażowany jest integrator lub developer.

---

## 4. Czy jeden szablon może obsłużyć wielu klientów?
**Tak – i to jest założenie XET.**

Różnice klientów są obsługiwane przez:
- warunki,
- konfigurację danych,
- parametry providera.

Nie tworzymy „kopii szablonu na klienta”, tylko **warianty konfiguracyjne**.

---

## 5. Jak przenieść szablon do innej instancji Odoo?
- eksport szablonu do JSON,
- import w drugiej instancji,
- ewentualna korekta mapowania pól (jeśli modele różnią się).

To standardowy element pracy z XET.

---

## 6. Co sprawdzić, gdy coś nie działa?
Zawsze w tej kolejności:
1. **log walidacji XML** (struktura, XSD),
2. **log komunikacji** (wysyłka / odbiór),
3. dane źródłowe w Odoo.

Nie debugujemy kodu – **analizujemy proces**.

---

## 7. Czy mogę coś „zepsuć” konfiguracją?
Ryzyko jest **kontrolowane**:
- walidacja XSD wykrywa błędy struktury,
- logi jasno pokazują etap awarii,
- zmiany w szablonie nie wpływają na core Odoo.

To bezpieczniejsze niż customowy kod.

---

## 8. Kiedy potrzebny jest developer?
Developer jest potrzebny, gdy:
- powstaje nowy provider,
- trzeba rozszerzyć silnik XET,
- pojawia się nowy typ integracji technicznej.

W typowych wdrożeniach **nie jest angażowany na co dzień**.

---

# 👥 Schemat ról w projektach XET
## Konsultant vs Integrator vs Developer

---

## 🧑‍💼 Konsultant wdrożeniowy

### Zakres odpowiedzialności
- analiza wymagań klienta,
- mapowanie pól Odoo do struktury dokumentu,
- konfiguracja szablonów XET,
- ustawianie warunków i wyjątków,
- testy funkcjonalne,
- wsparcie powdrożeniowe (1 linia).

### Kompetencje
- dobra znajomość Odoo (modele biznesowe),
- rozumienie procesów księgowych / biznesowych,
- podstawowa logika warunkowa (bez programowania).

### Czego NIE robi
- nie pisze kodu Pythona,
- nie implementuje providerów,
- nie zajmuje się kryptografią.

---

## 🔌 Integrator systemowy

### Zakres odpowiedzialności
- konfiguracja providerów (np. KSeF),
- ustawienia komunikacji i środowisk,
- obsługa sesji, trybów, harmonogramów,
- analiza logów komunikacyjnych (2 linia).

### Kompetencje
- dobra znajomość Odoo technicznie,
- rozumienie integracji systemowych,
- podstawy API / protokołów.

### Czego NIE robi
- nie projektuje struktury dokumentów,
- nie mapuje pól biznesowych,
- rzadko modyfikuje core.

---

## 🧑‍💻 Developer

### Zakres odpowiedzialności
- rozwój silnika XET,
- tworzenie nowych providerów,
- optymalizacja i refaktoryzacja,
- wsparcie techniczne 3 linii.

### Kompetencje
- Python / Odoo internals,
- architektura systemów,
- bezpieczeństwo i wydajność.

### Czego NIE robi
- nie konfiguruje klientów,
- nie dostosowuje szablonów,
- nie pracuje na danych biznesowych.

---

## 📊 Porównanie ról (skrót)

| Obszar | Konsultant | Integrator | Developer |
|------|-----------|------------|-----------|
| Szablony XET | ✅ główna rola | ⚠️ pomocniczo | ❌ |
| Providery | ❌ | ✅ główna rola | ⚠️ |
| Kod Python | ❌ | ⚠️ | ✅ |
| Klient końcowy | ✅ | ⚠️ | ❌ |
| Skalowanie rozwiązań | ⚠️ | ⚠️ | ✅ |

---

## 📌 Podsumowanie

XET umożliwia **czysty podział ról**:
- konsultanci konfigurują,
- integratorzy łączą systemy,
- developerzy rozwijają platformę.

Dzięki temu projekty:
- są szybsze,
- mniej ryzykowne,
- łatwiejsze do skalowania zespołów.


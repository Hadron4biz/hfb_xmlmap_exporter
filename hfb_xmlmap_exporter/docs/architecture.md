# 🧩 eXtensible Exchange Template (XET)
## Jednostronicowe podsumowanie dla zespołów wdrożeniowych

---

## 🎯 Cel rozwiązania

**XET** to platforma mapowania i wymiany danych strukturalnych w Odoo, której celem jest
**zastąpienie jednorazowych, kodowanych integracji XML rozwiązaniem konfiguracyjnym,
przenośnym i wielokrotnego użytku**.

XET rozdziela:
- **strukturę danych** (XSD),
- **mapowanie** (szablon XET),
- **komunikację** (provider).

Dzięki temu integracje przestają być kodem, a stają się **zarządzalnymi artefaktami wdrożeniowymi**.

---

## 🚀 Co daje to zespołom wdrożeniowym

- ⏱️ **Szybsze wdrożenia** – konfiguracja zamiast pisania kodu.
- ♻️ **Reużywalność** – jeden szablon dla wielu klientów i instancji Odoo.
- 🔄 **Przenośność** – eksport/import szablonów między środowiskami i firmami.
- 🧠 **Elastyczność** – warunki, pętle i logika decyzyjna bez modyfikacji Pythona.
- 🔍 **Lepsza diagnostyka** – logi strukturalne i komunikacyjne zamiast debugowania.
- 🧩 **Skalowalność zespołów** – mniej zależności od developerów.

Efekt: **niższy koszt wdrożeń, krótszy time-to-market, mniejsze ryzyko utrzymaniowe**.

---

## ⭐ Najważniejsze przewagi XET

- 📦 mapowanie jako **dane**, nie kod,
- 🔁 wielokrotne użycie i wersjonowanie szablonów,
- 🔌 niezależność od systemu zewnętrznego (KSeF, PEPPOL, inne),
- 📜 pełna zgodność z XSD i walidacja przed wysyłką,
- 🛠️ brak ingerencji w core Odoo i moduły biznesowe.

XET to **platforma integracyjna**, a nie kolejny generator XML.

---

## ⚖️ Porównanie: XET vs klasyczne integracje (Python / QWeb)

| Obszar | XET | Klasyczne integracje |
|------|-----|----------------------|
| Mapowanie danych | Konfiguracja (szablon XET) | Kod Python / QWeb |
| Reużywalność | Wysoka (wiele klientów, instancji) | Niska (jednorazowe) |
| Przenośność | Eksport/import JSON | Brak |
| Warunki i logika | W szablonie (declarative) | `if` w kodzie |
| Zmiana XSD | Aktualizacja szablonu | Refaktoryzacja kodu |
| Ryzyko regresji | Niskie | Wysokie |
| Utrzymanie | Konfiguracyjne | Programistyczne |
| Skalowanie zespołu | Konsultanci + integratorzy | Programiści |
| Diagnostyka | Logi strukturalne i komunikacyjne | Debug / logi techniczne |

---

## 📌 Podsumowanie

Dla zespołów wdrożeniowych **XET zmienia model pracy**:
z tworzenia integracji „od zera” na **zarządzanie biblioteką przenośnych szablonów**.

To:
- mniej kodu,
- więcej kontroli,
- większa powtarzalność,
- realna skalowalność biznesu wdrożeniowego.


# KSeF FA(3) Viewer - Roadmap Rozwoju

## Stan aktualny

| Typ dokumentu | Pokrycie |
|---------------|----------|
| VAT | 75-80% |
| ZAL | 70-75% |
| ROZ | 65-70% |
| KOR | 70-75% |
| KOR_ZAL | 65-70% |

---

# Faza 1 - Elementy wspólne FA(3)

## A1. Nagłówek techniczny

Status: TODO

### Parser

- [ ] KodFormularza
- [ ] KodSystemowy
- [ ] WariantFormularza
- [ ] DataWytworzeniaFa
- [ ] SystemInfo
- [ ] NumerKSeF z XML

### Raport

- [ ] Sekcja "Informacje techniczne"

Priorytet: Wysoki

---

## A2. Podmiot3

Status: TODO

### Parser

- [ ] Podmiot3
- [ ] DaneIdentyfikacyjne
- [ ] Adres
- [ ] NrKlienta

### Raport

- [ ] Sekcja "Odbiorca"

Priorytet: Wysoki

---

## A3. PodmiotUpowazniony

Status: TODO

### Parser

- [ ] PodmiotUpowazniony
- [ ] DaneIdentyfikacyjne
- [ ] Adres

### Raport

- [ ] Sekcja "Podmiot upoważniony"

Priorytet: Wysoki

---

## A4. Płatności

Status: TODO

### Parser

- [ ] TerminPlatnosci
- [ ] FormaPlatnosci
- [ ] RachunekBankowy
- [ ] KwotaDoZaplaty
- [ ] KwotaZaplacona

### Raport

- [ ] Sekcja "Płatności"

Priorytet: Bardzo wysoki

---

## A5. Waluty

Status: TODO

### Parser

- [ ] KodWaluty
- [ ] KursWaluty
- [ ] DataKursu

### Raport

- [ ] Sekcja kursu waluty

Priorytet: Średni

---

## A6. Procedury VAT

Status: Częściowo wykonane

### Wykonane

- [x] Split Payment
- [x] Procedura marży
- [x] Zwolnienie
- [x] Nowe środki transportu
- [x] Odwrotne obciążenie

### Do wykonania

- [ ] TP
- [ ] TT_WNT
- [ ] TT_D
- [ ] MR_T
- [ ] MR_UZ
- [ ] I_42
- [ ] I_63
- [ ] B_SPV
- [ ] B_SPV_DOSTAWA
- [ ] B_MPV_PROWIZJA

Priorytet: Wysoki

---

## A7. Nowe środki transportu

Status: TODO

### Parser

- [ ] DataDopuszczenia
- [ ] Przebieg
- [ ] GodzinyPracy

### Raport

- [ ] Szczegóły środka transportu

Priorytet: Średni

---

# Faza 2 - Faktura VAT

## VAT-1. Stawki VAT

Status: Częściowo wykonane

### Do wykonania

- [ ] Zw
- [ ] NP
- [ ] OO
- [ ] 0%
- [ ] Mieszane stawki specjalne

Priorytet: Średni

---

## VAT-2. Zwolnienia

Status: TODO

### Do wykonania

- [ ] Podstawa prawna zwolnienia
- [ ] Prezentacja podstawy zwolnienia

Priorytet: Średni

---

# Faza 3 - Faktura zaliczkowa (ZAL)

## ZAL-1. Dane zamówienia

Status: TODO

### Parser

- [ ] NrZamowienia
- [ ] DataZamowienia

### Raport

- [ ] Sekcja zamówienia

Priorytet: Wysoki

---

## ZAL-2. Rozliczenie zaliczek

Status: TODO

### Raport

- [ ] Wartość zamówienia
- [ ] Otrzymana zaliczka
- [ ] Pozostało do rozliczenia

Priorytet: Wysoki

---

## ZAL-3. Wielokrotne zaliczki

Status: TODO

### Parser

- [ ] Obsługa wielu zaliczek

### Raport

- [ ] Lista zaliczek

Priorytet: Średni

---

# Faza 4 - Faktura rozliczeniowa (ROZ)

## ROZ-1. Powiązane zaliczki

Status: TODO

### Parser

- [ ] Faktury zaliczkowe
- [ ] Numery KSeF zaliczek
- [ ] Kwoty zaliczek

### Raport

- [ ] Sekcja "Rozliczane zaliczki"

Priorytet: Bardzo wysoki

---

## ROZ-2. Bilans rozliczenia

Status: TODO

### Raport

- [ ] Wartość końcowa
- [ ] Suma zaliczek
- [ ] Pozostało do zapłaty

Priorytet: Bardzo wysoki

---

# Faza 5 - Faktura korygująca (KOR)

## KOR-1. Wizualizacja zmian

Status: Częściowo wykonane

### Aktualnie

- [x] StanPrzed

### Do wykonania

- [ ] StanPo
- [ ] Delta

Priorytet: Wysoki

---

## KOR-2. Przyczyna korekty

Status: TODO

### Parser

- [ ] PrzyczynaKorekty

### Raport

- [ ] Prezentacja przyczyny

Priorytet: Wysoki

---

## KOR-3. Zmiany wartości

Status: TODO

### Raport

- [ ] Netto przed
- [ ] Netto po
- [ ] Różnica netto
- [ ] VAT przed
- [ ] VAT po
- [ ] Różnica VAT
- [ ] Brutto przed
- [ ] Brutto po
- [ ] Różnica brutto

Priorytet: Wysoki

---

# Faza 6 - Korekta faktury zaliczkowej (KOR_ZAL)

## KZ-1. Dane korekty

Status: Częściowo wykonane

### Aktualnie

- [x] DaneFaKorygowanej
- [x] StanPrzedZ
- [x] P_15ZK

### Do wykonania

- [ ] StanPoZ
- [ ] Delta

Priorytet: Wysoki

---

## KZ-2. Rozliczenie korekty zaliczki

Status: TODO

### Raport

- [ ] Zaliczka przed korektą
- [ ] Zaliczka po korekcie
- [ ] Różnica

Priorytet: Wysoki

---

# Faza 7 - Elementy specjalne

## JST

Status: Częściowo wykonane

### Aktualnie

- [x] Flaga JST

### Do wykonania

- [ ] Szczegóły JST

---

## GV

Status: Częściowo wykonane

### Aktualnie

- [x] Flaga GV

### Do wykonania

- [ ] Szczegóły grupy VAT

---

## Transport

Status: TODO

### Do wykonania

- [ ] Szczegółowe dane środka transportu

---

# Założenia architektoniczne

- XML FA(3) pozostaje jedynym źródłem prawdy.
- Źródłem danych jest communication.log.
- Raport nie korzysta z account.move.line.
- Parser pozostaje centralnym punktem rozwoju.
- QWeb powinien operować wyłącznie na znormalizowanych danych.

## Przepływ danych

communication.log
→ XML FA(3)
→ KSeFParserFA3
→ normalized DTO
→ QWeb
→ PDF


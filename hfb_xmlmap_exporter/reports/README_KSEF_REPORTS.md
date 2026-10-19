# Raporty faktur KSeF FA(3)

## Cel

Katalog `reports` zawiera mechanizm generowania raportu PDF faktury KSeF na podstawie źródłowego pliku XML w strukturze FA(3).

Aktualna implementacja obejmuje:

- fakturę VAT (`VAT`),
- fakturę korygującą (`KOR`),
- fakturę zaliczkową (`ZAL`),
- fakturę rozliczeniową (`ROZ`).

Raport został zaprojektowany tak, aby odwzorować znaczenie danych zawartych w XML KSeF, a nie jedynie ich strukturę techniczną.

---

## Pliki

### `invoice_report.py`

Plik zawiera parser danych XML FA(3) oraz logikę przygotowania znormalizowanej struktury danych przekazywanej do raportu QWeb.

Do jego zadań należy między innymi:

- rozpoznanie rodzaju faktury,
- odczyt danych wystawcy i nabywcy,
- odczyt danych nagłówkowych dokumentu,
- interpretacja `FaWiersz`,
- interpretacja `ZamowienieWiersz`,
- budowa podsumowania VAT,
- obsługa danych korekty,
- obsługa danych zaliczek i faktur rozliczeniowych,
- przygotowanie danych o płatności,
- przygotowanie danych do prezentacji PDF.

### `ksef_invoice_report.xml`

Plik zawiera szablon QWeb raportu PDF.

Odpowiada za prezentację:

- nagłówka faktury,
- numeru KSeF,
- rodzaju dokumentu,
- danych wystawcy i nabywcy,
- danych sprzedaży,
- pozycji faktury,
- danych zamówienia,
- faktur zaliczkowych,
- podsumowania stawek VAT,
- danych korekty,
- analizy zmian VAT,
- informacji o płatności,
- kodu QR KSeF,
- stopki dokumentu.

---

# Obsługiwane rodzaje faktur

## VAT

Faktura `VAT` jest traktowana jako standardowy dokument sprzedażowy.

Źródłem pozycji są elementy:

```text
FaWiersz
```

Mapowanie logiczne:

```text
FaWiersz
    ↓
pozycje faktury
    ↓
account.move.line
    ↓
PDF: Pozycje
```

Raport prezentuje:

- pełne pozycje sprzedaży,
- ilość,
- jednostkę miary,
- cenę jednostkową,
- stawkę VAT,
- wartość netto,
- podsumowanie stawek podatku,
- kwotę należności,
- dane płatności.

---

## KOR

Faktura `KOR` jest obsługiwana jako faktura korygująca.

Parser rozróżnia:

```text
StanPrzed = 1
```

oraz stan po korekcie.

Schemat logiczny:

```text
FaWiersz StanPrzed
+
FaWiersz StanPo
    ↓
pozycje korekty
    ↓
analiza różnicy netto / VAT / brutto
```

Raport prezentuje między innymi:

- dane faktury korygowanej,
- przyczynę korekty,
- typ skutku korekty,
- identyfikację dokumentu pierwotnego,
- pozycje przed korektą,
- pozycje po korekcie,
- analizę zmian VAT według stawek,
- wynik korekty.

Analiza zmian VAT jest wyliczeniem pomocniczym raportu. Nie zastępuje danych źródłowych XML.

---

## ZAL

Faktura `ZAL` dokumentuje otrzymaną zaliczkę przed dokonaniem sprzedaży.

Kluczowe założenie:

> `ZamowienieWiersz` nie jest pozycją faktury zaliczkowej.

Elementy `ZamowienieWiersz` opisują przedmiot zamówienia lub umowy i mają charakter informacyjny.

### Warstwa księgowa

Dane finansowe faktury ZAL są budowane na podstawie:

```text
P_13_*
P_14_*
P_15
```

Schemat:

```text
P_13_* / P_14_*
    ↓
_process_zal_accounting_lines()
    ↓
techniczne linie księgowe
    ↓
account.move.line
```

Techniczne linie pozwalają prawidłowo wyliczyć:

```text
amount_untaxed
amount_tax
amount_total
```

### Warstwa informacyjna

Dane zamówienia są pobierane z:

```text
Zamowienie
ZamowienieWiersz
```

i trafiają do osobnej struktury:

```text
advance.order_lines
```

Schemat:

```text
ZamowienieWiersz
    ↓
dane informacyjne zamówienia
    ↓
PDF: Zamówienie
```

Raport ZAL prezentuje:

- wartość zamówienia lub umowy,
- pozycje zamówienia,
- kwotę zaliczki dokumentowaną fakturą,
- podsumowanie VAT według stawek.

Techniczne linie księgowe ZAL nie są prezentowane w PDF jako towary lub usługi.

### Rozszerzenie przyszłe

`ZamowienieWiersz` może w przyszłości służyć do opcjonalnego:

- wyszukania istniejącego `purchase.order`,
- powiązania ZAL z istniejącym zamówieniem,
- automatycznego utworzenia `purchase.order`.

Funkcjonalność ta powinna być konfigurowalna i niezależna od księgowego importu faktury ZAL.

---

## ROZ

Faktura `ROZ` jest fakturą rozliczeniową kończącą ścieżkę rozpoczętą przez jedną lub więcej faktur zaliczkowych.

Schemat procesu:

```text
Zamówienie / umowa
        ↓
       ZAL
        ↓
       ZAL
        ↓
   wykonanie sprzedaży
        ↓
       ROZ
```

### Pełne pozycje sprzedaży

Źródłem pełnych pozycji są:

```text
FaWiersz
```

Przykład:

```text
pozycja pierwsza   200 × 10,00 = 2 000,00
pozycja druga      300 × 20,00 = 6 000,00
```

### Rozliczenie zaliczek

Dane wynikowe ROZ są zawarte w:

```text
P_13_*
P_14_*
P_15
```

Techniczne linie rozliczenia zaliczek są obliczane jako różnica:

```text
pełne wartości FaWiersz
-
wartości wynikowe P_13_*
=
wartość rozliczonych zaliczek
```

Schemat:

```text
FaWiersz
    ↓
pełne pozycje transakcji

FaWiersz - P_13_*
    ↓
techniczne linie rozliczenia zaliczek

P_13_* + P_14_*
    ↓
wartość końcowa ROZ

P_15
    ↓
kontrola końcowej kwoty dokumentu
```

Przykładowy model Odoo:

```text
pozycja pierwsza                         2 000,00   VAT 23%
pozycja druga                            6 000,00   VAT 5%
rozliczenie zaliczek KSeF – stawka 23%   -401,83   VAT 23%
rozliczenie zaliczek KSeF – stawka 5%  -1205,48   VAT 5%
```

Efekt:

```text
netto:      6 392,69
VAT 23%:      367,58
VAT 5%:       239,73
brutto:     7 000,00
```

### Powiązanie z ZAL

Element:

```text
FakturaZaliczkowa
```

służy do identyfikacji i powiązania dokumentu ROZ z wcześniejszymi fakturami ZAL.

Powiązanie jest niezależne od wyliczenia kwot technicznych linii rozliczenia.

Źródłem kwot rozliczeniowych pozostaje sam XML dokumentu ROZ.

Raport ROZ prezentuje:

- wcześniejsze faktury zaliczkowe,
- pełne pozycje `FaWiersz`,
- kwotę pozostałą do zapłaty,
- wynikowe podsumowanie VAT,
- dane płatności.

Techniczne linie rozliczenia zaliczek są elementem księgowym Odoo i nie są prezentowane w PDF.

---

# Zasady wspólne

## XML jest źródłem danych

Raport i proces odtwarzania faktury powinny w pierwszej kolejności korzystać z danych zapisanych w XML FA(3).

Wyliczenia pomocnicze stosowane są tylko wtedy, gdy są potrzebne do:

- zbudowania poprawnych zapisów księgowych w Odoo,
- analizy korekty,
- kontroli spójności dokumentu.

Nie należy zastępować danych źródłowych XML wartościami odczytanymi z powiązanych dokumentów Odoo, jeśli XML zawiera własne dane rozliczeniowe.

---

## Rozdzielenie warstwy księgowej i prezentacyjnej

Nie każda linia `account.move.line` musi być prezentowana jako pozycja faktury PDF.

Przykłady:

### ZAL

```text
techniczne linie P_13/P_14
→ potrzebne w account.move
→ nie są prezentowane jako towary lub usługi
```

### ROZ

```text
techniczne linie rozliczenia zaliczek
→ potrzebne w account.move
→ nie są prezentowane w PDF
```

PDF powinien prezentować biznesowe znaczenie dokumentu, a nie techniczną implementację księgowania w Odoo.

---

# Kontrola spójności

Dla dokumentów ZAL i ROZ należy sprawdzać zgodność:

```text
suma P_13_*
+
suma P_14_*
=
P_15
```

Dopuszczalna może być jedynie różnica wynikająca z zaokrągleń.

Dla ROZ dodatkowo należy kontrolować zgodność końcowego:

```text
account.move.amount_total
```

z:

```text
P_15
```

---

# Aktualny zakres obsługi

| Typ | Import księgowy | PDF | Status |
|---|---|---|---|
| VAT | tak | tak | obsługiwany |
| KOR | tak | tak | obsługiwany |
| ZAL | tak | tak | obsługiwany |
| ROZ | tak | tak | obsługiwany |
| KOR_ZAL | częściowo / do weryfikacji | częściowo / do weryfikacji | kolejny etap |
| KOR_ROZ | częściowo / do weryfikacji | częściowo / do weryfikacji | kolejny etap |

---

# Kolejne etapy

Planowane dalsze prace:

1. analiza `KOR_ZAL` na podstawie rzeczywistych XML i PDF KSeF,
2. analiza `KOR_ROZ`,
3. ujednolicenie mapowania pól `P_13_* / P_14_*`,
4. oznaczanie technicznych linii rozliczeniowych ROZ osobną flagą,
5. pełna walidacja spójności kwot dokumentów,
6. opcjonalna obsługa `ZamowienieWiersz` w powiązaniu z `purchase.order`,
7. dalsze ujednolicenie stylu PDF pomiędzy VAT, KOR, ZAL i ROZ.

---

# Podsumowanie

Aktualny mechanizm pozwala odtworzyć z XML FA(3) oraz wygenerować PDF dla następujących rodzajów dokumentów:

```text
VAT
KOR
ZAL
ROZ
```

Obsługa ZAL i ROZ uwzględnia rozdzielenie:

```text
danych księgowych
od
danych informacyjnych i prezentacyjnych
```

co jest kluczowe dla poprawnego odwzorowania dokumentów zaliczkowych i rozliczeniowych w Odoo.

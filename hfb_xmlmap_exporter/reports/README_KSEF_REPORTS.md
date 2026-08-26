# Raporty faktur KSeF FA(3)

## Cel

Katalog `reports` zawiera mechanizm odczytu źródłowego XML KSeF w strukturze FA(3) oraz generowania na jego podstawie raportu PDF w Odoo.

Aktualna implementacja obejmuje przede wszystkim:

- fakturę VAT (`VAT`),
- fakturę korygującą (`KOR`),
- fakturę zaliczkową (`ZAL`),
- fakturę rozliczeniową (`ROZ`).

Częściowo obsługiwane są również warianty:

- korekta faktury zaliczkowej (`KOR_ZAL`),
- korekta faktury rozliczeniowej (`KOR_ROZ`).

Podstawową zasadą projektu jest odwzorowanie znaczenia danych zawartych w XML KSeF. Raport nie powinien zastępować danych źródłowych wartościami z rekordu `account.move`, jeżeli dana informacja występuje w XML.

---

# Pliki

## `invoice_report.py`

Plik zawiera:

- parser `KSeFParserFA3`,
- normalizację danych XML do struktury używanej przez QWeb,
- przygotowanie kontekstu raportu,
- generowanie PDF w `action_preview_ksef_pdf()`,
- utworzenie lub odczyt załącznika PDF powiązanego z `account.move`.

Parser odpowiada między innymi za:

- rozpoznanie `RodzajFaktury`,
- odczyt wystawcy i nabywcy,
- odczyt nagłówka dokumentu,
- odczyt numeru faktury z `P_2`,
- interpretację `FaWiersz`,
- interpretację `ZamowienieWiersz`,
- budowę podsumowania VAT z `P_13_*` i `P_14_*`,
- obsługę danych korekty,
- analizę zmian korekty według stawek VAT,
- obsługę faktur zaliczkowych i rozliczeniowych,
- obsługę pełnego bloku `Rozliczenie`,
- obsługę danych płatności,
- przygotowanie danych do kodu QR i wydruku PDF.

## `ksef_invoice_report.xml`

Plik zawiera:

- szablony funkcjonalnych sekcji dokumentu,
- własny layout raportu `ksef_external_layout`,
- prawdziwą stopkę PDF,
- definicję formatu papieru,
- akcję raportu `ir.actions.report`,
- przycisk uruchamiający `action_preview_ksef_pdf()`.

Raport prezentuje między innymi:

- nagłówek faktury,
- typ dokumentu,
- numer KSeF,
- numer faktury z XML,
- dane wystawcy i nabywcy,
- daty i walutę,
- pozycje faktury,
- dane zamówienia,
- wcześniejsze faktury zaliczkowe,
- podsumowanie stawek VAT,
- kwotę należności,
- dane korekty,
- analizę zmian korekty,
- blok `Rozliczenie`,
- dane płatności,
- kod QR KSeF,
- techniczną stopkę dokumentu.

---

# Generowanie PDF w Odoo 18

Kod został przeniesiony z działającej implementacji Odoo 15 do Odoo 18.

W Odoo 18 zmieniła się sygnatura prywatnej metody raportowej:

```python
_render_qweb_pdf(report_ref, res_ids=None, data=None)
```

Dlatego wywołanie powinno przekazywać referencję raportu jako pierwszy argument:

```python
pdf_content, report_type = report_record.with_context(
    active_id=self.id,
    move_id=self.id,
    active_model='account.move',
    ksef_preview_data=normalized,
    print_datetime=print_datetime,
)._render_qweb_pdf(
    report_record.report_name,
    res_ids=self.ids,
    data=render_data_for_pdf,
)
```

Przekazanie samego `self.ids` jako pierwszego argumentu powoduje w Odoo 18 próbę potraktowania listy identyfikatorów jako XML ID raportu i prowadzi do błędów:

```text
TypeError: unhashable type: 'list'
AttributeError: 'list' object has no attribute 'split'
```

## Załączniki podczas testowania

Jeżeli `action_preview_ksef_pdf()` najpierw wyszukuje istniejący załącznik i natychmiast go otwiera, zmiany QWeb nie będą widoczne do czasu usunięcia lub nadpisania starego PDF.

Podczas prac nad raportem należy:

- usuwać istniejący załącznik przed ponownym testem, albo
- generować PDF zawsze i nadpisywać istniejący `ir.attachment`.

---

# Znormalizowana struktura danych

Parser przekazuje do QWeb strukturę `ksef_preview_data`. Główne sekcje mają postać:

```text
ksef_preview_data
├── type
├── issuer
├── recipient
├── invoice
├── lines
├── totals
├── annotations
├── correction
├── correction_tax_analysis
├── advance
├── settlement
└── payment
```

Najważniejsze pola:

```text
invoice.number                 ← P_2
invoice.issue_date             ← P_1
invoice.sale_date              ← P_6
invoice.currency               ← KodWaluty

totals.net                    ← suma podstaw opodatkowania
totals.vat                    ← suma podatku
totals.gross                  ← P_15

settlement.amount_due         ← Rozliczenie/DoZaplaty
settlement.amount_to_settle   ← Rozliczenie/DoRozliczenia
```

---

# XML jest źródłem danych

## Numer faktury

Numer faktury w PDF pochodzi wyłącznie z XML:

```xml
<P_2>...</P_2>
```

W QWeb używana jest wartość:

```xml
<t t-esc="ksef.get('invoice', {}).get('number') or 'Brak w XML'"/>
```

Nie należy używać w tym miejscu:

```text
move.ref
move.name
```

`move.ref` może być właściwe dla części dokumentów przychodzących, a `move.name` dla dokumentów wychodzących, ale oba pola opisują rekord Odoo, a nie źródłowy dokument FA(3).

## Dane techniczne spoza XML

Rekord `account.move` może nadal dostarczać informacje techniczne, które nie są częścią treści XML faktury, na przykład:

- numer nadany przez KSeF,
- tryb wystawienia online/offline,
- dane potrzebne do utworzenia adresu QR,
- techniczny kontekst raportu i powiązanie załącznika.

---

# Obsługiwane rodzaje faktur

## VAT

Faktura `VAT` jest traktowana jako standardowy dokument sprzedażowy.

Źródłem pozycji są elementy:

```text
FaWiersz
```

Schemat:

```text
FaWiersz
    ↓
znormalizowane pozycje
    ↓
PDF: Pozycje
```

Raport prezentuje:

- pełne pozycje sprzedaży,
- ilość i jednostkę miary,
- cenę jednostkową,
- stawkę VAT,
- wartość netto,
- podsumowanie stawek podatku,
- `Kwotę należności` z `P_15`,
- blok `Rozliczenie`, jeśli występuje,
- dane płatności.

---

## KOR

Faktura `KOR` jest obsługiwana jako faktura korygująca.

Parser rozróżnia:

```text
StanPrzed = 1
```

oraz wiersze przedstawiające stan po korekcie.

Schemat:

```text
FaWiersz StanPrzed
+
FaWiersz po korekcie
    ↓
pozycje korekty
    ↓
analiza różnicy netto / VAT / brutto
```

Raport prezentuje:

- dane faktury korygowanej,
- przyczynę korekty,
- typ skutku korekty,
- jedną lub wiele faktur korygowanych,
- numery i daty dokumentów pierwotnych,
- numery KSeF dokumentów pierwotnych,
- pozycje przed korektą,
- pozycje po korekcie,
- podsumowanie VAT z XML,
- `Kwotę należności` z `P_15`,
- analizę zmian korekty według stawek VAT,
- blok `Rozliczenie`, jeżeli został zapisany w XML,
- dane płatności.

### Kwota należności a rozliczenie korekty

Dla `KOR` wartość `P_15` jest drukowana jako:

```text
Kwota należności
```

Nie należy na podstawie samego znaku `P_15` określać tej wartości jako:

- kwoty do zwrotu,
- nadpłaty,
- kwoty do rozliczenia.

Charakter końcowego salda określają dopiero pola bloku `Rozliczenie`:

```text
DoZaplaty
DoRozliczenia
```

### Analiza zmian korekty

Analiza korekty grupuje różnice według stawki VAT:

```text
netto przed
netto po
zmiana netto
zmiana VAT
zmiana brutto
```

Jeżeli pozycje nie zawierają `P_11Vat`, VAT może zostać wyliczony pomocniczo z wartości netto i stawki. Jest to sekcja analityczna raportu i nie zastępuje oficjalnego podsumowania `P_13_* / P_14_*` z XML.

---

## ZAL

Faktura `ZAL` dokumentuje otrzymaną zaliczkę przed dokonaniem sprzedaży.

Kluczowa zasada:

> `ZamowienieWiersz` nie jest pozycją sprzedaży faktury zaliczkowej.

Elementy `ZamowienieWiersz` opisują przedmiot zamówienia lub umowy i mają charakter informacyjny.

### Dane finansowe

Dane finansowe dokumentu wynikają z:

```text
P_13_*
P_14_*
P_15
```

Parser raportu może tworzyć syntetyczne pozycje prezentacyjne według stawek VAT, gdy dokument ZAL nie posiada zwykłych `FaWiersz`.

Służą one wyłącznie do czytelnego odwzorowania podstaw i podatku w PDF. Nie należy przedstawiać ich jako rzeczywistych towarów lub usług.

### Dane zamówienia

Dane informacyjne są pobierane z:

```text
Zamowienie
ZamowienieWiersz
```

oraz przekazywane do:

```text
advance.order_lines
```

Raport ZAL prezentuje:

- wartość zamówienia lub umowy,
- pozycje zamówienia,
- kwotę zapłaty zaliczki dokumentowaną fakturą,
- podsumowanie VAT według stawek,
- blok `Rozliczenie`, jeśli występuje,
- dane płatności.

### Rozszerzenie przyszłe

`ZamowienieWiersz` może w przyszłości służyć do opcjonalnego:

- wyszukania istniejącego `purchase.order`,
- powiązania ZAL z istniejącym zamówieniem,
- utworzenia `purchase.order`.

Funkcjonalność ta powinna być konfigurowalna i niezależna od podstawowego importu lub raportowania ZAL.

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

Raport prezentuje pełny przedmiot transakcji, a nie techniczne linie rozliczenia zaliczek.

### Wcześniejsze faktury zaliczkowe

Element:

```text
FakturaZaliczkowa
```

służy do identyfikacji wcześniejszych dokumentów ZAL.

Raport pokazuje:

- numer faktury zaliczkowej,
- numer KSeF,
- informację, czy dokument wystawiono poza KSeF.

### Kwoty końcowe

Dane wynikowe ROZ są zawarte w:

```text
P_13_*
P_14_*
P_15
```

`P_15` jest prezentowane w wyróżnionym bloku jako:

```text
Kwota pozostała do zapłaty
```

Blok ten ma ten sam układ wizualny co `Kwota należności` stosowana dla VAT i korekt.

Raport ROZ prezentuje:

- wcześniejsze faktury zaliczkowe,
- pełne pozycje `FaWiersz`,
- kwotę pozostałą do zapłaty,
- wynikowe podsumowanie VAT,
- blok `Rozliczenie`, jeśli występuje,
- dane płatności.

Techniczne linie rozliczenia zaliczek, jeżeli są tworzone w warstwie księgowej Odoo, nie są prezentowane jako pozycje sprzedaży PDF.

---

# Blok `Rozliczenie`

`Rozliczenie` jest pełnym, fakultatywnym blokiem elementu `Fa`.

Obsługiwana struktura:

```text
Rozliczenie
├── Obciazenia[]
│   ├── Kwota
│   └── Powod
├── SumaObciazen
├── Odliczenia[]
│   ├── Kwota
│   └── Powod
├── SumaOdliczen
├── DoZaplaty
└── DoRozliczenia
```

Parser zapisuje dane w:

```text
settlement.exists
settlement.charges
settlement.total_charges
settlement.deductions
settlement.total_deductions
settlement.amount_due
settlement.amount_to_settle
```

Raport zawiera osobną tabelę `Rozliczenie`, prezentującą:

- poszczególne obciążenia,
- sumę obciążeń,
- poszczególne odliczenia,
- sumę odliczeń,
- kwotę do zapłaty albo kwotę do rozliczenia.

Sekcja pojawia się tylko wtedy, gdy blok występuje w XML.

Raport nie wylicza samodzielnie `DoZaplaty` ani `DoRozliczenia` na podstawie `P_15`.

---

# Dane płatności

Blok `Platnosc` jest niezależny od `Rozliczenie`.

Parser obsługuje między innymi:

- status zapłaty,
- datę zapłaty,
- znacznik zapłaty częściowej,
- zapłaty częściowe,
- formę płatności,
- inną formę płatności i jej opis,
- terminy płatności,
- rachunki bankowe,
- rachunki faktora,
- skonto,
- link do płatności,
- `IPKSeF`.

Rozróżnienie:

```text
P_15                         → kwota należności dokumentu
Rozliczenie/DoZaplaty        → końcowa kwota do zapłaty
Rozliczenie/DoRozliczenia    → końcowa kwota do rozliczenia
Platnosc                     → status, termin i sposób płatności
```

---

# Layout PDF

## Własny layout

Raport używa:

```xml
<t t-call="hfb_xmlmap_exporter.ksef_external_layout">
```

zamiast:

```xml
<t t-call="web.external_layout">
```

Standardowy `web.external_layout` dodawał firmowy nagłówek i stopkę Odoo, które kolidowały z własnym układem raportu, były częściowo obcinane i prowadziły do podwójnej stopki.

`ksef_external_layout` zawiera:

- blok `article`,
- jedną prawdziwą stopkę PDF,
- numerację stron,
- informację o źródle dokumentu,
- wersję Odoo,
- datę i czas wygenerowania wydruku.

Stopka jest generowana na każdej stronie i nie jest zwykłym elementem kończącym treść dokumentu.

## Ramki tabel

Po odejściu od `web.external_layout` nie należy polegać wyłącznie na klasach Bootstrap `table table-bordered`.

Style raportu jawnie ustawiają:

```css
.ksef-report .table {
    width: 100%;
    border-collapse: collapse !important;
    border-spacing: 0 !important;
    border: 1px solid #777 !important;
}

.ksef-report .table th,
.ksef-report .table td {
    border: 1px solid #777 !important;
    padding: 5px 6px;
    vertical-align: middle;
}
```

Dzięki temu ramki tabel są czytelne również w PDF generowanym w Odoo 18.

## Bloki kwot

Wyróżnione bloki kwot mają spójny dwukolumnowy układ:

```text
etykieta | kwota i waluta
```

Stosowane etykiety:

| Typ dokumentu | Etykieta |
|---|---|
| VAT | Kwota należności |
| KOR | Kwota należności |
| KOR_ZAL / KOR_ROZ | Kwota należności |
| ZAL | Kwota zapłaty (zaliczki) dokumentowana fakturą |
| ROZ | Kwota pozostała do zapłaty |

Wartość pochodzi z `P_15`.

---

# Format papieru

Aktualna konfiguracja testowana w Odoo 18:

```xml
<record id="paperformat_ksef" model="report.paperformat">
    <field name="name">KSeF PDF</field>
    <field name="default" eval="False"/>
    <field name="format">A4</field>
    <field name="orientation">Portrait</field>
    <field name="margin_top">25</field>
    <field name="margin_bottom">30</field>
    <field name="margin_left">10</field>
    <field name="margin_right">10</field>
    <field name="dpi">120</field>
</record>
```

Margines dolny musi uwzględniać prawdziwą stopkę PDF. Zmiana XML rekordu `report.paperformat` wymaga aktualizacji modułu.

---

# Kod QR

Raport może prezentować kod QR służący do weryfikacji faktury w KSeF.

Sekcja zawiera:

- obraz QR,
- adres weryfikacyjny,
- numer KSeF,
- informację o trybie offline, jeśli dotyczy.

Numer KSeF i parametry potrzebne do budowy adresu QR są metadanymi technicznymi i nie zastępują treści dokumentu XML.

---

# Rozdzielenie warstwy księgowej i prezentacyjnej

Nie każda linia `account.move.line` musi być prezentowana jako pozycja faktury PDF.

Przykłady:

### ZAL

```text
syntetyczne lub techniczne linie według P_13/P_14
→ mogą być potrzebne do rozliczenia lub prezentacji wartości
→ nie są rzeczywistymi towarami ani usługami
```

### ROZ

```text
techniczne linie rozliczenia zaliczek
→ mogą być potrzebne w warstwie księgowej
→ nie są prezentowane jako pozycje sprzedaży PDF
```

PDF powinien prezentować biznesowe znaczenie dokumentu, a nie techniczną implementację księgowania w Odoo.

---

# Kontrola spójności

Dla dokumentów zawierających podsumowanie VAT należy kontrolować zgodność:

```text
suma P_13_*
+
suma P_14_*
=
P_15
```

Dopuszczalna może być wyłącznie różnica wynikająca z reguł zaokrągleń.

Dla danych odtworzonych w Odoo dodatkowo można kontrolować:

```text
account.move.amount_total
=
P_15
```

Wyliczenia kontrolne nie powinny zastępować wartości źródłowych XML w raporcie.

---

# Aktualny zakres obsługi

| Typ | Parser PDF | PDF | Status |
|---|---|---|---|
| VAT | tak | tak | obsługiwany |
| KOR | tak | tak | obsługiwany |
| ZAL | tak | tak | obsługiwany |
| ROZ | tak | tak | obsługiwany |
| KOR_ZAL | częściowo | częściowo | wymaga dalszej weryfikacji |
| KOR_ROZ | częściowo | częściowo | wymaga dalszej weryfikacji |

Aktualna wersja raportu została uruchomiona w Odoo 18 po dostosowaniu wywołania `_render_qweb_pdf()` i layoutu QWeb.

---

# Kolejne etapy

Planowane dalsze prace:

1. weryfikacja `KOR_ZAL` na podstawie większej liczby rzeczywistych XML,
2. weryfikacja `KOR_ROZ`,
3. ujednolicenie mapowania pól `P_13_* / P_14_*`,
4. pełna walidacja spójności kwot dokumentów,
5. oznaczanie technicznych linii rozliczeniowych ROZ osobną flagą,
6. opcjonalne powiązanie `ZamowienieWiersz` z `purchase.order`,
7. dalsze testy wielostronicowych faktur i podziału sekcji między stronami,
8. ujednolicenie zachowania załączników PDF podczas ponownego generowania,
9. przeniesienie i testy raportu w pozostałych wspieranych wersjach Odoo.

---

# Podsumowanie

Aktualny mechanizm pozwala odczytać XML FA(3) i wygenerować PDF dla podstawowych rodzajów dokumentów:

```text
VAT
KOR
ZAL
ROZ
```

Najważniejsze przyjęte zasady:

- treść faktury pochodzi z XML,
- numer faktury pochodzi z `P_2`,
- `P_15` jest prezentowane niezależnie od bloku `Rozliczenie`,
- `Rozliczenie` i `Platnosc` są odrębnymi sekcjami,
- korekta nie jest automatycznie interpretowana jako nadpłata lub zwrot,
- warstwa prezentacyjna jest oddzielona od technicznych zapisów księgowych,
- raport używa własnego layoutu i jednej prawdziwej stopki PDF,
- ramki tabel są definiowane jawnie w CSS,
- wywołanie PDF jest zgodne z sygnaturą Odoo 18.


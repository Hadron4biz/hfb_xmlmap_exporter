# Szablony XET – nazewnictwo i przeznaczenie

Dokument opisuje konwencję nazewniczą oraz zestaw referencyjnych szablonów XET
(`xml.export.template`) wykorzystywanych do generowania faktur XML FA(3)
wysyłanych do KSeF z Odoo 18.

Celem nazewnictwa jest:
- jednoznaczna identyfikacja przeznaczenia szablonu po nazwie,
- spójność z logiką w kodzie,
- rozróżnienie wariantów dokumentów KSeF,
- skalowalność na kolejne wersje schem i kanały.

---

## 1. Konwencja nazwy szablonu

Format kanoniczny:

XET.<PROVIDER>.<SCHEMA>.<DIRECTION>.<DOCUMENT_TYPE>[.<VARIANT>][.<SCOPE>]

### Znaczenie segmentów

- XET  
  Stały prefiks identyfikujący szablony XET.

- PROVIDER  
  System docelowy / kanał komunikacji.  
  Przykład: `KSeF`

- SCHEMA  
  Typ i wersja schemy XSD.  
  Przykład: `FA3`

- DIRECTION  
  Kierunek dokumentu:
  - `OUT` – dokumenty wychodzące (sprzedaż)
  - `IN` – dokumenty przychodzące (import)

- DOCUMENT_TYPE  
  Typ dokumentu wg KSeF:
  `VAT`, `ZAL`, `ROZ`, `UPR`, `KOR`, `KOR_ZAL`, `KOR_ROZ`

- VARIANT (opcjonalny)  
  Wariant logiczny wpływający na strukturę lub warunki XET  
  (np. `JST`, `OFFLINE`).

- SCOPE  
  Zakres i przeznaczenie szablonu:
  - `BASE` – szkielet techniczny XSD
  - `MIN` – struktura minimalna
  - `PROD` – szablon produkcyjny

---

## 2. Szablony bazowe (techniczne)

Szablony bazowe nie są używane bezpośrednio do wysyłki faktur.
Stanowią punkt odniesienia lub bazę do dalszego mapowania.

### XET.KSeF.FA3.OUT.BASE
Pełny szkielet schemy FA(3):
- kompletne drzewo `xml.export.node`,
- pełne metadane XSD (typy, min/maxOccurs, enumeracje),
- brak lub minimalne mapowanie do pól Odoo.

### XET.KSeF.FA3.OUT.MIN
Minimalna struktura FA(3):
- wyłącznie elementy wymagane przez XSD,
- używana do testów walidacji i porównań.

---

## 3. Szablony sprzedażowe – produkcyjne

Szablony wykorzystywane bezpośrednio do generowania XML wysyłanego do KSeF.

### Faktury sprzedażowe

#### XET.KSeF.FA3.OUT.VAT.PROD
Standardowa faktura VAT:
- podstawowy szablon sprzedażowy,
- mapowanie `account.move` → FA(3).

#### XET.KSeF.FA3.OUT.ZAL.PROD
Faktura zaliczkowa:
- dokumentowanie otrzymania zaliczki,
- powiązania z przyszłą fakturą rozliczeniową.

#### XET.KSeF.FA3.OUT.ROZ.PROD
Faktura rozliczeniowa:
- rozliczenie wcześniejszych zaliczek,
- referencje do faktur ZAL.

#### XET.KSeF.FA3.OUT.UPR.PROD
Faktura uproszczona:
- ograniczony zakres danych,
- uproszczona struktura logiczna.

---

## 4. Korekty sprzedaży

Szablony korekt wymagają obowiązkowej gałęzi `DaneFaKorygowanej`.

### XET.KSeF.FA3.OUT.KOR.PROD
Korekta faktury VAT.

### XET.KSeF.FA3.OUT.KOR_ZAL.PROD
Korekta faktury zaliczkowej.

### XET.KSeF.FA3.OUT.KOR_ROZ.PROD
Korekta faktury rozliczeniowej.

---

## 5. Warianty logiczne szablonów

Warianty stosowane wyłącznie wtedy, gdy różnice:
- nie mogą być obsłużone samym `condition_expr`,
- wpływają na strukturę lub obowiązkowe węzły XET.

### Przykłady

#### XET.KSeF.FA3.OUT.VAT.JST.PROD
Faktura VAT dla jednostek samorządu terytorialnego (JST).

#### XET.KSeF.FA3.OUT.VAT.OFFLINE.PROD
Faktura wystawiana w trybie offline KSeF.

> Jeżeli różnice da się obsłużyć warunkami w jednym szablonie,
> nie należy tworzyć osobnego wariantu.

---

## 6. Zasady praktyczne

- Nazwa szablonu musi jednoznacznie wskazywać:
  - kierunek dokumentu,
  - typ dokumentu KSeF,
  - czy jest to szablon produkcyjny.
- Kod aplikacji nie powinien zgadywać przeznaczenia szablonu – nazwa jest kontraktem.
- Zmiana nazwy szablonu nie powinna zmieniać UUID (ciągłość danych).

---

## 7. Rekomendowane minimum produkcyjne

Dla sprzedaży w KSeF minimalny zestaw produkcyjny to:

- XET.KSeF.FA3.OUT.VAT.PROD
- XET.KSeF.FA3.OUT.ZAL.PROD
- XET.KSeF.FA3.OUT.ROZ.PROD
- XET.KSeF.FA3.OUT.KOR.PROD

Pozostałe szablony są rozszerzeniami funkcjonalnymi.


# Dostępne szablony w wersji 1.0

W niniejszej wersji modułu znajdują się wybrane z szablonów jako przykłady - gotowe do użycia. 
Szablony są w wersji uproszczonej i przygotowane do ich rozwijania i modyfikacji.
Jeśli planowane jest ich użycie, zalecane jest ich staranna weryfikacja pod kątem spełnienia pożądanych wymagań.


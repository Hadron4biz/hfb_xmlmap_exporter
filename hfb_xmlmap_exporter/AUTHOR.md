# Od autora

### Niniejsze oprogramowanie powstało jako odpowiedź na brak uniwersalnego narzędzia do obsługi wysyłki i odbioru faktur poprzez KSeF w wersji 2.0 dla środowisk Odoo, obserwowany w październiku i listopadzie 2025 r.

Celem było stworzenie rozwiązania umożliwiającego spójne zarządzanie zmianami w konfiguracji eksportowanych dokumentów faktur w postaci plików XML, bez konieczności ingerencji w kod aplikacji.

Prace nad wersją prototypową zakończyły sie w styczniu 2026 r.
Wersja 1.0, przeznaczona dla Odoo w wersjach 15, 16, 17 oraz 18+, została wydana w marcu 2026 r.

Uwzględniając wysoką zmienność przepisów fiskalnych w Rzeczypospolitej Polskiej na przestrzeni ostatnich dekad, jak również zmienność samego oprogramowania, opracowałem format wymiany informacji XET.
Format ten służy do generowania dokumentów w Odoo na podstawie schematów XSD.
Pliki w formacie XET stanowią szablony mapowania struktur opisanych w XSD na struktury danych Odoo.

---

#### Elementy struktury XML jako węzły, dla których definiowane są
- lokalizacja w strukturze wynikowej,
- warunki walidacji,
- warunki użycia (renderowania),
- sposób ustalenia wartości zwracanej.

#### Przygotowane szablony mogą być eksportowane oraz importowane pomiędzy instancjami Odoo, co umożliwia
- centralne przygotowanie konfiguracji,
- przenoszenie konfiguracji pomiędzy środowiskami,
- weryfikację poprawności generowanych dokumentów XML,
- wymianę szablonów między zespołami wdrożeniowymi.

#### Na oprogramowanie modułu składają się trzy główne komponenty
- moduł zarządzania konfiguracją szablonów XET,
- moduł dostawców i komunikacji API,
- moduł generowania dokumentów XML.

#### Z uwagi na ograniczony czas realizacji oraz dostępne zasoby, wersja 1.0 obejmuje
- dostawców API: lokalny katalog oraz KSeF,
- podstawowy generator dokumentów XML oparty o XET na potrzeby KSeF,
- klienta Java (pełna obsługa XAdES) do wysyłki i importu faktur VAT z KSeF,
- wbudowanego klienta Odoo (uproszczona obsługa XAdES) do wysyłki i importu faktur VAT z KSeF.
- obsługę certyfikatów KSeF generowanych w środowisku aplikacji KSeF Ministerstwa Finansów Rzeczypospolitej Polskiej.

#### Dalszy rozwój modułu
- integracja z systemami LLM/ML w zakresie wspomagania procesu analizy XSD → XET, oferowania dokumentów kontekstowych, automatyzacji procesu komunikacji poprzez API dostawców,
- wsparcie obsługi innych dostawców API

---

Uwzględniając powyższe, oprogramowanie w wersji 1.0 nie jest wolne od ograniczeń typowych dla wczesnego etapu rozwoju.
Pomimo to, moduł realizuje założone funkcje i stanowi bazę do dalszego rozwoju.

Andrzej Wiśniewski


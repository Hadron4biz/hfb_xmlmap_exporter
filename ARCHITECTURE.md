# ARCHITECTURE

## 1. Cel architektury

Celem architektury modułu jest rozdzielenie trzech niezależnych odpowiedzialności:

1. definicji struktury dokumentu (XML / XSD)  
2. generowania danych (mapowanie Odoo → XML)  
3. transportu i komunikacji (API, kolejki, retry)  

Rozdzielenie tych warstw eliminuje zależności pomiędzy:

- schematem dokumentu (KSeF FA(3)),
- logiką biznesową Odoo,
- implementacją integracji (API, Java, podpisy).

---

## 2. Przegląd warstw

Architektura modułu oparta jest o trzy główne warstwy:

+------------------------------------------------------+
| XET (XML Mapping Layer) |
| xml.export.template / xml.export.node |
+------------------------------------------------------+
| Communication Layer (Transport) |
| communication.log / communication.provider.* |
+------------------------------------------------------+
| Integration Layer (KSeF / Java / API) |
| ProviderKsefApiService / Java CLI / XAdES |
+------------------------------------------------------+


---

## 3. Warstwa XET (mapowanie XML)

### 3.1 Odpowiedzialność

Warstwa XET odpowiada wyłącznie za:

- odwzorowanie struktury XSD (np. FA(3))
- definiowanie węzłów XML
- określenie wartości i warunków ich użycia

Nie zawiera:

- logiki transportowej
- integracji API
- zależności od providerów

---

### 3.2 Główne modele

- `xml.export.template` – definicja dokumentu  
- `xml.export.node` – definicja pojedynczego węzła  

---

### 3.3 Definicja węzła

Każdy węzeł opisuje:

- `name` – nazwa elementu XML  
- `xpath` – pozycja w strukturze  
- `xsd_type_name` – typ wynikający z XSD  
- `sequence` – kolejność  
- `value_expr` – sposób wyliczenia wartości  
- `condition_expr` – warunek użycia  

---

### 3.4 Zasady renderowania

- jeśli `condition_expr`:
  - brak → renderuj  
  - `True` → renderuj  
  - `False` → pomiń węzeł i dzieci  

- węzeł może istnieć bez wartości, jeśli ma dzieci  

- struktura generowana jest rekurencyjnie  

---

### 3.5 Charakterystyka

- brak twardego kodowania XML w Pythonie  
- pełna zgodność z XSD jako źródłem prawdy  
- możliwość eksportu/importu konfiguracji  

---

## 4. Warstwa komunikacji

### 4.1 Odpowiedzialność

Warstwa komunikacji odpowiada za:

- obsługę kolejki operacji  
- retry  
- stan przetwarzania  
- izolację procesów  

---

### 4.2 Główny model

`communication.log`

Każdy rekord reprezentuje jedną operację, np.:

- wysyłka faktury  
- sprawdzenie statusu  
- pobranie UPO  
- import faktury  

---

### 4.3 Workflow

Typowy przepływ:

draft → generated → validated → queued → sent → received

oraz:

error / retry / waiting_delay


---

### 4.4 Operacje KSeF

Sterowanie odbywa się przez pola:

- `ksef_operation`  
- `ksef_next_operation`  
- `ksef_status`  

Sekwencja obejmuje m.in.:

- `auth`  
- `open_session`  
- `send_invoice`  
- `check_status`  
- `download_upo`  
- `close_session`  

---

### 4.5 Izolacja

Każdy proces:

- działa na własnym `communication.log`  
- posiada własny kontekst (`payload_context`)  
- może być ponawiany niezależnie  

---

## 5. Warstwa integracji (KSeF)

### 5.1 Odpowiedzialność

Warstwa integracyjna odpowiada za:

- komunikację z API KSeF  
- obsługę sesji  
- podpisywanie dokumentów (XAdES)  
- szyfrowanie  

Nie odpowiada za:

- generowanie XML  
- logikę biznesową Odoo  

---

### 5.2 Komponenty

- `communication.provider.ksef`  
- `ProviderKsefApiService`  
- integracja z Java CLI  

---

### 5.3 Podział Python / Java

**Python:**

- sterowanie procesem  
- zapis logów  
- decyzje workflow  

**Java:**

- podpis XAdES  
- szyfrowanie AES  
- operacje wymagane przez MF  

---

## 6. Tryb offline

### 6.1 Założenie

Offline jest osobnym przepływem, nie trybem awaryjnym.

---

### 6.2 Mechanizm

- tworzony jest nowy `communication.log`  
- stan: `offline_pending`  
- zapis kontekstu (deadline, tryb)  

---

### 6.3 Wznowienie

CRON:

- monitoruje dostępność KSeF  
- przełącza:

offline_pending → queued


---

## 7. QR (KSeF)

Konfiguracja QR jest wydzielona:

- provider udostępnia tylko URL  
- generowanie QR odbywa się w `account.move`  

Brak zależności:

- provider nie zna faktury  
- provider nie generuje QR  

---

## 8. Zasady projektowe

### 8.1 Separation of concerns

- XET → struktura  
- communication.log → proces  
- provider → transport  

---

### 8.2 XSD jako źródło prawdy

XML nie jest implementowany ręcznie.  
Struktura wynika bezpośrednio z XSD.

---

### 8.3 Brak logiki biznesowej w providerach

Provider:

- nie zna modeli biznesowych  
- nie zawiera mapowania danych  

---

### 8.4 Idempotencja operacji

Każdy krok może być:

- powtórzony  
- wznowiony  
- analizowany niezależnie  

---

## 9. Rozszerzalność

Architektura umożliwia:

- dodanie nowych providerów (np. EDI, Peppol)  
- obsługę nowych schematów XSD  
- rozszerzenie XET bez zmian w kodzie Python  

---

## 10. Ograniczenia

- poprawność XML zależy od poprawności danych wejściowych  
- brak walidacji biznesowej w XET  
- zależność od komponentów zewnętrznych (Java, API KSeF)  

---

## 11. Podsumowanie

Architektura modułu opiera się na pełnym rozdzieleniu:

- struktury dokumentu,  
- procesu generowania,  
- transportu i integracji.  

Dzięki temu:

- zmiany w XSD nie wymagają zmian w kodzie  
- komunikacja jest izolowana i kontrolowalna  
- system może być rozszerzany bez naruszania istniejącej logiki  




# Changelog

## [Unreleased]

### Added

#### communication.provider.ksef

- Dodano pole `api_backend` (Selection: `java | python`)
  - Umożliwia wybór klienta API KSeF.
  - Domyślna wartość: `java`.

---

#### communication.log

Dodano wsparcie dla danych kryptograficznych sesji oraz technicznych statusów API.

Nowe pola:

- `ksef_session_key` (Binary)  
  Klucz sesji AES-256 wykorzystywany do szyfrowania faktur (backend Python).

- `ksef_session_iv` (Binary)  
  Wektor inicjujący (IV) dla szyfrowania AES.

- `ksef_http_status` (Integer)  
  Kod odpowiedzi HTTP zwracany przez API KSeF.

- `ksef_api_status_code` (Integer)  
  Kod statusu logicznego zwracany przez API KSeF.

- `ksef_api_status_message` (Text)  
  Szczegółowy komunikat odpowiedzi API KSeF.

- `ksef_sent_datetime` (Datetime)  
  Data i czas skutecznego przesłania dokumentu do KSeF.

---

### Architecture

- Zachowano istniejący mechanizm powiązania dokumentu:
  - `document_model`
  - `document_id`
  - `import_move_id`

- Nie wprowadzono duplikacji pól:
  - `ksef_reference_number`
  - `ksef_session_token`
  - `ksef_invoice_number`
  - `ksef_number` (account.move)
  - `ksef_sent_date` (account.move)

- Tokeny (access/refresh) pozostają przechowywane na poziomie firmy.
- `communication.log` pozostaje źródłem prawdy dla stanu procesu KSeF.
- Pola w `account.move` pełnią funkcję odzwierciedlenia biznesowego.

---

### Technical Notes

Zmiany przygotowują system do:

- obsługi backendu Python (pełnej lub hybrydowej),
- rozdzielenia statusów HTTP i statusów logicznych API,
- bezpiecznej obsługi równoległych sesji,
- spójnego modelu retry i harmonogramowania.



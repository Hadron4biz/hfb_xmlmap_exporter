# wizard/README.md

Katalog `wizard/` zawiera **kreator nazwy szablonu** (TransientModel) służący do zbudowania *jednego, kanonicznego* ciągu znaków będącego nazwą i wersją szablonu oraz do wskazania **załącznika XSD**. Kreator jest neutralny domenowo (PEPPOL, eFaktura, KSeF, UBL, X12, custom – wszystkie mieszczą się w parametrach) i nie wykonuje żadnego mapowania pól. Wynik służy dalej modelowi szablonu.

---

## Co robi ten kreator

- Przyjmuje **plik XSD** (ir.attachment).
- Użytkownik wybiera składowe nazwy (Odoo, system, dokument, wersja szablonu).
- Kreator składa **kanoniczną nazwę** w formacie:

```
odoo-<odoo_ver>-<system>-<system_ver>-<doc_type>-<tpl_semver>
```

Przykład: `odoo-19.0-peppol-3.0-bill-1.2.3`

- Po zatwierdzeniu tworzy rekord `xml.export.template` z:
  - `name` = złożona nazwa,
  - `xsd_attachment_id` = wskazany schemat.
- **Żadnych** dalszych działań (walidacja/eksport/mapowanie) — to jest domena modelu szablonu.

---

## Modele i widoki

- Model: `xml.template.name.wizard` *(TransientModel)*
- Widok formularza: `xml.template.name.wizard.form`
- Akcja okna: `action_xml_template_name_wizard`

Pliki:
- Python: `wizard/template_name_wizard.py`
- Widok: `wizard/template_name_wizard_views.xml`

---

## Pola kreatora (skrót)

- **Schemat**  
  `xsd_attachment_id` – wymagany załącznik XSD (ir.attachment)

- **Odoo**  
  `odoo_version_major` – Selection (14..19), wymagane  
  `odoo_version_minor` – Char (opcjonalne)

- **System docelowy**  
  `system_id` – Char, wymagane (np. `peppol`, `efaktura`, `ubl`, `x12`, `custom`)  
  `system_ver` – Char, wymagane (np. `3.0`, `bis3`, `2.3`, `4010`, `2025.10`)

- **Dokument**  
  `doc_type` – Selection: `bill`, `order`, `despatch`, `creditnote`, `debitnote`, `remittance`, `statement`, `catalog`

- **Wersja szablonu (semver)**  
  `tpl_ver_major`, `tpl_ver_minor`, `tpl_ver_patch` – Integery ≥ 0

- **Podgląd**  
  `preview_name` – computed, readonly (złożona nazwa)

---

## Format nazwy i walidacja

- Zasady:
  - lowercase,
  - separatory `-` między segmentami,
  - dopuszczalne znaki:  
    - `system_id`: `[a-z0-9_]+`  
    - `system_ver`: `[a-z0-9._]+`  
    - `doc_type`: `[a-z][a-z0-9_]*`  
    - `odoo_ver`: `\d+(\.\d+)?`  
    - `tpl_semver`: `\d+\.\d+\.\d+`

- Globalny regex (spójny 14→19):

```
^odoo-\d+(?:\.\d+)?-[a-z0-9_]+-[a-z0-9._]+-[a-z][a-z0-9_]*-\d+\.\d+\.\d+$
```

- Semver: każde z pól `tpl_ver_*` musi być liczbą całkowitą ≥ 0.

---

## Przepływ użytkownika

1. Otwórz akcję: **Ustawienia → Techniczne** (lub z menu modułu) → „Kreator nazwy szablonu”.  
   ID akcji: `action_xml_template_name_wizard`.

2. Wskaż **XSD** oraz uzupełnij pola: Odoo, System, Wersja systemu, Typ dokumentu, Semver.

3. Sprawdź **Podgląd nazwy**.

4. Kliknij **Potwierdź**. Kreator utworzy rekord `xml.export.template` z wypełnionym `name` i `xsd_attachment_id` i otworzy formularz szablonu.  
   Dalsze przetwarzanie (walidacja, import struktury, mapowanie) realizuje model szablonu — **nie** wizard.

---

## Bezpieczeństwo i dostęp

- Uprawnienia są definiowane wyłącznie w `security/ir.model.access.csv` (kompatybilnie 14→19).  
  Minimalny wpis dla wizarda:

```csv
access_xml_template_name_wizard_user,xml.template.name.wizard user,model_xml_template_name_wizard,base.group_user,1,0,1,0
```

- **Kolejność ładowania** w `__manifest__.py` (potwierdzona w projekcie):

```python
"data": [
    "security/ir.model.access.csv",
    "views/actions.xml",
    "views/xml_template_views.xml",
    "wizard/template_name_wizard_views.xml",
    "views/menu.xml",
],
```

---

## Zgodność wersji Odoo (14 → 19)

- Formularz używa klasycznych widoków (bez Owl/BS5 własności), przycisków `oe_highlight` / `oe_link` → działa w dół.  
- Brak assetów, brak zależności JS.  
- `TransientModel`, `@api.depends`, `@api.constrains`, `ValidationError` – stabilne w tym zakresie wersji.

---

## Błędy i wskazówki

- **AccessError przy otwieraniu**: brak wpisu w `ir.model.access.csv` dla `xml.template.name.wizard` lub zła kolejność ładowania.
- **Niepoprawna nazwa**: komunikat z walidatora wskaże, które pola naruszają format (regex powyżej).
- **Załącznik XSD wymagany**: bez niego kreator nie zatwierdzi formularza.

---

## Scope i anty-scope (ważne)

- Kreator **nie** rozpoznaje i **nie** mapuje schematów; XSD służy wyłącznie jako **załącznik** oraz źródło dalszego przetwarzania *poza* wizardem.  
- Kreator **nie** tworzy węzłów, namespace’ów ani konfiguracji eksportu.  
- Kreator **nie** zapisuje nic poza rekordem `xml.export.template` (name + XSD).

---

## Zmiany (skrót)

- **v1.0** – Wersja bazowa README dla wizarda nazwy szablonu.

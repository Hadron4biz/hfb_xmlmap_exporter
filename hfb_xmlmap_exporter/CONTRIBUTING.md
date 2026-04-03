# Zasady kontrybucji / Contributing Guidelines

## Wybór języka / Language Choice
- Kod źródłowy i komentarze techniczne piszemy w języku angielskim
- Dokumentacja użytkownika i komunikaty dla użytkownika mogą być w języku polskim lub angielskim
- Komentarze w kodzie dotyczące praw autorskich i licencji są dwujęzyczne (PL/EN)

- Source code and technical comments should be in English
- User documentation and user messages can be in Polish or English
- Copyright and license comments in code are bilingual (PL/EN)

## Licencja i prawa / License and Rights

### Licencja kodu / Code License
Kontrybuując do tego projektu, zgadzasz się na udostępnienie swojego kodu na licencji **GNU Affero General Public License v3 (AGPLv3)**.

By contributing to this project, you agree to license your code under the **GNU Affero General Public License v3 (AGPLv3)**.

### Znaki towarowe / Trademarks
**"XET"** i **"Hadron for Business"** są zastrzeżonymi znakami towarowymi. Nie możesz ich używać w nazwach swoich forków, modułów czy firm bez pisemnej zgody.

**"XET"** and **"Hadron for Business"** are trademarks. You cannot use them in names of your forks, modules or companies without written permission.

### Koncepcje i pomysły / Concepts and Ideas
Koncepcje biznesowe, algorytmy i rozwiązania projektowe pozostają własnością Hadron for Business. Kontrybucje nie przenoszą praw do tych koncepcji.

Business concepts, algorithms and design solutions remain the property of Hadron for Business. Contributions do not transfer rights to these concepts.

## Proces kontrybucji / Contribution Process

### 1. Zgłoszenia / Issues
- Sprawdź czy podobne zgłoszenie już istnieje
- Użyj szablonu zgłoszenia jeśli dostępny
- Opisz problem lub proponowaną funkcjonalność jasno i szczegółowo

- Check if similar issue already exists
- Use issue template if available
- Describe the problem or feature request clearly and in detail

### 2. Fork i branch / Fork and branch
git checkout -b feature/nazwa-funkcjonalnosci
# lub / or
git checkout -b fix/nazwa-bugu

### 3. Standardy kodu / Code Standards
Python
	Zgodność z PEP 8

	Linia z modelem (np. _name = 'xet.model') powinna być poprzedzona komentarzem
	Wszystkie metody powinny mieć docstring
	Używamy nazewnictwa: modele (xet.model), pola (field_name), metody (action_method)
	PEP 8 compliance
	Model line (e.g., _name = 'xet.model') should be preceded by a comment
	All methods should have docstrings
	Naming conventions: models (xet.model), fields (field_name), methods (action_method)

XML
	Wcięcia 4 spacje
	Atrybuty w kolejności: name, model, id (dla record), potem pozostałe
	Zamykaj tagi na osobnej linii dla złożonych elementów
	4 spaces indentation
	Attributes order: name, model, id (for record), then others
	Close tags on new line for complex elements

JavaScript
	Zgodność z ESLint config projektu
	Używaj odoo.define() dla modułów
	Komentarze dla publicznych metod
	ESLint config compliance
	Use odoo.define() for modules
	Comments for public methods

Nagłówki plików / File Headers
Python (.py)

	# -*- coding: utf-8 -*-
	# vim: tabstop=4 softtabstop=0 shiftwidth=4 smarttab expandtab fileformat=unix
	#################################################################################
	# Copyright (C) [rok] Hadron for Business sp. z o.o.
	# License AGPLv3 - see LICENSE file for details
	#################################################################################
	# UWAGA / NOTICE: Znaki towarowe i koncepcje - patrz NOTICE
	#################################################################################

XML (.xml)

	<?xml version="1.0" encoding="utf-8"?>
	<!-- vim: tabstop=4 softtabstop=0 shiftwidth=4 smarttab expandtab fileformat=unix -->
	<!--
	#################################################################################
	# Copyright (C) [rok] Hadron for Business sp. z o.o.
	# License AGPLv3 - see LICENSE file for details
	#################################################################################
	# UWAGA / NOTICE: Znaki towarowe i koncepcje - patrz NOTICE
	#################################################################################
	-->

### 4. Commity / Commits
Używaj języka angielskiego w commit message
- Format: [typ] Krótki opis (max 50 znaków)
- Typy: [ADD], [FIX], [IMP], [REF], [REM], [DOC]
- W opisie szczegółowym wyjaśnij DLACZEGO, nie CO
- Use English for commit messages
- Format: [type] Short description (max 50 chars)
- Types: [ADD], [FIX], [IMP], [REF], [REM], [DOC]
- In detailed description explain WHY, not WHAT

Przykład / Example:

text
[ADD] New field for customer VAT validation

Added vat_required field on res.partner to enforce VAT number
entry for customers in EU countries. This helps with compliance
for intra-community transactions.

Task: #1234

### 5. Pull Request
- PR opisuje co zmienia i dlaczego
- Odnosi się do istniejącego issue (jeśli dotyczy)
- Przechodzi wszystkie testy CI
- Aktualizuje dokumentację jeśli potrzebna
- Dodaje wpis do CHANGELOG.md
- PR describes what it changes and why
- References existing issue (if applicable)
- Passes all CI tests
- Updates documentation if needed
- Adds entry to CHANGELOG.md

### 6. Review
- Bądź otwarty na feedback
- Odpowiadaj na komentarze w rozsądnym czasie
- Wprowadzaj poprawki w kolejnych commitach (nie squashed)
- Be open to feedback
- Respond to comments in reasonable time
- Make corrections in additional commits (not squashed)

### Testy / Testing
- Dodawaj testy dla nowych funkcjonalności
- Upewnij się że wszystkie testy przechodzą
- Testuj na różnych wersjach Odoo jeśli to możliwe
- Add tests for new features
- Ensure all tests pass
- Test on different Odoo versions if possible

### Dokumentacja / Documentation
- Aktualizuj README.md jeśli zmieniasz funkcjonalność
- Dokumentuj niestandardowe metody w kodzie
- Dodawaj komentarze dla złożonej logiki
- Update README.md if changing functionality
- Document non-standard methods in code
- Add comments for complex logic

### Kontakt / Contact
W razie pytań dotyczących kontrybucji:
For questions about contributing:

Hadron for Business sp. z o.o.
Email: info@hadronforbusiness.com
WWW: http://ksef.odoo.com

Dziękujemy za zainteresowanie rozwojem modułu!
Thank you for your interest in developing the module!

🧩 Pełny model ról w ekosystemie XET
🧑💼 Konsultant wdrożeniowy
    • projektuje strukturę dokumentu,
    • mapuje dane biznesowe do szablonu XET,
    • konfiguruje warunki i warianty,
    • przygotowuje szablon do bezpiecznego użycia operacyjnego.
➡️ oddaje użytkownikowi gotowy, sprawdzony szablon

🔌 Integrator systemowy
    • konfiguruje providera (np. KSeF),
    • ustawia środowiska, tryby, harmonogramy,
    • odpowiada za komunikację z systemami zewnętrznymi,
    • nadzoruje procesy asynchroniczne.
➡️ zapewnia stabilne połączenie systemów

🧑💻 Developer
    • rozwija silnik XET,
    • tworzy nowe providery,
    • dba o bezpieczeństwo i wydajność,
    • utrzymuje platformę techniczną.
➡️ zapewnia ewolucję i stabilność rozwiązania

🧑💼 Użytkownik biznesowy (rola operacyjna) ← brakujący element
    • korzysta z gotowego szablonu XET,
    • pracuje na dokumentach (np. fakturach),
    • waliduje dokument przed wysyłką,
    • otrzymuje czytelne komunikaty o błędach,
    • podejmuje decyzję: wysłać / poprawić / wstrzymać.
➡️ nie konfiguruje, nie programuje – kontroluje i zatwierdza

🔍 Co dokładnie robi użytkownik w XET?
Użytkownik biznesowy:
    • wybiera przypisany szablon XET,
    • generuje dokument (XML) w trybie podglądu,
    • uruchamia walidację strukturalną (XSD),
    • otrzymuje:
        ◦ listę braków,
        ◦ wskazanie błędnych danych,
        ◦ informację, czy dokument jest gotowy do wysyłki,
    • dopiero po pozytywnej walidacji:
        ◦ zatwierdza wysyłkę,
        ◦ uruchamia proces komunikacji.
XET działa tu jak bezpieczna bramka jakości danych.

🛡️ Dlaczego ta rola jest kluczowa
Bez XET:
    • użytkownik wysyła dokument „w ciemno”,
    • błędy wychodzą dopiero w systemie zewnętrznym,
    • odpowiedzialność jest niejasna.
Z XET:
    • błędy są wykrywane przed wysyłką,
    • użytkownik widzi co i dlaczego jest niepoprawne,
    • decyzja biznesowa jest świadoma i kontrolowana.

📊 Zaktualizowana tabela ról
Rola	Główna odpowiedzialność	Praca z XET
Użytkownik biznesowy	Kontrola i zatwierdzanie	Walidacja, decyzja
Konsultant	Konfiguracja i mapowanie	Szablony, warunki
Integrator	Połączenia systemów	Providery, sesje
Developer	Rozwój platformy	Core, API



#!/bin/bash
# i jeden wiersz: 
#	for f in views/*.xml wizard/*.xml; do [ -f "$f" ] && grep -q "$f" __manifest__.py || echo "Brak w manifest: $f"; done
#
# Sprawdzenie plików XML w katalogach views i wizard
echo "Sprawdzanie plików XML w katalogach views i wizard..."
echo "=================================================="

# Znajdź wszystkie pliki .xml w katalogach views i wizard
for xml_file in $(find views wizard -name "*.xml" -type f | sort); do
    # Sprawdź czy plik jest wymieniony w __manifest__.py
    if ! grep -q "$xml_file" __manifest__.py; then
        echo "❌ BRAK: $xml_file nie znaleziony w __manifest__.py"
    else
        echo "✅ OK: $xml_file jest zadeklarowany"
    fi
done

# Opcjonalnie: sprawdź też czy wszystkie zadeklarowane pliki istnieją
echo ""
echo "Sprawdzanie czy zadeklarowane pliki istnieją na dysku..."
echo "========================================================"

# Wyciągnij ścieżki plików z __manifest__.py
grep -E "views/.*\.xml|wizard/.*\.xml" __manifest__.py | grep -oE "(views|wizard)/[a-zA-Z0-9_/-]*\.xml" | sort -u | while read -r declared_file; do
    if [ ! -f "$declared_file" ]; then
        echo "❌ BRAKUJE: $declared_file jest zadeklarowany ale nie istnieje na dysku"
    else
        echo "✅ OK: $declared_file istnieje"
    fi
done
#EoF

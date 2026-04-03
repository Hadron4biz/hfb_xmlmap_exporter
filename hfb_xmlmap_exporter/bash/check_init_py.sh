#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo "Sprawdzanie plików Python w podkatalogach..."
echo "=========================================="

# Znajdź wszystkie pliki .py (oprócz __init__.py) w podkatalogach
find models wizard -name "*.py" -type f ! -name "__init__.py" | sort | while read check_file; do
    # Pobierz katalog gdzie znajduje się plik
    file_dir=$(dirname "$check_file")
    init_file="$file_dir/__init__.py"
    
    # Sprawdź czy plik istnieje i czy jest zaimportowany w __init__.py
    if [ -f "$init_file" ]; then
        # Wyciągnij nazwę pliku bez rozszerzenia .py
        filename=$(basename "$check_file" .py)
        
        # Sprawdź różne formaty importów w __init__.py
        if grep -q -E "import[[:space:]]+$filename|from[[:space:]]+\.?[[:space:]]*import[[:space:]]+$filename" "$init_file"; then
            echo -e "${GREEN}✓ ${check_file}${NC} - OK (zaimportowany w $init_file)"
        else
            echo -e "${RED}✗ ${check_file}${NC} - brak importu w $init_file"
        fi
    else
        echo -e "${RED}✗ ${check_file}${NC} - brak pliku $init_file"
    fi
done

# Dodatkowo: sprawdź czy są jakieś puste __init__.py
echo ""
echo "Sprawdzanie pustych plików __init__.py..."
echo "========================================"

find models wizard -name "__init__.py" -type f | while read init_file; do
    if [ ! -s "$init_file" ]; then
        echo -e "${RED}⚠ PUSTY: ${init_file}${NC} - plik jest pusty"
    else
        echo -e "${GREEN}✓ ${init_file}${NC} - zawiera importy"
    fi
done

# Sprawdź czy wszystkie zadeklarowane importy mają odpowiadające pliki
echo ""
echo "Sprawdzanie czy zaimportowane pliki istnieją..."
echo "=============================================="

find models wizard -name "__init__.py" -type f | while read init_file; do
    file_dir=$(dirname "$init_file")
    
    # Znajdź wszystkie importy w __init__.py
    grep -E "import[[:space:]]+[a-zA-Z_]+|from[[:space:]]+\.?[[:space:]]*import[[:space:]]+[a-zA-Z_]+" "$init_file" | while read line; do
        # Wyciągnij nazwy plików z importów
        echo "$line" | grep -o -E "import[[:space:]]+([a-zA-Z_]+)" | cut -d' ' -f2 | while read module; do
            if [ ! -f "$file_dir/$module.py" ] && [ ! -f "$file_dir/$module/__init__.py" ]; then
                echo -e "${RED}✗ ${file_dir}/$module.py${NC} - zaimportowany w $init_file ale nie istnieje"
            fi
        done
        
        # Sprawdź importy z "from ... import ..."
        echo "$line" | grep -o -E "from[[:space:]]+\.?[[:space:]]*import[[:space:]]+([a-zA-Z_,[:space:]]+)" | sed 's/from[[:space:]]*\.*[[:space:]]*import[[:space:]]*//' | tr ',' '\n' | tr -d ' ' | while read module; do
            if [ ! -z "$module" ] && [ ! -f "$file_dir/$module.py" ]; then
                echo -e "${RED}✗ ${file_dir}/$module.py${NC} - zaimportowany w $init_file ale nie istnieje"
            fi
        done
    done
done

echo ""
echo "Sprawdzanie zakończone."
#EoF

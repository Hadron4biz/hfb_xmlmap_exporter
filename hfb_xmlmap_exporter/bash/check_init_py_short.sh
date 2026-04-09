RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "Sprawdzanie plików Python..."

find models wizard -name "*.py" -type f ! -name "__init__.py" | sort | while read check_file; do
    dir=$(dirname "$check_file")
    module=$(basename "$check_file" .py)
    
    if [ -f "$dir/__init__.py" ] && grep -q "import.*$module\|from.*import.*$module" "$dir/__init__.py"; then
        echo -e "${GREEN}✓ ${check_file}${NC}"
    else
        echo -e "${RED}✗ ${check_file} - brak importu w $dir/__init__.py${NC}"
    fi
done
#EoF

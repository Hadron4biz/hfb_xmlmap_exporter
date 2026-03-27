# Pełna weryfikacja dla trybu host
./sprawdz-po-instalacji.py . --mode host

# Weryfikacja dla odoo.sh
./sprawdz-po-instalacji.py . --mode odoo.sh

# Generowanie requirements.txt
./sprawdz-po-instalacji.py . --mode host --generate-requirements

# Zapisz raport do pliku
./sprawdz-po-instalacji.py . --mode host --save-report raport.json

# Wyświetl raport w formacie JSON
./sprawdz-po-instalacji.py . --mode host --output json

# Pomiń dodatkowe lokalne moduły
./sprawdz-po-instalacji.py . --mode host --ignore my_custom_module --ignore another_module


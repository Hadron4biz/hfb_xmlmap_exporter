## Pełna weryfikacja dla trybu host
	python3 sprawdz-po-instalacji.py . --mode host

## Weryfikacja dla odoo.sh
	python3 sprawdz-po-instalacji.py . --mode odoo.sh

## Generowanie requirements.txt
	python3 sprawdz-po-instalacji.py . --mode host --generate-requirements

## Zapisz raport do pliku
	python3 sprawdz-po-instalacji.py . --mode host --save-report raport.json

## Wyświetl raport w formacie JSON
	python3 sprawdz-po-instalacji.py . --mode host --output json

## Pomiń dodatkowe lokalne moduły
	python3 sprawdz-po-instalacji.py . --mode host --ignore my_custom_module --ignore another_module


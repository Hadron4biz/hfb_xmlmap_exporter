# Przygotowanie pól Node dla podatków w szablonie XET

## Stawka 23% (P_13_1 / P_14_1)
	{
		"tag": "P_13_1",
		"condition_expr": "record.get_ksef_p13('23') is not None",
		"value_expr": "record.get_ksef_p13('23')"
	},
	{
		"tag": "P_14_1",
		"condition_expr": "record.get_ksef_p14('23') is not None",
		"value_expr": "record.get_ksef_p14('23')"
	}

## Stawka 8% (P_13_2 / P_14_2)
	{
		"tag": "P_13_2",
		"condition_expr": "record.get_ksef_p13('8') is not None",
		"value_expr": "record.get_ksef_p13('8')"
	},
	{
		"tag": "P_14_2",
		"condition_expr": "record.get_ksef_p14('8') is not None",
		"value_expr": "record.get_ksef_p14('8')"
	}

### Stawka 5% (P_13_3 / P_14_3)
	{
		"tag": "P_13_3",
		"condition_expr": "record.get_ksef_p13('5') is not None",
		"value_expr": "record.get_ksef_p13('5')"
	},
	{
		"tag": "P_14_3",
		"condition_expr": "record.get_ksef_p14('5') is not None",
		"value_expr": "record.get_ksef_p14('5')"
	}

## Stawka 0% (P_13_6_x)

### 0% Krajowe / Pozostałe (P_13_6_1):
	{
		"tag": "P_13_6_1",
		"condition_expr": "record.get_ksef_p13('0 KR') is not None",
		"value_expr": "record.get_ksef_p13('0 KR')"
	}

### Wewnątrzwspólnotowa Dostawa Towarów (P_13_6_2):
	{
		"tag": "P_13_6_2",
		"condition_expr": "record.get_ksef_p13('0 WDT') is not None",
		"value_expr": "record.get_ksef_p13('0 WDT')"
	}

### Eksport Towarów (P_13_6_3):
	{
		"tag": "P_13_6_3",
		"condition_expr": "record.get_ksef_p13('0 EX') is not None",
		"value_expr": "record.get_ksef_p13('0 EX')"
	}

## Zwolnione (zw) i Nie podlegające (np)

### Zwolnione (P_13_7):
	{
		"tag": "P_13_7",
		"condition_expr": "record.get_ksef_p13('zw') is not None",
		"value_expr": "record.get_ksef_p13('zw')"
	}

### Poza terytorium kraju (P_13_8 i P_13_9):
	{
		"tag": "P_13_8",
		"condition_expr": "record.get_ksef_p13('np I') is not None",
		"value_expr": "record.get_ksef_p13('np I')"
	},
	{
		"tag": "P_13_9",
		"condition_expr": "record.get_ksef_p13('np II') is not None",
		"value_expr": "record.get_ksef_p13('np II')"
	}	



## SUMA
	{
		"tag": "P_15",
		"value_expr": "record.get_ksef_p15()"
	}



## Jeśli faktura jest w PLN, nie dodawaj pól z literą W na końcu. Jeśli jednak planujesz faktury w EUR, dla każdej stawki musisz dodać bliźniaczy tag:
	{
		"tag": "P_14_1W",
		"condition_expr": "record.currency_id.name != 'PLN' and record.get_ksef_p14('23') is not None",
		"value_expr": "record.get_ksef_p14('23')"
	}
	
### W KSeF przy walucie obcej:
	P_14_1 = kwota VAT przeliczona na PLN (musielibyśmy dopisać metodę get_ksef_p14_pln).

	P_14_1W = kwota VAT w walucie faktury (np. EUR).



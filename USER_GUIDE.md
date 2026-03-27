## **Kroki dla instalcji / flow**

### **1. Instalacja**

* instalacja modułu `hfb_xmlmap_exporter`

---

### **2. Weryfikacja po instalacji**

* uruchomienie `sprawdz-po-instalacji.py`

---

### **3. Konfiguracja Odoo (globalna)**

* użytkownicy
* uprawnienia
* słowniki podatkowe (zgodne z KSeF)

---

### **4. Konfiguracja modułu**

#### **4.1 Schemy i mapowanie**

* import schemy XSD
* konfiguracja XET
* import XET
* eksport XET

---

#### **4.2 Warstwa integracyjna (Provider)**

* utworzenie Providera
* konfiguracja Providera (endpointy, auth, tryb: test/prod)
* powiązanie Providera z szablonami (XET)

**Wymaganie dodatkowe:**

* instrukcja wygenerowania certyfikatów w
  KSeF 2.0
* pobranie certyfikatów (klucz prywatny + certyfikat publiczny)
* wgranie certyfikatów do konfiguracji Providera

---

### **5. Operacje użytkownika (faktura)**

* przypisanie szablonu do faktury
* weryfikacja dokumentu (składnia)
* wysłanie dokumentu do kolejki obsługi
* kontrola statusu wysyłki

---

### **6. Automatyzacja**

* konfiguracja cronów:

  * wysyłka
  * odbiór

---

### **7. Kontrola procesu**

* monitoring statusu wysyłki
* weryfikacja odpowiedzi KSeF

---


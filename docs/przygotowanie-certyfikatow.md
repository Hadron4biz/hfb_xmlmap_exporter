# Przygotowanie certyfikatów .p12 dla integracji z KSeF

Niniejszy dokument opisuje sprawdzony sposób przygotowania certyfikatów PKCS#12 (.p12) na potrzeby integracji z systemem KSeF (Krajowy System e-Faktur), po otrzymaniu plików w formacie PEM z aplikacji Ministerstwa Finansów.

Instrukcja dotyczy certyfikatów:
- AUTH – uwierzytelnienie do KSeF,
- SIGN – podpis dokumentów.

## 1. Wymagania wstępne

### 1.1. Obsługiwany algorytm
Certyfikaty muszą być oparte o algorytm RSA.

Certyfikaty ECDSA / EC (np. id-ecPublicKey) nie są obsługiwane przez aktualny mechanizm uwierzytelniania i spowodują błąd podczas operacji AUTH.

### 1.2. Sprawdzenie algorytmu certyfikatu
Dla każdego certyfikatu (AUTH oraz SIGN) wykonaj:

openssl x509 -in certyfikat-api-auth.crt -text -noout | grep "Public Key Algorithm"

**Poprawny wynik:**
Public Key Algorithm: rsaEncryption

**Jeżeli wynik to:**
id-ecPublicKey

➡ certyfikat nie może zostać użyty – należy wygenerować nowy certyfikat RSA w aplikacji MF KSeF.

## 2. Pliki wejściowe

Po pobraniu certyfikatów z aplikacji MF KSeF w katalogu roboczym powinny znajdować się:

### AUTH (uwierzytelnienie)
- certyfikat-api-auth.crt – certyfikat użytkownika (RSA)
- certyfikat-api-auth.key – klucz prywatny

### SIGN (podpis)
- certyfikat-api-sign.crt
- certyfikat-api-sign.key


## 3. Tworzenie pliku .p12 – AUTH

W katalogu z plikami wykonaj polecenie:

openssl pkcs12 -export \
  -inkey certyfikat-api-auth.key \
  -in certyfikat-api-auth.crt \
  -name ksef-auth \
  -out certyfikat-api-auth.p12

Podczas wykonywania polecenia:
- ustaw hasło do keystore (będzie wymagane w konfiguracji integracji),
- zapamiętaj hasło – musi być identyczne jak w konfiguracji systemu.

### 3.1. Weryfikacja pliku AUTH

keytool -list -v -storetype PKCS12 -keystore certyfikat-api-auth.p12

Sprawdź:
- Entry type = PrivateKeyEntry
- Signature algorithm name = SHA256withRSA
- Alias name = ksef-auth

## 4. Tworzenie pliku .p12 – SIGN

Analogicznie wykonaj:

openssl pkcs12 -export \
  -inkey certyfikat-api-sign.key \
  -in certyfikat-api-sign.crt \
  -name ksef-sign \
  -out certyfikat-api-sign.p12

### 4.1. Weryfikacja pliku SIGN

keytool -list -v -storetype PKCS12 -keystore certyfikat-api-sign.p12

Sprawdź:
- Entry type = PrivateKeyEntry
- Signature algorithm name = SHA256withRSA
- Alias name = ksef-sign


## 5. Wgrywanie certyfikatów do systemu

Po poprawnym przygotowaniu plików .p12 należy wgrać je do konfiguracji integracji (KSeF / communication.provider.ksef):

| Pole konfiguracyjne | Wartość |
|---------------------|---------|
| AUTH keystore | certyfikat-api-auth.p12 (zakodowany base64) |
| AUTH password | hasło z openssl pkcs12 -export |
| AUTH alias | ksef-auth |
| SIGN keystore | certyfikat-api-sign.p12 (base64) |
| SIGN password | hasło |
| SIGN alias | ksef-sign |

Pole „Klucz publiczny MF” należy uzupełnić certyfikatem MF w formacie PEM (np. SymmetricKeyEncryption), zgodnie z dokumentacją MF.

## 6. Najczęstsze problemy i ich przyczyny

### 6.1. Błąd: No certificate found
Najczęstsze przyczyny:
- certyfikat ECDSA zamiast RSA,
- niepoprawnie utworzony plik .p12,
- niezgodny alias (-name podczas tworzenia .p12).

### 6.2. AUTH nie działa mimo poprawnego .p12
- sprawdź algorytm (rsaEncryption),
- sprawdź hasło keystore,
- upewnij się, że .p12 został wygenerowany ponownie z plików PEM, a nie pochodzi z innej konfiguracji.

## 7. Podsumowanie
- integracja KSeF wymaga certyfikatów użytkownika w formacie .p12,
- certyfikaty muszą być RSA,
- alias i hasło keystore są krytyczne,
- poprawne przygotowanie certyfikatów eliminuje błędy na etapie AUTH.



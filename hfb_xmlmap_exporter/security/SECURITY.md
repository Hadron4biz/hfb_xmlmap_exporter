# Konfiguracja bezpieczeństwa dla hfb_xmlmap_exporter

## Opis ogólny
Niniejszy dokument opisuje model bezpieczeństwa dla modułu XML Map Exporter, w tym prawa dostępu, grupy użytkowników oraz reguły rekordów.

## Struktura plików bezpieczeństwa

	security/
	├── ir.model.access.csv # Prawa dostępu na poziomie modeli
	└── security.xml # Grupy użytkowników i reguły rekordów


## Grupy użytkowników

### XML Export Administrator
- **Nazwa techniczna:** `hfb_xmlmap_exporter.group_xml_export_admin`
- **Kategoria:** Narzędzia
- **Cel:** Pełny dostęp administracyjny do konfiguracji eksportu XML
- **Uprawnienia:**
  - Pełne operacje CRUD na szablonach eksportu, węzłach i przestrzeniach nazw
  - Dostęp do wszystkich modeli związanych z eksportem XML

## Prawa dostępu do modeli (ir.model.access.csv)

### Główne modele eksportu XML (Użytkownik + Admin)
| Model | Grupa użytkownika | Grupa admin | Uprawnienia użytkownika | Uprawnienia admin |
|-------|-------------------|-------------|------------------------|-------------------|
| `xml.template.exporter` | base.group_user | group_xml_export_admin | R,O,U | R,O,U,S |
| `xml.export.template` | base.group_user | group_xml_export_admin | R,O,U | R,O,U,S |
| `xml.export.node` | base.group_user | group_xml_export_admin | R,O,U | R,O,U,S |
| `xml.export.namespace` | base.group_user | group_xml_export_admin | R,O,U | R,O,U,S |

**Legenda:** R=Odczyt, O=Tworzenie, U=Modyfikacja, S=Usuwanie

**Uprawnienia użytkownika:** Odczyt, Modyfikacja, Tworzenie (brak usuwania)  
**Uprawnienia administratora:** Pełny dostęp (Odczyt, Tworzenie, Modyfikacja, Usuwanie)

### Kreatory (dane tymczasowe)
| Model | Grupa | Uprawnienia |
|-------|-------|-------------|
| `xml.template.name.wizard` | base.group_user | R, Tworzenie |
| `xml.template.xsd.upload.wizard` | base.group_user | R, Tworzenie |
| `xml.xsd.import.wizard` | base.group_system | R,O,U,S |
| `xml.xsd.import.line` | base.group_system | R,O,U,S |
| `xml.template.import.json.wizard` | Publiczny | R,O,U,S |

### Modele walidacji
| Model | Grupa | Uprawnienia |
|-------|-------|-------------|
| `xml.validation.log` | base.group_user | Tylko odczyt |
| `xml.validation.log` | base.group_system | R,O,U,S |
| `xml.xsd.type` | base.group_system | R,O,U,S |
| `xml.xsd.element` | base.group_system | R,O,U,S |

### Modele komunikacji
| Model | Grupa | Uprawnienia |
|-------|-------|-------------|
| `communication.log` | base.group_system | R,O,U,S |
| `communication.provider` | base.group_system | R,O,U,S |
| `communication.provider.localdir` | base.group_system | R,O,U,S |
| `communication.provider.localdir` | base.group_user | R,O,U,S |
| `communication.provider.ksef` | base.group_system | R,O,U,S |
| `communication.provider.ksef` | base.group_user | R,O,U,S |
| `communication.provider.ksef.offline` | base.group_user | R,O,U,S |

## Reguły rekordów (security.xml)

### Grupa: XML Export Administrator

	<record id="group_xml_export_admin" model="res.groups">
		<field name="name">XML Export Administrator</field>
		<field name="category_id" ref="base.module_category_tools"/>
	</record>

## Reguła: Publiczny odczyt dostawców komunikacji
	<record id="rule_communication_provider_read" model="ir.rule">
		<field name="name">communication.provider public read</field>
		<field name="model_id" ref="model_communication_provider"/>
		<field name="groups" eval="[(4, ref('base.group_user'))]"/>
		<field name="domain_force">[(1, '=', 1)]</field>
		<field name="perm_read" eval="True"/>
		<field name="perm_write" eval="False"/>
		<field name="perm_create" eval="False"/>
		<field name="perm_unlink" eval="False"/>
	</record>

Cel: Pozwala wszystkim użytkownikom na odczyt dostawców komunikacji (tylko do odczytu).

## Status wsparcia multi-company

Aktualny status: ⚠️ WYMAGA IMPLEMENTACJI

### Wymagane zmiany dla kompatybilności z multi-company

#### 1. Modele wymagające pola company_id:
- xml.template.exporter
- xml.export.template
- xml.export.node
- xml.export.namespace
- communication.log
- xml.validation.log

#### 2. Wymagane reguły rekordów dla multi-company:
	<!-- Przykładowa reguła dla szablonu eksportu XML -->
	<record id="rule_xml_template_exporter_company" model="ir.rule">
		<field name="name">XML Template Exporter: Wielofirmowy</field>
		<field name="model_id" ref="model_xml_template_exporter"/>
		<field name="global" eval="True"/>
		<field name="domain_force">
			['|', ('company_id', '=', False), ('company_id', '=', user.company_id.id)]
		</field>
		<field name="groups" eval="[(4, ref('base.group_multi_company'))]"/>
	</record>

#### 3. Wymagane aktualizacje modeli:
	class XmlTemplateExporter(models.Model):
		_name = 'xml.template.exporter'
		_check_company_auto = True  # Dodać tę linię
		
		company_id = fields.Many2one(
			'res.company', 
			string='Firma',
			required=True,
			default=lambda self: self.env.company
		)


## Dobre praktyki bezpieczeństwa

### Dla programistów:
- Używaj sudo() ostrożnie - omija reguły bezpieczeństwa
- Dodaj company_id do wszystkich modeli biznesowych które powinny być przypisane do firmy
- Używaj _check_company_auto = True w modelach z polem company_id
- Testuj z wieloma firmami przed wdrożeniem

### Dla administratorów systemu:
- Przypisz użytkowników do odpowiednich firm w ustawieniach użytkownika
- Używaj grupy XML Export Administrator tylko dla zaufanych użytkowników
- Monitoruj xml.validation.log pod kątem błędów eksportu
- Okresowo przeglądaj dostęp do dostawców komunikacji

## Testowanie bezpieczeństwa

### Test dostępu użytkownika:
	# Test jako zwykły użytkownik
	sudo -u odoo python3 -c "
	from odoo import api, SUPERUSER_ID
	env = api.Environment(cr, SUPERUSER_ID, {})
	user = env.ref('base.user_demo')
	# Tutaj test dostępu"

### Test izolacji między firmami:
	def test_izolacji_firm(self):
		"""Test czy użytkownicy widzą tylko dane swojej firmy"""
		# Utwórz dwie firmy
		firma_a = self.env['res.company'].create({'name': 'Firma A'})
		firma_b = self.env['res.company'].create({'name': 'Firma B'})
		
		# Utwórz użytkownika w Firmie A
		uzytkownik_a = self.stworz_uzytkownika_z_firma(firma_a)
		
		# Utwórz rekord w Firmie A
		rekord = self.env['xml.template.exporter'].sudo(uzytkownik_a).create({
			'name': 'Test',
			'company_id': firma_a.id
		})
		
		# Użytkownik z Firmy B nie powinien widzieć tego rekordu
		uzytkownik_b = self.stworz_uzytkownika_z_firma(firma_b)
		rekordy = self.env['xml.template.exporter'].sudo(uzytkownik_b).search([])
		assert rekord not in rekordy

## Kompatybilność wersji
- **Odoo 18:** W pełni kompatybilny z opisanym modelem bezpieczeństwa
- **Multi-Company:** Wymaga dodatkowej implementacji (patrz uwagi powyżej)

## Dzienniki zmian
| Data | Wersja | Zmiany |
|------|--------|--------|
| 2026-03-31 | 1.0 | Początkowa dokumentacja bezpieczeństwa |
| - | - | Planowane wsparcie multi-company |

## Powiązana dokumentacja
- [Dokumentacja bezpieczeństwa Odoo](https://www.odoo.com/documentation/18.0/developer/reference/backend/security.html)
- [Przewodnik multi-company](https://www.odoo.com/documentation/18.0/developer/tutorials/multi_company.html)
- [Dobre praktyki praw dostępu](https://www.odoo.com/documentation/18.0/developer/reference/backend/security/acl.html)

## Szybkie komendy dla administratora

### Sprawdź grupy użytkownika:
	SELECT login, name FROM res_users WHERE id = [ID_UZYTKOWNIKA];

### Wyświetl wszystkie prawa dostępu:
	SELECT * FROM ir_model_access WHERE model_id IN (
		SELECT id FROM ir_model WHERE model IN (
			'xml.template.exporter',
			'xml.export.template'
		)
	);

### Dodaj użytkownika do grupy admin:

	<record id="user_admin_group" model="res.users">
	    <field name="groups_id" eval="[(4, ref('hfb_xmlmap_exporter.group_xml_export_admin'))]"/>
	</record>

Ten plik zawiera wszystkie informacje w jednym, zwartym dokumencie, w języku polskim, z zachowaniem przejrzystej struktury i praktycznych przykładów.	




#!/usr/bin/env python3
"""
	Narzędzie do weryfikacji wymagań modułu Provider/KSeF Odoo przed instalacją.

	@version 1.0
	@owner  Hadron for Business Sp. z o.o.
	@author Andrzej Wiśniewski (warp3r)
	@date   2026-03-07
"""
import os
import sys
import subprocess
import platform
import re
from pathlib import Path
import json
import argparse
from typing import Dict, List, Tuple, Set, Optional

class OdooModuleChecker:
	def __init__(self, module_path: str, mode: str = 'host', ignore_modules: Set[str] = None):
		"""
		Inicjalizacja checker-a
		
		:param module_path: Ścieżka do katalogu modułu Odoo
		:param mode: Tryb instalacji ('host' lub 'odoo.sh')
		:param ignore_modules: Zbiór modułów do pominięcia
		"""
		self.module_path = Path(module_path)
		self.mode = mode
		self.ignore_modules = ignore_modules or set()
		
		# Dodaj domyślne lokalne moduły
		self.ignore_modules.update({
			'communication_provider_ksef_apiservice',
			# Możesz dodać więcej domyślnych modułów
		})
		
		self.results = {
			'status': 'pending',
			'checks': [],
			'summary': {
				'total': 0,
				'passed': 0,
				'failed': 0,
				'warnings': 0
			},
			'suggestions': []
		}
		
	def run_check(self, check_name: str, check_func, required: bool = True) -> Dict:
		"""Uruchom pojedyncze sprawdzenie"""
		print(f"🔍 Sprawdzanie: {check_name}...", end=' ', flush=True)
		
		try:
			result = check_func()
			status = 'passed' if result['success'] else ('warning' if not required else 'failed')
			
			check_result = {
				'name': check_name,
				'status': status,
				'message': result.get('message', ''),
				'details': result.get('details', {}),
				'required': required
			}
			
			if status == 'passed':
				print("✅")
				self.results['summary']['passed'] += 1
			elif status == 'warning':
				print("⚠️")
				self.results['summary']['warnings'] += 1
			else:
				print("❌")
				self.results['summary']['failed'] += 1
				
			self.results['summary']['total'] += 1
			self.results['checks'].append(check_result)
			
			if not result['success'] and not required:
				self.results['suggestions'].append(result.get('suggestion', ''))
				
			return check_result
			
		except Exception as e:
			print("💥 BŁĄD!")
			error_result = {
				'name': check_name,
				'status': 'error',
				'message': f'Błąd podczas sprawdzania: {str(e)}',
				'details': {},
				'required': required
			}
			self.results['checks'].append(error_result)
			self.results['summary']['failed'] += 1
			self.results['summary']['total'] += 1
			return error_result
	
	def check_system(self) -> Dict:
		"""Sprawdzenie podstawowych informacji o systemie"""
		system = platform.system()
		release = platform.release()
		machine = platform.machine()
		
		# Sprawdzenie czy to Debian/Ubuntu
		is_debian_family = False
		os_name = "Nieznany"
		
		if system == 'Linux':
			try:
				with open('/etc/os-release', 'r') as f:
					os_info = {}
					for line in f:
						if '=' in line:
							key, value = line.strip().split('=', 1)
							os_info[key] = value.strip('"')
					os_name = f"{os_info.get('NAME', '')} {os_info.get('VERSION', '')}"
					is_debian_family = 'debian' in os_info.get('ID', '').lower() or \
									  'ubuntu' in os_info.get('ID', '').lower()
			except:
				pass
		
		success = True
		message = "System zgodny"
		
		if self.mode == 'host' and not is_debian_family:
			success = False
			message = "System nie jest Debian/Ubuntu - instalacja może być utrudniona"
		
		return {
			'success': success,
			'message': message,
			'details': {
				'system': system,
				'os_name': os_name,
				'release': release,
				'machine': machine,
				'is_debian_family': is_debian_family
			},
			'suggestion': "Rozważ użycie Debiana lub Ubuntu dla lepszej kompatybilności" if not success else ""
		}

	def check_hardware(self) -> Dict:
		"""Sprawdzenie zasobów sprzętowych"""
		details = {}
		
		# Sprawdzenie CPU
		cpu_count = os.cpu_count() or 0
		details['cpu_cores'] = cpu_count
		
		# Sprawdzenie RAM
		try:
			if platform.system() == 'Linux':
				with open('/proc/meminfo', 'r') as f:
					for line in f:
						if 'MemTotal' in line:
							mem_kb = int(line.split()[1])
							mem_gb = mem_kb / (1024 * 1024)
							details['ram_gb'] = round(mem_gb, 2)
							break
		except:
			details['ram_gb'] = 0
		
		success = True
		message = "Zasoby sprzętowe wystarczające"
		suggestion = ""

		if self.mode == 'host':
			if details.get('cpu_cores', 0) < 4:
				success = False
				message = "Za mało rdzeni CPU (wymagane minimum 4)"
				suggestion = "Zwiększ liczbę rdzeni CPU"
			elif details.get('ram_gb', 0) < 5:
				success = False
				message = "Za mało RAM (wymagane minimum 6 GB)"
				suggestion = "Zwiększ RAM do minimum 6 GB"
			elif details.get('ram_gb', 0) < 6:
				# To jest warning, nie błąd
				success = True
				message = f"RAM ({details['ram_gb']} GB) poniżej rekomendowanego (zalecane 6+ GB)"
				suggestion = "Rozważ zwiększenie RAM dla lepszej wydajności"
		
		return {
			'success': success,
			'message': message,
			'details': details,
			'suggestion': suggestion
		}
		
	
	def check_java(self) -> Dict:
		"""Sprawdzenie instalacji Java"""
		if self.mode == 'odoo.sh':
			return {
				'success': True,
				'message': 'Java nie jest wymagana w trybie odoo.sh',
				'details': {'java_required': False}
			}
		
		details = {'java_required': True}
		
		try:
			# Sprawdzenie java
			result = subprocess.run(['java', '-version'], 
								  capture_output=True, text=True)
			if result.returncode == 0:
				# Java jest zainstalowana, sprawdź wersję
				version_output = result.stderr or result.stdout
				
				# Wyszukaj wersję
				version_match = re.search(r'version "([^"]+)"', version_output)
				if version_match:
					version_str = version_match.group(1)
					details['java_version'] = version_str
					
					# Sprawdź czy wersja 17+
					major_version = version_str.split('.')[0]
					if major_version.startswith('1.'):
						major_version = major_version[2:]
					
					try:
						if int(major_version) >= 17:
							success = True
							message = f"Java {version_str} - zgodna"
						else:
							success = False
							message = f"Java {version_str} - wymagana wersja 17+"
					except:
						success = False
						message = "Nie można określić wersji Java"
				else:
					success = False
					message = "Java zainstalowana ale nie można określić wersji"
			else:
				success = False
				message = "Java nie jest zainstalowana"
				
		except FileNotFoundError:
			success = False
			message = "Java nie jest zainstalowana"
		
		return {
			'success': success,
			'message': message,
			'details': details,
			'suggestion': "Zainstaluj Java 17: sudo apt install openjdk-17-jdk" if not success else ""
		}
	
	def extract_python_requirements(self) -> Set[str]:
		"""Ekstrakcja wymaganych bibliotek Python z kodu modułu"""
		requirements = set()
		
		# Moduły standardowej biblioteki Pythona (wbudowane)
		stdlib_modules = {
			'warnings', 'base64', 'hashlib', 'tempfile', 'signal', 'uuid', 
			'decimal', 'platform', 'subprocess', 'argparse', 'typing', 
			'dataclasses', 'pathlib', 'io', 'fnmatch', 'os', 'sys', 're',
			'json', 'datetime', 'time', 'math', 'random', 'collections',
			'itertools', 'functools', 'threading', 'multiprocessing', 'socket',
			'http', 'urllib', 'xml', 'csv', 'sqlite3', 'logging', 'glob',
			'shutil', 'pickle', 'struct', 'zipfile', 'tarfile', 'gzip',
			'bz2', 'lzma', 'zlib', 'hashlib', 'hmac', 'secrets', 'token',
			'string', 'unicodedata', 'codecs', 'abc', 'contextlib',
			'copy', 'pprint', 'traceback', 'weakref', 'enum', 'array',
			'queue', 'heapq', 'bisect', 'calendar', 'getpass', 'operator',
			'itertools', 'functools', 'atexit', 'sysconfig', 'platform'
		}
		
		# Importy specyficzne dla Odoo do pominięcia
		odoo_imports = {'odoo', 'odoo.api', 'odoo.models', 'odoo.fields',
						'odoo.exceptions', 'odoo.tools', 'odoo.http',
						'odoo.service', 'odoo.addons'}
		
		# Wzorce do wyszukiwania importów
		import_patterns = [
			r'^import (\w+)',
			r'^from (\w+) import',
			r'^from \.(\w+) import',  # importy względne
			r'^from (\w+)\.',  # import z podmodułu
		]
		
		# Rozszerzenia plików do sprawdzenia
		extensions = ['.py', '.xml', '.csv']
		
		# Katalogi do pominięcia
		exclude_dirs = {'__pycache__', 'tests', 'static', 'demo', 'data'}
		
		print("\n📦 Analizowanie zależności Python w module...")
		
		for root, dirs, files in os.walk(self.module_path):
			# Pomiń wykluczone katalogi
			dirs[:] = [d for d in dirs if d not in exclude_dirs]
			
			for file in files:
				if any(file.endswith(ext) for ext in extensions):
					file_path = os.path.join(root, file)
					try:
						with open(file_path, 'r', encoding='utf-8') as f:
							content = f.read()
							
						# Szukaj importów
						for pattern in import_patterns:
							matches = re.findall(pattern, content, re.MULTILINE)
							for match in matches:
								# Normalizuj nazwę (usuń kropki, weź główny moduł)
								module_name = match.split('.')[0] if '.' in match else match
								
								# Pomijanie importów
								if (module_name in stdlib_modules or  # standard library
									any(module_name.startswith(odoo) for odoo in odoo_imports) or  # Odoo imports
									module_name == '' or  # puste
									module_name.startswith('.') or  # importy względne
									module_name.startswith('_')):  # moduły prywatne
									continue
								
								requirements.add(module_name)
								
					except Exception as e:
						print(f"	⚠️  Błąd czytania {file_path}: {e}")
						continue
		
		return requirements
	
	def is_external_package(self, package_name: str) -> bool:
		"""Sprawdza czy moduł jest zewnętrznym pakietem (nie standardowym i nie własnym)"""
		
		# Moduły standardowej biblioteki Pythona (wbudowane)
		stdlib_modules = {
			'warnings', 'base64', 'hashlib', 'tempfile', 'signal', 'uuid', 
			'decimal', 'platform', 'subprocess', 'argparse', 'typing', 
			'dataclasses', 'pathlib', 'io', 'fnmatch', 'os', 'sys', 're',
			'json', 'datetime', 'time', 'math', 'random', 'collections',
			'itertools', 'functools', 'threading', 'multiprocessing', 'socket',
			'http', 'urllib', 'xml', 'csv', 'sqlite3', 'logging', 'glob',
			'shutil', 'pickle', 'struct', 'zipfile', 'tarfile', 'gzip',
			'bz2', 'lzma', 'zlib', 'hashlib', 'hmac', 'secrets', 'token',
			'string', 'unicodedata', 'codecs', 'abc', 'contextlib',
			'copy', 'pprint', 'traceback', 'weakref', 'enum', 'array',
			'queue', 'heapq', 'bisect', 'calendar', 'getpass', 'operator',
			'itertools', 'functools', 'atexit', 'sysconfig', 'platform'
		}
		
		if package_name in stdlib_modules:
			return False
		
		# Moduły własne projektu (dodaj wszystkie lokalne moduły które nie są pakietami PyPI)
		local_modules = {
			'communication_provider_ksef_apiservice',  # Twój lokalny moduł
			# Możesz dodać więcej lokalnych modułów tutaj
			# np. 'my_custom_library', 'internal_api', itp.
		}
		
		if package_name in local_modules:
			print(f"	ℹ️  Moduł {package_name} - pominięto (lokalny moduł własny)")
			return False
		
		# Sprawdź czy to moduł własny projektu (istnieje w ścieżce modułu)
		# Sprawdź jako plik .py
		module_file = self.module_path / f"{package_name}.py"
		# Sprawdź jako podkatalog
		module_dir = self.module_path / package_name
		
		if module_file.exists() or (module_dir.exists() and module_dir.is_dir()):
			print(f"	ℹ️  Moduł {package_name} - pominięto (znaleziony w strukturze modułu)")
			return False
		
		# Sprawdź czy to może być moduł z innego katalogu addons (współdzielony)
		# Możesz dodać ścieżki do innych katalogów addons jeśli potrzebujesz
		addons_paths = [
			'/usr/lib/python3/dist-packages/odoo/addons',
			'/opt/odoo/addons',
			# Dodaj inne ścieżki jeśli potrzebujesz
		]
		
		for addons_path in addons_paths:
			if os.path.exists(addons_path):
				module_in_addons = os.path.join(addons_path, package_name)
				if os.path.exists(module_in_addons):
					print(f"	ℹ️  Moduł {package_name} - pominięto (moduł Odoo w {addons_path})")
					return False
		
		return True

	def is_odoo_module(self, module_name: str) -> bool:
		"""Sprawdza czy nazwa odpowiada innemu modułowi Odoo"""
		# Możesz dodać listę znanych modułów lub sprawdzać w ścieżkach addons
		# To jest uproszczona wersja
		known_odoo_modules = {
			'account', 'sale', 'purchase', 'stock', 'crm', 'project',
			'hr', 'mail', 'web', 'website', 'point_of_sale', 'pos',
			# Dodaj tutaj swoje moduły
		}
		return module_name in known_odoo_modules


	def generate_requirements_file(self, output_path: str = None) -> str:
		"""Generuje plik requirements.txt z zewnętrznymi zależnościami"""
		all_requirements = self.extract_python_requirements()
		external_requirements = [req for req in all_requirements 
								if self.is_external_package(req)]
		
		if not external_requirements:
			return "# Brak zewnętrznych zależności"
		
		requirements_text = "# Automatycznie wygenerowane zależności dla modułu Odoo\n"
		requirements_text += "# Zainstaluj za pomocą: pip install -r requirements.txt\n\n"
		
		for req in sorted(external_requirements):
			requirements_text += f"{req}\n"
		
		if output_path:
			with open(output_path, 'w') as f:
				f.write(requirements_text)
			print(f"✅ Plik requirements.txt wygenerowano: {output_path}")
		
		return requirements_text

	def check_python_packages(self) -> Dict:
		"""Sprawdzenie zainstalowanych pakietów Python"""
		all_requirements = self.extract_python_requirements()
		
		# Filtruj tylko zewnętrzne pakiety
		external_requirements = {req for req in all_requirements 
								if self.is_external_package(req)}
		
		if not external_requirements:
			return {
				'success': True,
				'message': 'Nie znaleziono zewnętrznych zależności Python',
				'details': {
					'packages_found': [],
					'packages_missing': [],
					'external_packages': [],
					'skipped_stdlib': len(all_requirements) - len(external_requirements)
				}
			}
		
		details = {
			'packages_found': [],
			'packages_missing': [],
			'all_packages': list(external_requirements),
			'skipped_packages': list(all_requirements - external_requirements)
		}
		
		print(f"\n	Znaleziono {len(external_requirements)} zewnętrznych zależności")
		if details['skipped_packages']:
			print(f"	Pominięto {len(details['skipped_packages'])} modułów standardowych/własnych")
		
		try:
			# Pobierz listę zainstalowanych pakietów
			result = subprocess.run([sys.executable, '-m', 'pip', 'list', '--format=json'],
								  capture_output=True, text=True)
			
			if result.returncode == 0:
				installed = {pkg['name'].lower() for pkg in json.loads(result.stdout)}
				
				for req in external_requirements:
					if req.lower() in installed:
						details['packages_found'].append(req)
					else:
						details['packages_missing'].append(req)
			else:
				# Fallback do starego formatu
				result = subprocess.run([sys.executable, '-m', 'pip', 'freeze'],
									  capture_output=True, text=True)
				installed = {line.split('==')[0].lower() 
							for line in result.stdout.split('\n') if '==' in line}
				
				for req in external_requirements:
					if req.lower() in installed:
						details['packages_found'].append(req)
					else:
						details['packages_missing'].append(req)
						
		except Exception as e:
			return {
				'success': False,
				'message': f'Błąd podczas sprawdzania pakietów: {str(e)}',
				'details': details
			}
		
		success = len(details['packages_missing']) == 0
		message = f"Znaleziono {len(details['packages_found'])}/{len(external_requirements)} wymaganych pakietów"
		
		suggestion = ""
		if details['packages_missing']:
			suggestion = f"Zainstaluj brakujące pakiety: pip install {' '.join(details['packages_missing'])}"
		
		return {
			'success': success,
			'message': message,
			'details': details,
			'suggestion': suggestion
		}
	
	def check_system_libraries(self) -> Dict:
		"""Sprawdzenie bibliotek systemowych"""
		# Typowe biblioteki wymagane przez moduły Odoo
		common_libraries = {
			'libpq-dev': 'PostgreSQL client',
			'python3-dev': 'Python headers',
			'build-essential': 'Build tools',
			'libjpeg-dev': 'JPEG support',
			'libpng-dev': 'PNG support',
			'libxml2-dev': 'XML support',
			'libxslt1-dev': 'XSLT support',
			'zlib1g-dev': 'Compression',
			'libsasl2-dev': 'SASL authentication',
			'libldap2-dev': 'LDAP support',
			'libssl-dev': 'SSL support',
		}
		
		if self.mode == 'odoo.sh':
			return {
				'success': True,
				'message': 'Biblioteki systemowe zarządzane przez odoo.sh',
				'details': {'managed_by_odoo_sh': True}
			}
		
		details = {
			'libraries_checked': [],
			'libraries_installed': [],
			'libraries_missing': []
		}
		
		for lib, description in common_libraries.items():
			details['libraries_checked'].append({
				'name': lib,
				'description': description
			})
			
			# Sprawdź czy biblioteka jest zainstalowana
			try:
				result = subprocess.run(['dpkg', '-l', lib], 
									  capture_output=True, text=True)
				if result.returncode == 0 and 'ii' in result.stdout:
					details['libraries_installed'].append(lib)
				else:
					details['libraries_missing'].append(lib)
			except:
				details['libraries_missing'].append(lib)
		
		success = len(details['libraries_missing']) == 0
		message = f"Znaleziono {len(details['libraries_installed'])}/{len(details['libraries_checked'])} bibliotek"
		
		suggestion = ""
		if details['libraries_missing']:
			suggestion = f"Zainstaluj brakujące biblioteki: sudo apt update && sudo apt install {' '.join(details['libraries_missing'])}"
		
		return {
			'success': success,
			'message': message,
			'details': details,
			'suggestion': suggestion
		}
	
	def check_module_structure(self) -> Dict:
		"""Sprawdzenie struktury modułu Odoo"""
		required_files = ['__manifest__.py', '__init__.py']
		optional_files = ['models/__init__.py', 'views/__init__.py', 
						 'security/__init__.py', 'data/__init__.py']
		
		details = {
			'required_files': {},
			'optional_files': {},
			'has_java_client': False
		}
		
		# Sprawdź wymagane pliki
		for file in required_files:
			exists = (self.module_path / file).exists()
			details['required_files'][file] = exists
		
		# Sprawdź opcjonalne pliki
		for file in optional_files:
			exists = (self.module_path / file).exists()
			details['optional_files'][file] = exists
		
		# Sprawdź czy jest klient Java (np. katalog java/, jar, itp.)
		java_indicators = [
			self.module_path / 'java',
			self.module_path / 'lib' / 'java',
			self.module_path / 'static' / 'lib' / 'java',
		]
		
		for path in java_indicators:
			if path.exists() and path.is_dir():
				details['has_java_client'] = True
				break
		
		# Sprawdź czy są pliki .jar
		if not details['has_java_client']:
			for ext in ['*.jar', '*.java']:
				if list(self.module_path.rglob(ext)):
					details['has_java_client'] = True
					break
		
		all_required_ok = all(details['required_files'].values())
		
		message = "Struktura modułu poprawna" if all_required_ok else "Brak wymaganych plików modułu"
		
		return {
			'success': all_required_ok,
			'message': message,
			'details': details
		}
	
	def generate_report(self) -> Dict:
		"""Generowanie raportu końcowego"""
		# Określenie ogólnego statusu
		if self.results['summary']['failed'] == 0:
			if self.results['summary']['warnings'] == 0:
				self.results['status'] = 'ready'
				self.results['final_message'] = '✅ System gotowy do instalacji!'
			else:
				self.results['status'] = 'ready_with_warnings'
				self.results['final_message'] = '⚠️ System gotowy do instalacji ale z ostrzeżeniami'
		else:
			self.results['status'] = 'not_ready'
			self.results['final_message'] = '❌ System NIE jest gotowy do instalacji'
		
		# Dodaj podsumowanie trybu instalacji
		self.results['installation_mode'] = self.mode
		self.results['module_path'] = str(self.module_path)
		
		return self.results
	
	def print_report(self):
		"""Drukowanie raportu w czytelnej formie"""
		print("\n" + "="*60)
		print(f"📋 RAPORT WERYFIKACJI MODUŁU ODOO")
		print("="*60)
		print(f"Moduł: {self.module_path}")
		print(f"Tryb instalacji: {self.mode}")
		print(f"Status: {self.results['final_message']}")
		print("-"*60)
		print(f"Podsumowanie:")
		print(f"  ✅ Przeszło: {self.results['summary']['passed']}")
		print(f"  ⚠️  Ostrzeżenia: {self.results['summary']['warnings']}")
		print(f"  ❌ Błędy: {self.results['summary']['failed']}")
		print("-"*60)
		
		if self.results['suggestions']:
			print("\n💡 Sugestie:")
			for suggestion in self.results['suggestions']:
				if suggestion:
					print(f"  • {suggestion}")
		
		print("\n📊 Szczegółowe wyniki:")
		for check in self.results['checks']:
			status_icon = '✅' if check['status'] == 'passed' else '⚠️' if check['status'] == 'warning' else '❌'
			print(f"\n  {status_icon} {check['name']}")
			print(f"	 {check['message']}")
			
			if check['details']:
				print(f"	 Szczegóły: {check['details']}")
	
	def run_all_checks(self):
		"""Uruchom wszystkie sprawdzenia"""
		print(f"\n🔧 Rozpoczynanie weryfikacji dla trybu: {self.mode.upper()}\n")
		
		self.run_check("System operacyjny", self.check_system)
		self.run_check("Zasoby sprzętowe", self.check_hardware)
		self.run_check("Java", self.check_java)
		self.run_check("Struktura modułu", self.check_module_structure)
		self.run_check("Pakiety Python", self.check_python_packages)
		self.run_check("Biblioteki systemowe", self.check_system_libraries)
		
		return self.generate_report()

def main():
	parser = argparse.ArgumentParser(description='Sprawdzanie wymagań modułu Odoo')
	parser.add_argument('module_path', help='Ścieżka do katalogu modułu')
	parser.add_argument('--mode', choices=['host', 'odoo.sh'], default='host',
					   help='Tryb instalacji (domyślnie: host)')
	parser.add_argument('--output', choices=['text', 'json'], default='text',
					   help='Format wyjścia (domyślnie: text)')
	parser.add_argument('--save-report', help='Zapisz raport do pliku')
	parser.add_argument('--generate-requirements', help='Wygeneruj plik requirements.txt', 
					   action='store_true')
	parser.add_argument('--ignore-modules', help='Plik z listą modułów do pominięcia (jeden na linię)')
	parser.add_argument('--ignore', action='append', help='Dodaj moduł do pominięcia (może być użyty wielokrotnie)')
	
	args = parser.parse_args()
	
	# Sprawdź czy ścieżka istnieje
	if not os.path.exists(args.module_path):
		print(f"❌ Błąd: Ścieżka {args.module_path} nie istnieje")
		sys.exit(1)
	
	# Sprawdź czy to moduł Odoo (ma __manifest__.py)
	manifest_path = os.path.join(args.module_path, '__manifest__.py')
	if not os.path.exists(manifest_path):
		print(f"❌ Błąd: {args.module_path} nie jest modułem Odoo (brak __manifest__.py)")
		sys.exit(1)
	
	# Przygotuj listę ignorowanych modułów
	ignore_modules = set()
	if hasattr(args, 'ignore') and args.ignore:
		ignore_modules.update(args.ignore)
	if hasattr(args, 'ignore_modules') and args.ignore_modules and os.path.exists(args.ignore_modules):
		with open(args.ignore_modules, 'r') as f:
			for line in f:
				module = line.strip()
				if module and not module.startswith('#'):
					ignore_modules.add(module)
	
	# Jeśli tylko generujemy requirements, nie trzeba uruchamiać pełnej weryfikacji
	if args.generate_requirements:
		# Utwórz tymczasowy checker tylko do generowania requirements
		temp_checker = OdooModuleChecker(args.module_path, args.mode, ignore_modules)
		req_file = temp_checker.generate_requirements_file(
			os.path.join(args.module_path, 'requirements.txt')
		)
		print("\n" + "="*60)
		print("✅ Wygenerowano plik requirements.txt")
		print("="*60)
		print(req_file)
		sys.exit(0)
	
	# Uruchom pełne sprawdzanie
	checker = OdooModuleChecker(args.module_path, args.mode, ignore_modules)
	results = checker.run_all_checks()
	
	# Wyświetl wyniki
	if args.output == 'text':
		checker.print_report()
	else:
		print(json.dumps(results, indent=2, default=str))
	
	# Zapisz raport jeśli podano
	if args.save_report:
		with open(args.save_report, 'w') as f:
			json.dump(results, f, indent=2, default=str)
		print(f"\n📁 Raport zapisano do: {args.save_report}")
	
	# Kod wyjścia
	if results['status'] == 'ready':
		sys.exit(0)
	elif results['status'] == 'ready_with_warnings':
		sys.exit(1)
	else:
		sys.exit(2)

if __name__ == '__main__':
	main()

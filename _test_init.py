import sys, os, json, traceback
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from core.theme_manager import ThemeManager
from core.crypto import CryptoManager
from core.database import DatabaseManager

app = QApplication(sys.argv)
ThemeManager.instance().init_app(app, 'light')
print('Theme OK')

data_dir = Path.home() / '.local_password_vault'
config_path = data_dir / 'config.json'
db_path = data_dir / 'vault.db'

with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)
salt = bytes.fromhex(config['salt'])
iterations = config.get('iterations', 600000)

print('Creating CryptoManager...')
crypto = CryptoManager('test_password_123', salt, iterations=iterations)
print('Crypto OK')

print('Creating DatabaseManager...')
db = DatabaseManager(str(db_path), crypto)
print('DB OK')

print('Creating MainWindow...')
try:
    from ui.main_window import MainWindow
    window = MainWindow(db, str(config_path))
    print('MainWindow created OK')
except Exception as e:
    traceback.print_exc()
    print(f'MainWindow FAILED: {e}')
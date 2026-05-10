"""
全局常量配置
集中管理项目中的硬编码路径和配置项
"""
from pathlib import Path

# 数据目录（密码保险箱主数据目录）
DATA_DIR = Path.home() / '.local_password_vault'

# 数据库文件路径
VAULT_DB_PATH = DATA_DIR / 'vault.db'
VAULT_URLS_DB_PATH = DATA_DIR / 'vault_urls.db'

# 备份目录
BACKUP_DIR = DATA_DIR / 'backups'

# 配置文件路径
CONFIG_PATH = DATA_DIR / 'config.json'
COMPACT_VIEW_PATH = DATA_DIR / 'compact_view.json'

# 日志文件路径
LOG_PATH = DATA_DIR / 'app.log'

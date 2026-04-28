"""
数据库管理模块
SQLite 连接管理 + 自动加解密透明处理
"""
import os
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta


class DatabaseManager:
    """数据库管理器：处理 SQLite 连接、建表、加密字段透明处理"""
    
    def __init__(self, db_path: str, crypto_manager=None):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径
            crypto_manager: 加密管理器实例（None 则不加密）
        """
        self.db_path = db_path
        self.crypto = crypto_manager
        self.conn = None
        self.cursor = None
        
        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 连接数据库
        self._connect()
        
        # 建表
        self._create_tables()
        
        # 数据库迁移（添加新字段）
        self._migrate_database()
    
    def _connect(self):
        """建立数据库连接"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
    
    def _create_tables(self):
        """创建数据表结构"""
        # 账号主表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL,
                url TEXT,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                tags TEXT DEFAULT '[]',
                remark TEXT,
                ai_remark TEXT,
                security_level TEXT,
                last_password_change TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # AI 分类缓存表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS category_cache (
                app_name_hash TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                hit_count INTEGER DEFAULT 1,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 配置表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # 分类快照表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                item_type TEXT NOT NULL,
                before_state BLOB NOT NULL,
                changes BLOB NOT NULL
            )
        """)
        
        # 审计日志表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                mode TEXT NOT NULL,
                user_query TEXT NOT NULL,
                parsed_action TEXT,
                parsed_params BLOB,
                affected_count INTEGER DEFAULT 0,
                affected_ids BLOB,
                result TEXT,
                error_message TEXT,
                transaction_id TEXT
            )
        """)
        
        # 回收站表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS recycle_bin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                encrypted_data BLOB NOT NULL,
                app_name TEXT,
                username TEXT,
                url TEXT,
                category TEXT,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                restored_at TIMESTAMP,
                is_restored INTEGER DEFAULT 0
            )
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recycle_expires ON recycle_bin(expires_at) WHERE is_restored = 0
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recycle_type ON recycle_bin(item_type, is_restored)
        """)
        
        # 分类排序表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS category_order (
                category TEXT PRIMARY KEY,
                sort_index INTEGER NOT NULL
            )
        """)
        
        self.conn.commit()
    
    def _encrypt_field(self, plaintext: str) -> str:
        """加密字段（如果 crypto_manager 存在）"""
        if self.crypto and plaintext:
            return self.crypto.encrypt_to_string(plaintext)
        return plaintext
    
    def _decrypt_field(self, ciphertext: str) -> str:
        """解密字段（如果 crypto_manager 存在）"""
        if self.crypto and ciphertext:
            try:
                return self.crypto.decrypt_from_string(ciphertext)
            except Exception as e:
                # 解密失败：记录日志后返回原密文（避免崩溃，但UI会显示密文）
                print(f"[DB] Decrypt failed: {type(e).__name__}: {e}")
                return ciphertext
        return ciphertext
    
    def _migrate_database(self):
        """数据库迁移：添加新字段"""
        try:
            # 检查并添加 tags 字段
            self.cursor.execute("PRAGMA table_info(accounts)")
            columns = [row[1] for row in self.cursor.fetchall()]
            
            new_columns = {
                'tags': "ALTER TABLE accounts ADD COLUMN tags TEXT DEFAULT '[]'",
                'ai_remark': "ALTER TABLE accounts ADD COLUMN ai_remark TEXT",
                'security_level': "ALTER TABLE accounts ADD COLUMN security_level TEXT",
                'last_password_change': "ALTER TABLE accounts ADD COLUMN last_password_change TIMESTAMP"
            }
            
            for col_name, sql in new_columns.items():
                if col_name not in columns:
                    try:
                        self.cursor.execute(sql)
                        print(f"[DB] Migrated: added column '{col_name}'")
                    except Exception as e:
                        print(f"[DB] Migration warning for {col_name}: {e}")
            
            self.conn.commit()
            
        except Exception as e:
            print(f"[DB] Migration failed: {e}")
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
    
    # ==================== 账号表操作 ====================
    
    def insert_account(self, account_data: Dict[str, Any]) -> int:
        """
        插入新账号
        
        Args:
            account_data: 账号数据字典（明文）
            
        Returns:
            新账号 ID
        """
        # 加密敏感字段
        encrypted_data = {
            'app_name': self._encrypt_field(account_data.get('app_name', '')),
            'url': self._encrypt_field(account_data.get('url', '')),
            'username': self._encrypt_field(account_data.get('username', '')),
            'password': self._encrypt_field(account_data.get('password', '')),
            'category': account_data.get('category', '其他'),  # 分类不加密
            'tags': account_data.get('tags', '[]'),  # 标签不加密
            'remark': self._encrypt_field(account_data.get('remark', '')),
            'ai_remark': account_data.get('ai_remark', ''),  # AI 备注不加密
            'security_level': account_data.get('security_level', ''),  # 安全等级不加密
        }
        
        self.cursor.execute("""
            INSERT INTO accounts (app_name, url, username, password, category, tags, remark, ai_remark, security_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            encrypted_data['app_name'],
            encrypted_data['url'],
            encrypted_data['username'],
            encrypted_data['password'],
            encrypted_data['category'],
            encrypted_data['tags'],
            encrypted_data['remark'],
            encrypted_data['ai_remark'],
            encrypted_data['security_level']
        ))
        
        self.conn.commit()
        return self.cursor.lastrowid
    
    def update_account(self, account_id: int, account_data: Dict[str, Any]) -> bool:
        """
        更新账号
        
        Args:
            account_id: 账号 ID
            account_data: 更新的数据字典（明文）
            
        Returns:
            是否成功
        """
        # 加密敏感字段
        encrypted_data = {}
        fields = []
        values = []
        
        if 'app_name' in account_data:
            encrypted_data['app_name'] = self._encrypt_field(account_data['app_name'])
            fields.append("app_name = ?")
            values.append(encrypted_data['app_name'])
        
        if 'url' in account_data:
            encrypted_data['url'] = self._encrypt_field(account_data['url'])
            fields.append("url = ?")
            values.append(encrypted_data['url'])
        
        if 'username' in account_data:
            encrypted_data['username'] = self._encrypt_field(account_data['username'])
            fields.append("username = ?")
            values.append(encrypted_data['username'])
        
        if 'password' in account_data:
            encrypted_data['password'] = self._encrypt_field(account_data['password'])
            fields.append("password = ?")
            values.append(encrypted_data['password'])
        
        if 'category' in account_data:
            fields.append("category = ?")
            values.append(account_data['category'])
        
        if 'remark' in account_data:
            encrypted_data['remark'] = self._encrypt_field(account_data['remark'])
            fields.append("remark = ?")
            values.append(encrypted_data['remark'])
        
        if 'ai_remark' in account_data:
            fields.append("ai_remark = ?")
            values.append(account_data['ai_remark'])
        
        if 'security_level' in account_data:
            fields.append("security_level = ?")
            values.append(account_data['security_level'])
        
        if 'tags' in account_data:
            fields.append("tags = ?")
            values.append(account_data['tags'])
        
        if 'last_password_change' in account_data:
            fields.append("last_password_change = ?")
            values.append(account_data['last_password_change'])
        
        if not fields:
            return False
        
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(account_id)
        
        sql = f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?"
        self.cursor.execute(sql, values)
        self.conn.commit()
        
        return self.cursor.rowcount > 0
    
    def delete_account(self, account_id: int) -> bool:
        """
        删除账号
        
        Args:
            account_id: 账号 ID
            
        Returns:
            是否成功
        """
        self.cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def get_account_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取账号
        
        Args:
            account_id: 账号 ID
            
        Returns:
            账号数据字典（明文），不存在返回 None
        """
        self.cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = self.cursor.fetchone()
        
        if not row:
            return None
        
        return self._decrypt_row(dict(row))
    
    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """
        获取所有账号
        
        Returns:
            账号数据列表（明文，按应用名排序）
        """
        self.cursor.execute("SELECT * FROM accounts ORDER BY app_name")
        rows = self.cursor.fetchall()
        
        return [self._decrypt_row(dict(row)) for row in rows]
    
    def get_accounts_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        按分类获取账号
        
        Args:
            category: 分类名称
            
        Returns:
            账号数据列表（明文）
        """
        self.cursor.execute(
            "SELECT * FROM accounts WHERE category = ? ORDER BY app_name",
            (category,)
        )
        rows = self.cursor.fetchall()
        
        return [self._decrypt_row(dict(row)) for row in rows]
    
    def get_categories(self) -> List[str]:
        """
        获取所有账号分类（去重，排除空值）。
        合并数据表中实际使用的分类 + category_order 排序表中记录的空分类，
        确保新建的空分类也能被显示。
        
        Returns:
            分类名称列表
        """
        # 1. 从数据表中读取实际使用的分类
        self.cursor.execute(
            "SELECT DISTINCT category FROM accounts WHERE category IS NOT NULL AND category != ''"
        )
        db_cats = {row['category'] for row in self.cursor.fetchall()}
        
        # 2. 从排序表中读取所有已记录的分类（包含空分类）
        try:
            self.cursor.execute("SELECT category FROM category_order")
            order_cats = {row['category'] for row in self.cursor.fetchall()}
        except Exception:
            order_cats = set()
        
        # 3. 合并、去重、排序
        all_cats = sorted(db_cats | order_cats)
        return all_cats
    
    def get_category_orders(self) -> Dict[str, int]:
        """获取分类自定义排序（category -> sort_index）"""
        try:
            self.cursor.execute("SELECT category, sort_index FROM category_order")
            return {row['category']: row['sort_index'] for row in self.cursor.fetchall()}
        except Exception:
            return {}
    
    def save_category_orders(self, orders: Dict[str, int]):
        """保存分类自定义排序"""
        self.cursor.execute("DELETE FROM category_order")
        for category, sort_index in orders.items():
            self.cursor.execute(
                "INSERT INTO category_order (category, sort_index) VALUES (?, ?)",
                (category, sort_index)
            )
        self.conn.commit()
    
    def add_category_order(self, category_name: str) -> bool:
        """新增分类到排序表（如果不存在），sort_index 设为当前最大值+1"""
        try:
            self.cursor.execute(
                "SELECT sort_index FROM category_order WHERE category = ?",
                (category_name,)
            )
            if self.cursor.fetchone():
                return False  # 已存在
            
            self.cursor.execute("SELECT MAX(sort_index) FROM category_order")
            row = self.cursor.fetchone()
            max_idx = row[0] if row and row[0] is not None else -1
            
            self.cursor.execute(
                "INSERT INTO category_order (category, sort_index) VALUES (?, ?)",
                (category_name, max_idx + 1)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"[DB] add_category_order failed: {e}")
            return False
    
    def rename_category(self, old_name: str, new_name: str) -> int:
        """重命名分类，返回影响的行数"""
        self.cursor.execute(
            "UPDATE accounts SET category = ? WHERE category = ?",
            (new_name, old_name)
        )
        self.conn.commit()
        return self.cursor.rowcount
    
    def rename_category_order(self, old_name: str, new_name: str) -> bool:
        """同步重命名 category_order 表中的分类记录（包括子类前缀）"""
        try:
            # 1. 精确匹配的旧分类
            self.cursor.execute(
                "UPDATE category_order SET category = ? WHERE category = ?",
                (new_name, old_name)
            )
            # 2. 如果是旧分类是一级分类，同步更新所有子类（如 教育>考试应试 → 新教育>考试应试）
            if '>' not in old_name:
                self.cursor.execute(
                    "UPDATE category_order SET category = ? || SUBSTR(category, ?) WHERE category LIKE ?",
                    (new_name, len(old_name) + 1, f"{old_name}>%")
                )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"[DB] rename_category_order failed: {e}")
            return False

    def delete_category(self, category_name: str) -> int:
        """删除分类：
        - 二级分类：精确匹配的条目去掉二级部分（保留一级）
        - 一级分类：该一级及其所有子类下的条目移至'其他'
        同时清理 category_order 表，返回影响的行数
        """
        if '>' in category_name:
            # 删除二级分类：精确匹配，去掉二级部分
            parent = category_name.split('>')[0].strip()
            self.cursor.execute(
                "UPDATE accounts SET category = ? WHERE category = ?",
                (parent, category_name)
            )
        else:
            # 删除一级分类：匹配自身及所有子类
            self.cursor.execute(
                "UPDATE accounts SET category = '其他' WHERE category = ? OR category LIKE ?",
                (category_name, f"{category_name}>%")
            )
        affected = self.cursor.rowcount
        # 同步清理 category_order 表，避免弹窗下拉框显示幽灵类别
        self.cursor.execute(
            "DELETE FROM category_order WHERE category = ?",
            (category_name,)
        )
        self.conn.commit()
        return affected

    def promote_category(self, old_path: str) -> bool:
        """
        将二级分类升级为一级分类
        - 解析 new_name = old_path.split('>')[1]
        - 更新 accounts 表中 category = old_path 的条目为 new_name
        - 更新 category_order 表：删除 old_path 记录，插入 new_name（复用 sort_index）
        """
        try:
            new_name = old_path.split('>', 1)[1].strip()

            # 检查 category_order 中是否已有该名称
            self.cursor.execute("SELECT 1 FROM category_order WHERE category = ?", (new_name,))
            if self.cursor.fetchone():
                return False

            # 更新 accounts 表
            self.cursor.execute(
                "UPDATE accounts SET category = ? WHERE category = ?",
                (new_name, old_path)
            )

            # 获取旧分类的 sort_index
            self.cursor.execute(
                "SELECT sort_index FROM category_order WHERE category = ?",
                (old_path,)
            )
            row = self.cursor.fetchone()
            old_sort_index = row[0] if row else None

            # 删除旧路径记录
            self.cursor.execute(
                "DELETE FROM category_order WHERE category = ?",
                (old_path,)
            )

            # 插入新一级分类记录
            if old_sort_index is not None:
                self.cursor.execute(
                    "INSERT INTO category_order (category, sort_index) VALUES (?, ?)",
                    (new_name, old_sort_index)
                )
            else:
                self.cursor.execute("SELECT MAX(sort_index) FROM category_order")
                row = self.cursor.fetchone()
                max_idx = row[0] if row and row[0] is not None else -1
                self.cursor.execute(
                    "INSERT INTO category_order (category, sort_index) VALUES (?, ?)",
                    (new_name, max_idx + 1)
                )

            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] promote_category failed: {e}")
            return False
    
    def reparent_category(self, old_path: str, new_path: str) -> int:
        """将 old_path 精确匹配的分类条目更新为 new_path，并同步更新 category_order"""
        try:
            self.cursor.execute(
                "UPDATE accounts SET category = ? WHERE category = ?",
                (new_path, old_path)
            )
            updated_rows = self.cursor.rowcount

            self.cursor.execute(
                "SELECT sort_index FROM category_order WHERE category = ?",
                (old_path,)
            )
            row = self.cursor.fetchone()
            old_sort_index = row[0] if row else None

            self.cursor.execute(
                "DELETE FROM category_order WHERE category = ?",
                (old_path,)
            )

            # 如果 new_path 已存在于 category_order 中，保留其现有 sort_index，不覆盖
            self.cursor.execute(
                "SELECT 1 FROM category_order WHERE category = ?",
                (new_path,)
            )
            if not self.cursor.fetchone():
                if old_sort_index is not None:
                    self.cursor.execute(
                        "INSERT INTO category_order (category, sort_index) VALUES (?, ?)",
                        (new_path, old_sort_index)
                    )
                else:
                    self.cursor.execute("SELECT MAX(sort_index) FROM category_order")
                    row = self.cursor.fetchone()
                    max_idx = row[0] if row and row[0] is not None else -1
                    self.cursor.execute(
                        "INSERT INTO category_order (category, sort_index) VALUES (?, ?)",
                        (new_path, max_idx + 1)
                    )

            # 清理 AI 分类缓存，避免缓存返回旧分类路径
            self.cursor.execute("DELETE FROM category_cache")

            self.conn.commit()
            return updated_rows
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] reparent_category failed: {e}")
            return 0
    
    def _decrypt_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """解密一行数据"""
        return {
            'id': row['id'],
            'app_name': self._decrypt_field(row['app_name']),
            'url': self._decrypt_field(row['url']),
            'username': self._decrypt_field(row['username']),
            'password': self._decrypt_field(row['password']),
            'category': row['category'],
            'tags': row.get('tags', '[]'),
            'remark': self._decrypt_field(row['remark']),
            'ai_remark': row.get('ai_remark', ''),
            'security_level': row.get('security_level', ''),
            'last_password_change': row.get('last_password_change'),
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }
    
    # ==================== 分类缓存表操作 ====================
    
    def get_cached_category(self, app_name_hash: str) -> Optional[str]:
        """获取缓存的分类"""
        self.cursor.execute(
            "SELECT category FROM category_cache WHERE app_name_hash = ?",
            (app_name_hash,)
        )
        row = self.cursor.fetchone()
        
        if row:
            # 更新命中次数和时间
            self.cursor.execute(
                """UPDATE category_cache 
                   SET hit_count = hit_count + 1, last_used = CURRENT_TIMESTAMP 
                   WHERE app_name_hash = ?""",
                (app_name_hash,)
            )
            self.conn.commit()
            return row['category']
        
        self.conn.commit()
        return None
    
    def cache_category(self, app_name_hash: str, category: str):
        """缓存分类结果"""
        self.cursor.execute(
            """INSERT OR REPLACE INTO category_cache 
                (app_name_hash, category, hit_count, last_used)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)""",
            (app_name_hash, category)
        )
        self.conn.commit()
    
    # ==================== 配置表操作 ====================
    
    def get_config(self, key: str) -> Optional[str]:
        """获取配置项"""
        self.cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = self.cursor.fetchone()
        return row['value'] if row else None
    
    def set_config(self, key: str, value: str):
        """设置配置项"""
        self.cursor.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value)
        )
        self.conn.commit()
    
    def insert_audit_log(self, mode: str, user_query: str, parsed_action: Optional[str] = None,
                         parsed_params: Optional[Any] = None, affected_count: int = 0,
                         affected_ids: Optional[List[int]] = None, result: Optional[str] = None,
                         error_message: Optional[str] = None, transaction_id: Optional[str] = None) -> int:
        """
        写入审计日志
        
        Args:
            mode: 操作模式（plan / build）
            user_query: 用户原始查询
            parsed_action: 解析后的动作类型
            parsed_params: 解析后的参数（会自动 JSON 序列化为 BLOB）
            affected_count: 影响记录数
            affected_ids: 影响的账号 ID 列表（会自动 JSON 序列化为 BLOB）
            result: 执行结果描述
            error_message: 错误信息
            transaction_id: 事务 ID
            
        Returns:
            新插入记录的 ID
        """
        import json as _json
        parsed_params_blob = _json.dumps(parsed_params, ensure_ascii=False).encode('utf-8') if parsed_params is not None else None
        affected_ids_blob = _json.dumps(affected_ids, ensure_ascii=False).encode('utf-8') if affected_ids is not None else None
        
        self.cursor.execute("""
            INSERT INTO audit_log (mode, user_query, parsed_action, parsed_params, affected_count, affected_ids, result, error_message, transaction_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (mode, user_query, parsed_action, parsed_params_blob, affected_count, affected_ids_blob, result, error_message, transaction_id))
        self.conn.commit()
        return self.cursor.lastrowid
    
    # ==================== 回收站操作 ====================
    
    def soft_delete_account(self, account_id: int, account_data: dict) -> bool:
        """将账号移入回收站（软删除）"""
        try:
            data_json = json.dumps(account_data, ensure_ascii=False, default=str)
            encrypted = self._encrypt_field(data_json)
            
            username = account_data.get('username', '')
            if len(username) > 4:
                if '@' in username:
                    local, domain = username.split('@', 1)
                    if len(local) > 2:
                        username = local[0] + '***' + local[-1] + '@' + domain
                else:
                    username = username[:3] + '****' + username[-3:]
            
            app_name = account_data.get('app_name', '')
            url = account_data.get('url', '')
            category = account_data.get('category', '其他')
            expires_at = datetime.now() + timedelta(days=30)
            
            self.cursor.execute("""
                INSERT INTO recycle_bin (original_id, item_type, encrypted_data, app_name, username, url, category, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (account_id, 'account', encrypted, app_name, username, url, category, expires_at))
            
            self.cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] soft_delete_account error: {e}")
            return False
    
    def soft_delete_url(self, url_id: int, url_data: dict) -> bool:
        """将网址移入回收站（软删除）"""
        try:
            data_json = json.dumps(url_data, ensure_ascii=False, default=str)
            encrypted = self._encrypt_field(data_json)
            
            title = url_data.get('title', '')
            url_str = url_data.get('url', '')
            category = url_data.get('category', '其他')
            expires_at = datetime.now() + timedelta(days=30)
            
            self.cursor.execute("""
                INSERT INTO recycle_bin (original_id, item_type, encrypted_data, app_name, username, url, category, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (url_id, 'url', encrypted, title, '', url_str, category, expires_at))
            
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] soft_delete_url error: {e}")
            return False
    
    def get_recycle_bin_items(self, item_type: str = None, include_expired: bool = False) -> List[Dict]:
        """获取回收站条目列表"""
        try:
            if item_type:
                if include_expired:
                    self.cursor.execute(
                        "SELECT * FROM recycle_bin WHERE item_type = ? AND is_restored = 0 ORDER BY deleted_at DESC",
                        (item_type,)
                    )
                else:
                    self.cursor.execute(
                        "SELECT * FROM recycle_bin WHERE item_type = ? AND is_restored = 0 AND expires_at > datetime('now') ORDER BY deleted_at DESC",
                        (item_type,)
                    )
            else:
                if include_expired:
                    self.cursor.execute(
                        "SELECT * FROM recycle_bin WHERE is_restored = 0 ORDER BY deleted_at DESC"
                    )
                else:
                    self.cursor.execute(
                        "SELECT * FROM recycle_bin WHERE is_restored = 0 AND expires_at > datetime('now') ORDER BY deleted_at DESC"
                    )
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[DB] get_recycle_bin_items error: {e}")
            return []
    
    def restore_account(self, recycle_id: int) -> Optional[Dict]:
        """从回收站恢复账号到 accounts 表（生成新ID）"""
        try:
            self.cursor.execute("SELECT * FROM recycle_bin WHERE id = ?", (recycle_id,))
            row = self.cursor.fetchone()
            if not row:
                return None
            
            encrypted_data = row['encrypted_data']
            if isinstance(encrypted_data, str):
                decrypted_json = self._decrypt_field(encrypted_data)
            else:
                decrypted_json = self._decrypt_field(encrypted_data.decode('utf-8') if isinstance(encrypted_data, bytes) else str(encrypted_data))
            
            account_data = json.loads(decrypted_json)
            account_data.pop('id', None)
            account_data.pop('created_at', None)
            account_data.pop('updated_at', None)
            
            new_id = self.insert_account(account_data)
            
            self.cursor.execute(
                "UPDATE recycle_bin SET is_restored = 1, restored_at = CURRENT_TIMESTAMP WHERE id = ?",
                (recycle_id,)
            )
            self.conn.commit()
            
            account_data['id'] = new_id
            return account_data
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] restore_account error: {e}")
            return None
    
    def restore_url(self, recycle_id: int) -> Optional[Dict]:
        """从回收站恢复网址（返回解密后的数据，由调用方插入urls表）"""
        try:
            self.cursor.execute("SELECT * FROM recycle_bin WHERE id = ?", (recycle_id,))
            row = self.cursor.fetchone()
            if not row:
                return None
            
            encrypted_data = row['encrypted_data']
            if isinstance(encrypted_data, str):
                decrypted_json = self._decrypt_field(encrypted_data)
            else:
                decrypted_json = self._decrypt_field(encrypted_data.decode('utf-8') if isinstance(encrypted_data, bytes) else str(encrypted_data))
            
            url_data = json.loads(decrypted_json)
            url_data.pop('id', None)
            url_data.pop('created_at', None)
            url_data.pop('updated_at', None)
            
            self.cursor.execute(
                "UPDATE recycle_bin SET is_restored = 1, restored_at = CURRENT_TIMESTAMP WHERE id = ?",
                (recycle_id,)
            )
            self.conn.commit()
            
            return url_data
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] restore_url error: {e}")
            return None
    
    def cleanup_expired_recycle_bin(self, days: int = 30) -> int:
        """清理超过保留期的回收站条目，返回清理数量"""
        try:
            self.cursor.execute(
                "DELETE FROM recycle_bin WHERE is_restored = 0 AND expires_at < datetime('now')"
            )
            self.conn.commit()
            return self.cursor.rowcount
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] cleanup_expired_recycle_bin error: {e}")
            return 0
    
    def permanently_delete_recycle_item(self, recycle_id: int) -> bool:
        """永久删除回收站条目"""
        try:
            self.cursor.execute("DELETE FROM recycle_bin WHERE id = ?", (recycle_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            self.conn.rollback()
            print(f"[DB] permanently_delete_recycle_item error: {e}")
            return False
    
    # ==================== 快照表操作 ====================
    
    def insert_snapshot(self, snapshot_id: str, item_type: str, before_state: str, changes: str) -> bool:
        """
        插入分类快照
        
        Args:
            snapshot_id: 快照唯一标识
            item_type: 'account' 或 'url'
            before_state: 变更前状态的JSON字符串
            changes: 变更列表的JSON字符串
            
        Returns:
            是否成功
        """
        encrypted_before = self._encrypt_field(before_state)
        encrypted_changes = self._encrypt_field(changes)
        self.cursor.execute(
            "INSERT INTO snapshots (snapshot_id, item_type, before_state, changes) VALUES (?, ?, ?, ?)",
            (snapshot_id, item_type, encrypted_before, encrypted_changes)
        )
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def get_snapshots(self, item_type: str = None) -> List[Dict[str, Any]]:
        """
        获取快照列表
        
        Args:
            item_type: 过滤指定类型的快照
            
        Returns:
            快照字典列表（已解密）
        """
        if item_type:
            self.cursor.execute(
                "SELECT * FROM snapshots WHERE item_type = ? ORDER BY created_at DESC",
                (item_type,)
            )
        else:
            self.cursor.execute("SELECT * FROM snapshots ORDER BY created_at DESC")
        rows = self.cursor.fetchall()
        
        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'snapshot_id': row['snapshot_id'],
                'created_at': row['created_at'],
                'item_type': row['item_type'],
                'before_state': self._decrypt_field(row['before_state']),
                'changes': self._decrypt_field(row['changes'])
            })
        return result
    
    def delete_snapshot(self, snapshot_id: str) -> bool:
        """
        删除指定快照
        
        Args:
            snapshot_id: 快照唯一标识
            
        Returns:
            是否成功
        """
        self.cursor.execute("DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def cleanup_old_snapshots(self, days: int = 30) -> int:
        """
        清理指定天数前的快照
        
        Args:
            days: 保留天数（默认30天）
            
        Returns:
            删除的快照数量
        """
        days = int(days)
        self.cursor.execute(
            f"DELETE FROM snapshots WHERE created_at < datetime('now', '-{days} days')"
        )
        self.conn.commit()
        return self.cursor.rowcount

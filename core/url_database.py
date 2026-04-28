"""
网址数据库管理模块
独立的 SQLite 数据库（vault_urls.db）
"""
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any


class URLDatabaseManager:
    """网址数据库管理器"""
    
    def __init__(self, db_path: str):
        """
        初始化网址数据库管理器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        
        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 连接数据库
        self._connect()
        
        # 建表
        self._create_tables()
        
        # 自动迁移（添加新列）
        self._ensure_columns()
    
    def _connect(self):
        """建立数据库连接"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
    
    def _create_tables(self):
        """创建数据表结构"""
        # 网址收藏表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                tags TEXT DEFAULT '[]',
                related_account_id INTEGER,
                visit_count INTEGER DEFAULT 0,
                ai_remark TEXT DEFAULT '',
                remark TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 分类统计视图
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS url_categories (
                name TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        
        # 分类排序表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS category_order (
                category TEXT PRIMARY KEY,
                sort_index INTEGER NOT NULL
            )
        """)
        
        # 回收站表（网址库独立回收站）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS url_recycle_bin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_id INTEGER NOT NULL,
                title TEXT,
                url TEXT,
                category TEXT,
                tags TEXT,
                ai_remark TEXT,
                remark TEXT,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_restored INTEGER DEFAULT 0,
                restored_at TIMESTAMP
            )
        """)
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_url_recycle_expires ON url_recycle_bin(expires_at) WHERE is_restored = 0
        """)
        
        self.conn.commit()
    
    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
    
    def _ensure_columns(self):
        """确保 urls 表包含所有必要列（自动迁移）"""
        self.cursor.execute("PRAGMA table_info(urls)")
        columns = {row['name'] for row in self.cursor.fetchall()}
        
        if 'ai_remark' not in columns:
            self.cursor.execute("ALTER TABLE urls ADD COLUMN ai_remark TEXT DEFAULT ''")
        if 'remark' not in columns:
            self.cursor.execute("ALTER TABLE urls ADD COLUMN remark TEXT DEFAULT ''")
        
        self.conn.commit()
    
    # ==================== 网址表操作 ====================
    
    def insert_url(self, url_data: Dict[str, Any]) -> int:
        """
        插入新网址
        
        Args:
            url_data: 网址数据字典
            
        Returns:
            新网址 ID
        """
        self.cursor.execute("""
            INSERT INTO urls (title, url, category, tags, related_account_id, ai_remark, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            url_data.get('title', ''),
            url_data.get('url', ''),
            url_data.get('category', '其他'),
            url_data.get('tags', '[]'),
            url_data.get('related_account_id'),
            url_data.get('ai_remark', ''),
            url_data.get('remark', '')
        ))
        
        self.conn.commit()
        return self.cursor.lastrowid
    
    def update_url(self, url_id: int, url_data: Dict[str, Any]) -> bool:
        """
        更新网址
        
        Args:
            url_id: 网址 ID
            url_data: 更新的数据字典
            
        Returns:
            是否成功
        """
        fields = []
        values = []
        
        if 'title' in url_data:
            fields.append("title = ?")
            values.append(url_data['title'])
        
        if 'url' in url_data:
            fields.append("url = ?")
            values.append(url_data['url'])
        
        if 'category' in url_data:
            fields.append("category = ?")
            values.append(url_data['category'])
        
        if 'tags' in url_data:
            fields.append("tags = ?")
            values.append(url_data['tags'])
        
        if 'related_account_id' in url_data:
            fields.append("related_account_id = ?")
            values.append(url_data['related_account_id'])
        
        if 'visit_count' in url_data:
            fields.append("visit_count = ?")
            values.append(url_data['visit_count'])
        
        if 'ai_remark' in url_data:
            fields.append("ai_remark = ?")
            values.append(url_data['ai_remark'])
        
        if 'remark' in url_data:
            fields.append("remark = ?")
            values.append(url_data['remark'])
        
        if not fields:
            return False
        
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(url_id)
        
        sql = f"UPDATE urls SET {', '.join(fields)} WHERE id = ?"
        self.cursor.execute(sql, values)
        self.conn.commit()
        
        return self.cursor.rowcount > 0
    
    def delete_url(self, url_id: int) -> bool:
        """
        删除网址
        
        Args:
            url_id: 网址 ID
            
        Returns:
            是否成功
        """
        self.cursor.execute("DELETE FROM urls WHERE id = ?", (url_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def soft_delete_url(self, url_id: int, url_data: dict) -> bool:
        """将网址移入回收站（软删除），并删除原记录"""
        try:
            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(days=30)
            self.cursor.execute("""
                INSERT INTO url_recycle_bin (original_id, title, url, category, tags, ai_remark, remark, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                url_id,
                url_data.get('title', ''),
                url_data.get('url', ''),
                url_data.get('category', '其他'),
                url_data.get('tags', '[]'),
                url_data.get('ai_remark', ''),
                url_data.get('remark', ''),
                expires_at
            ))
            self.cursor.execute("DELETE FROM urls WHERE id = ?", (url_id,))
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"[URLDB] soft_delete_url error: {e}")
            return False
    
    def get_recycle_bin_items(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """获取回收站条目列表"""
        try:
            if include_expired:
                self.cursor.execute(
                    "SELECT * FROM url_recycle_bin WHERE is_restored = 0 ORDER BY deleted_at DESC"
                )
            else:
                self.cursor.execute(
                    "SELECT * FROM url_recycle_bin WHERE is_restored = 0 AND expires_at > datetime('now') ORDER BY deleted_at DESC"
                )
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[URLDB] get_recycle_bin_items error: {e}")
            return []
    
    def restore_url(self, recycle_id: int) -> Optional[Dict[str, Any]]:
        """从回收站恢复网址，返回恢复后的数据（含新ID）"""
        try:
            self.cursor.execute("SELECT * FROM url_recycle_bin WHERE id = ?", (recycle_id,))
            row = self.cursor.fetchone()
            if not row:
                return None
            
            url_data = dict(row)
            url_data.pop('id', None)
            url_data.pop('original_id', None)
            url_data.pop('deleted_at', None)
            url_data.pop('expires_at', None)
            url_data.pop('is_restored', None)
            url_data.pop('restored_at', None)
            
            new_id = self.insert_url(url_data)
            
            self.cursor.execute(
                "UPDATE url_recycle_bin SET is_restored = 1, restored_at = CURRENT_TIMESTAMP WHERE id = ?",
                (recycle_id,)
            )
            self.conn.commit()
            
            url_data['id'] = new_id
            return url_data
        except Exception as e:
            self.conn.rollback()
            print(f"[URLDB] restore_url error: {e}")
            return None
    
    def permanently_delete_recycle_item(self, recycle_id: int) -> bool:
        """永久删除回收站条目"""
        try:
            self.cursor.execute("DELETE FROM url_recycle_bin WHERE id = ?", (recycle_id,))
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            self.conn.rollback()
            print(f"[URLDB] permanently_delete_recycle_item error: {e}")
            return False
    
    def cleanup_expired_recycle_bin(self, days: int = 30) -> int:
        """清理超过保留期的回收站条目"""
        try:
            self.cursor.execute(
                "DELETE FROM url_recycle_bin WHERE is_restored = 0 AND expires_at < datetime('now')"
            )
            self.conn.commit()
            return self.cursor.rowcount
        except Exception as e:
            self.conn.rollback()
            print(f"[URLDB] cleanup_expired_recycle_bin error: {e}")
            return 0
    
    def get_url_by_id(self, url_id: int) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取网址
        
        Args:
            url_id: 网址 ID
            
        Returns:
            网址数据字典，不存在返回 None
        """
        self.cursor.execute("SELECT * FROM urls WHERE id = ?", (url_id,))
        row = self.cursor.fetchone()
        
        if not row:
            return None
        
        return dict(row)
    
    def get_all_urls(self) -> List[Dict[str, Any]]:
        """
        获取所有网址
        
        Returns:
            网址数据列表（按添加时间倒序）
        """
        self.cursor.execute("SELECT * FROM urls ORDER BY created_at DESC")
        rows = self.cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def get_urls_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        按分类获取网址
        
        Args:
            category: 分类名称
            
        Returns:
            网址数据列表
        """
        self.cursor.execute(
            "SELECT * FROM urls WHERE category = ? ORDER BY created_at DESC",
            (category,)
        )
        rows = self.cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def search_urls(self, keyword: str) -> List[Dict[str, Any]]:
        """
        搜索网址
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            匹配的网址列表
        """
        keyword = f"%{keyword}%"
        self.cursor.execute(
            """SELECT * FROM urls 
               WHERE title LIKE ? OR url LIKE ? OR tags LIKE ?
               ORDER BY created_at DESC""",
            (keyword, keyword, keyword)
        )
        rows = self.cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def get_urls_by_account(self, account_id: int) -> List[Dict[str, Any]]:
        """
        获取关联到指定账号的网址
        
        Args:
            account_id: 账号 ID
            
        Returns:
            网址数据列表
        """
        self.cursor.execute(
            "SELECT * FROM urls WHERE related_account_id = ? ORDER BY created_at DESC",
            (account_id,)
        )
        rows = self.cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def increment_visit_count(self, url_id: int):
        """
        增加访问次数
        
        Args:
            url_id: 网址 ID
        """
        self.cursor.execute(
            "UPDATE urls SET visit_count = visit_count + 1 WHERE id = ?",
            (url_id,)
        )
        self.conn.commit()
    
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
    
    def get_categories(self) -> List[str]:
        """
        获取所有网址分类（去重，排除空值）。
        合并数据表中实际使用的分类 + category_order 排序表中记录的空分类，
        确保新建的空分类也能被显示。
        
        Returns:
            分类名称列表
        """
        # 1. 从数据表中读取实际使用的分类
        self.cursor.execute(
            "SELECT DISTINCT category FROM urls WHERE category IS NOT NULL AND category != ''"
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
    
    def update_url_field(self, url_id: int, field: str, value: Any) -> bool:
        """
        更新网址单个字段（用于 Repository 层）
        
        Args:
            url_id: 网址 ID
            field: 字段名
            value: 新值
            
        Returns:
            是否成功
        """
        allowed = {'title', 'url', 'category', 'tags', 'related_account_id', 
                   'visit_count', 'ai_remark', 'remark'}
        if field not in allowed:
            raise ValueError(f"不允许修改的字段: {field}")
        
        self.cursor.execute(
            f"UPDATE urls SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (value, url_id)
        )
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def find_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """
        根据 URL 查找网址（用于判重）
        
        Args:
            url: 网址
            
        Returns:
            网址数据字典，不存在返回 None
        """
        self.cursor.execute("SELECT * FROM urls WHERE url = ? LIMIT 1", (url,))
        row = self.cursor.fetchone()
        return dict(row) if row else None
    
    def rename_category(self, old_name: str, new_name: str) -> int:
        self.cursor.execute(
            "UPDATE urls SET category = ? WHERE category = ?",
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
            # 2. 如果是旧分类是一级分类，同步更新所有子类
            if '>' not in old_name:
                self.cursor.execute(
                    "UPDATE category_order SET category = ? || SUBSTR(category, ?) WHERE category LIKE ?",
                    (new_name, len(old_name) + 1, f"{old_name}>%")
                )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"[URLDB] rename_category_order failed: {e}")
            return False

    def delete_category(self, category_name: str) -> int:
        """删除分类：
        - 二级分类：精确匹配的条目去掉二级部分（保留一级）
        - 一级分类：该一级及其所有子类下的条目移至'其他'
        同时清理 category_order 表
        """
        if '>' in category_name:
            # 删除二级分类：精确匹配，去掉二级部分
            parent = category_name.split('>')[0].strip()
            self.cursor.execute(
                "UPDATE urls SET category = ? WHERE category = ?",
                (parent, category_name)
            )
        else:
            # 删除一级分类：匹配自身及所有子类
            self.cursor.execute(
                "UPDATE urls SET category = '其他' WHERE category = ? OR category LIKE ?",
                (category_name, f"{category_name}>%")
            )
        affected = self.cursor.rowcount
        # 同步清理 category_order 表
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
        - 更新 urls 表
        - 更新 category_order 表
        """
        try:
            new_name = old_path.split('>', 1)[1].strip()

            self.cursor.execute("SELECT 1 FROM category_order WHERE category = ?", (new_name,))
            if self.cursor.fetchone():
                return False

            self.cursor.execute(
                "UPDATE urls SET category = ? WHERE category = ?",
                (new_name, old_path)
            )

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
            print(f"[URLDB] promote_category failed: {e}")
            return False

    def reparent_category(self, old_path: str, new_path: str) -> int:
        """将 old_path 精确匹配的分类条目更新为 new_path，并同步更新 category_order"""
        try:
            self.cursor.execute(
                "UPDATE urls SET category = ? WHERE category = ?",
                (new_path, old_path)
            )

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

            self.conn.commit()
            return self.cursor.rowcount
        except Exception as e:
            self.conn.rollback()
            print(f"[URLDB] reparent_category failed: {e}")
            return 0

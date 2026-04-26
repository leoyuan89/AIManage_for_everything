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
        """⚠️ 物理删除网址记录（不进入回收站）。调用方需先通过主数据库的 soft_delete_url 备份到回收站！"""
        return self.delete_url(url_id)
    
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
        获取所有分类
        
        Returns:
            分类名称列表
        """
        self.cursor.execute(
            "SELECT DISTINCT category FROM urls ORDER BY category"
        )
        rows = self.cursor.fetchall()
        
        return [row['category'] for row in rows]
    
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

    def delete_category(self, category_name: str) -> int:
        """删除分类：将该分类下所有条目的 category 设为 '其他'，并清理 category_order 表"""
        self.cursor.execute(
            "UPDATE urls SET category = '其他' WHERE category = ?",
            (category_name,)
        )
        affected = self.cursor.rowcount
        # 同步清理 category_order 表
        self.cursor.execute(
            "DELETE FROM category_order WHERE category = ?",
            (category_name,)
        )
        self.conn.commit()
        return affected

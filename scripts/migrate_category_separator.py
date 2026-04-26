#!/usr/bin/env python3
"""
数据迁移脚本：将旧分类中的 '/' 替换为 '与'。

执行时机：代码升级前，必须先执行。
作用范围：用户数据目录下的生产数据库（vault.db 和 urls.db）。

步骤：
1. 备份数据库（带时间戳后缀）
2. 扫描含 '/' 的分类
3. 替换 '/' 为 '与'
4. 处理 category_order / url_categories 中的重复键（合并去重）
5. 清理 category_cache 表

注意事项：
- 脚本不依赖项目业务代码，仅使用标准库 sqlite3 + shutil。
- 所有操作在事务保护下进行（BEGIN / COMMIT / ROLLBACK）。
"""

import sqlite3
import shutil
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _process_category_order(conn: sqlite3.Connection, table_name: str = "category_order") -> int:
    """
    处理 category_order 表中替换后可能产生的重复主键。

    策略：
    - 若无重复键，直接执行 UPDATE ... REPLACE(...)。
    - 若有重复键（如已有 ``金融与支付`` 和替换后的 ``金融与支付``），
      保留 sort_index 较小的记录，删除另一条，最后重新写入。

    Returns:
        被合并/删除的重复行数。
    """
    try:
        cursor = conn.execute(f"SELECT category, sort_index FROM {table_name}")
        rows = cursor.fetchall()
        if not rows:
            return 0

        # 计算替换后的新值并检测重复
        new_map = {}          # new_category -> (old_category, sort_index)
        duplicates = []       # 被丢弃的旧分类名列表

        for old_cat, sort_idx in rows:
            new_cat = old_cat.replace("/", "与")
            if new_cat in new_map:
                # 保留 sort_index 较小的那条
                if sort_idx < new_map[new_cat][1]:
                    duplicates.append(new_map[new_cat][0])
                    new_map[new_cat] = (old_cat, sort_idx)
                else:
                    duplicates.append(old_cat)
            else:
                new_map[new_cat] = (old_cat, sort_idx)

        if not duplicates:
            # 没有冲突，常规 UPDATE 即可
            conn.execute(
                f"UPDATE {table_name} SET category = REPLACE(category, '/', '与') "
                f"WHERE category LIKE '%/%'"
            )
            return 0

        # 存在冲突：整表重写（category_order 数据量极小，安全且简单）
        conn.execute(f"DELETE FROM {table_name}")
        for new_cat, (_, sort_idx) in new_map.items():
            conn.execute(
                f"INSERT INTO {table_name} (category, sort_index) VALUES (?, ?)",
                (new_cat, sort_idx)
            )
        return len(duplicates)

    except sqlite3.OperationalError:
        # 表不存在（兼容旧版本或异常数据库）
        return 0


def _process_url_categories(conn: sqlite3.Connection) -> int:
    """
    处理 urls.db 中 url_categories 表的重复键。

    逻辑与 _process_category_order 类似，但合并的是 count 字段。

    Returns:
        被合并/删除的重复行数。
    """
    try:
        cursor = conn.execute("SELECT name, count FROM url_categories")
        rows = cursor.fetchall()
        if not rows:
            return 0

        new_map = {}
        duplicates = []

        for old_name, count in rows:
            new_name = old_name.replace("/", "与")
            if new_name in new_map:
                duplicates.append(old_name)
                # 合并计数
                new_map[new_name] = (old_name, new_map[new_name][1] + count)
            else:
                new_map[new_name] = (old_name, count)

        if not duplicates:
            conn.execute(
                "UPDATE url_categories SET name = REPLACE(name, '/', '与') "
                "WHERE name LIKE '%/%'"
            )
            return 0

        conn.execute("DELETE FROM url_categories")
        for new_name, (_, count) in new_map.items():
            conn.execute(
                "INSERT INTO url_categories (name, count) VALUES (?, ?)",
                (new_name, count)
            )
        return len(duplicates)

    except sqlite3.OperationalError:
        return 0


# ---------------------------------------------------------------------------
# 主迁移逻辑
# ---------------------------------------------------------------------------

def migrate() -> None:
    data_dir = Path.home() / ".local_password_vault"

    if not data_dir.exists():
        print(f"数据目录不存在: {data_dir}")
        return

    migrated_dbs = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for db_name in ["vault.db", "urls.db"]:
        db_path = data_dir / db_name
        if not db_path.exists():
            print(f"[{db_name}] 数据库不存在，跳过")
            continue

        # 1. 备份（带时间戳后缀）
        backup_path = db_path.with_suffix(f".db.backup.{timestamp}")
        shutil.copy2(db_path, backup_path)
        print(f"[{db_name}] 已备份至: {backup_path}")

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("BEGIN TRANSACTION")

            # 确定当前数据库的主业务表
            main_table = "accounts" if db_name == "vault.db" else "urls"

            # 2. 扫描并记录变更
            cursor = conn.execute(
                f"SELECT DISTINCT category FROM {main_table} WHERE category LIKE '%/%'"
            )
            old_categories = [row[0] for row in cursor.fetchall()]

            if old_categories:
                print(f"[{db_name}] 发现 {len(old_categories)} 个含 '/' 的分类:")
                for cat in old_categories:
                    print(f"    '{cat}' → '{cat.replace('/', '与')}'")
            else:
                print(f"[{db_name}] 未发现含 '/' 的分类")

            # 3. 替换主业务表中的 '/'
            if old_categories:
                cursor = conn.execute(
                    f"UPDATE {main_table} SET category = REPLACE(category, '/', '与') "
                    f"WHERE category LIKE '%/%'"
                )
                changed_rows = cursor.rowcount
                print(f"[{db_name}] {main_table} 表已替换 {changed_rows} 条记录")

            # 4. 处理辅助表中的重复键（合并去重）
            dup_co = _process_category_order(conn, "category_order")
            if dup_co:
                print(f"[{db_name}] category_order 表合并 {dup_co} 个重复键")

            if db_name == "urls.db":
                dup_uc = _process_url_categories(conn)
                if dup_uc:
                    print(f"[{db_name}] url_categories 表合并 {dup_uc} 个重复键")

            # 5. 清理缓存表（vault.db 才有 category_cache）
            try:
                conn.execute("DELETE FROM category_cache")
                print(f"[{db_name}] 已清理 category_cache")
            except sqlite3.OperationalError:
                print(f"[{db_name}] category_cache 表不存在，跳过清理")

            conn.commit()
            print(f"[{db_name}] 迁移完成")
            migrated_dbs.append(db_name)

        except Exception as e:
            conn.rollback()
            print(f"[{db_name}] 迁移失败，已回滚: {e}")
            raise
        finally:
            conn.close()

    if migrated_dbs:
        print(f"\n成功迁移的数据库: {', '.join(migrated_dbs)}")
    else:
        print("\n没有需要迁移的数据库")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"迁移异常: {e}", file=sys.stderr)
        sys.exit(1)

# 代码审查与问题汇总报告

> 生成日期：2026-05-08
> 审查范围：全项目代码（`ui/`、`services/`、`core/`、`models/`、`ai/`、`main.py`）
> 审查重点：泄露密码检测闪退问题、暗黑主题适配、代码质量与架构债务

---

## 修复记录（2026-05-08 当日完成）

本次审查报告生成后，已按报告逐项进行修复开发，并经过多轮审查和重新分析。以下是已修复问题的汇总：

| 优先级 | 问题 | 文件 | 状态 |
|--------|------|------|------|
| P0 | `vault` 未定义导致闪退 | `ui/widgets/dashboard_widget.py` | ✅ 已修复（改为 `self.vault`） |
| P0 | 泄露检测主线程同步 HTTP 阻塞 + `processEvents()` 重入闪退 | `ui/dialogs/health_check_dialog.py` | ✅ 已修复（改为 `QThread` 子线程） |
| P1 | SQLite 多线程访问无锁保护 | `core/database.py`, `core/url_database.py` | ✅ 已修复（添加 `threading.RLock()`） |
| P1 | `services/url_service.toggle_favorite` 绕过 RLock 直接操作 cursor | `services/url_service.py` | ✅ 已修复（改为调用 `self.db.update_url`） |
| P1 | 密码验证逻辑缺陷（明文等于密文误判） | `main.py` | ✅ 已修复（改为捕获解密异常） |
| P1 | Undo 横幅 / Toast 硬编码颜色 | `ui/main_window.py` | ✅ 已修复（使用 `ThemeColors`） |
| P1 | 锁屏输入框硬编码颜色 | `ui/lock_screen.py` | ✅ 已修复（使用 `ThemeColors` + `QColor` alpha） |
| P1 | AI 按钮硬编码紫色 | `ui/tag_editor_dialog.py` | ✅ 已修复（使用 `accent_blue`） |
| P1 | 密码强度建议文字硬编码颜色 | `ui/account_dialog.py` | ✅ 已修复（使用 `ThemeColors`） |
| P1 | 实时密码强度评估颜色不一致 | `ui/account_dialog.py` | ✅ 已修复（统一使用 `_get_strength_color`） |
| P1 | 密码强度标签硬编码颜色 | `ui/widgets/account_list_item.py` | ✅ 已修复（使用 `ThemeColors`） |
| P1 | 密码强度分布条形图硬编码颜色 | `ui/widgets/dashboard_widget.py` | ✅ 已修复（使用 `ThemeColors`） |
| P1 | 重复密码组 hover / 泄露检测按钮 `white` 硬编码 | `ui/widgets/dashboard_widget.py` | ✅ 已修复（使用 `text_on_dark`） |
| P2 | `Qt.GlobalColor.gray/red` 未适配主题 | `ui/dialogs/health_check_dialog.py` | ✅ 已修复（使用 `QColor(c.text_tertiary)` / `QColor(c.accent_red)`） |
| P2 | 大量裸 `except:` 吞没异常 | 10+ 个文件 | ✅ 已修复（全部改为显式 `except Exception` + 日志记录） |
| P2 | `_test_init.py` 文件句柄未关闭 | `_test_init.py` | ✅ 已修复（使用 `with open`） |
| P2 | `ClipboardManager` timer 线程不安全 | `core/clipboard.py` | ✅ 已修复（添加 `threading.Lock()`） |
| P2 | `debug_output.txt` 生产环境敏感信息泄露 | `ui/account_dialog.py`, `ui/settings_dialog.py` | ✅ 已修复（移除文件写入，保留 `logger.debug`） |
| P2 | `_BreachCheckThread` 全失败时重复触发信号 | `ui/widgets/dashboard_widget.py` | ✅ 已修复（error 后加 `return`） |
| P2 | `_make_weak_item` 不可达代码 | `ui/dialogs/health_check_dialog.py` | ✅ 已修复（删除冗余 `return item`） |
| P2 | `dashboard_widget.py` 潜在 `KeyError` | `ui/widgets/dashboard_widget.py` | ✅ 已修复（添加 `if p in pwd_to_ids` 判断） |

### 遗留问题（未在本次修复，建议后续迭代）

| 优先级 | 问题 | 说明 |
|--------|------|------|
| P3 | `main_window.py` 近 7000 行未拆分 | 超大模块，建议拆分为 `controllers/` 下多个模块 |
| P3 | `database.py` 与 `url_database.py` 重复代码 | 建议提取 `BaseCategoryManager` 抽象基类 |
| P3 | `.local_password_vault` 路径多处硬编码 | 建议集中到 `core/constants.py` |
| P3 | 头像颜色数组仍为 Material 硬编码色 | `account_list_item.py`、`url_list_item.py` 的 15 色数组 |
| P3 | `core/password_strength.py` 返回硬编码颜色 | 需同步收敛到 `ThemeColors` |
| P3 | 测试覆盖不足 | 缺少数据库线程安全、子线程行为等关键测试 |

---

## 目录

1. [🔴 P0 — 泄露密码检测闪退问题](#一-p0--泄露密码检测闪退问题)
2. [🟠 P1 — 暗黑主题适配问题](#二-p1--暗黑主题适配问题)
3. [🟡 P1~P2 — 代码质量与架构债务](#三-p1p2--代码质量与架构债务)
4. [附录：修复优先级速查表](#附录修复优先级速查表)

---

## 一、🔴 P0 — 泄露密码检测闪退问题

### 1.1 `dashboard_widget.py` — `NameError: vault 未定义`（极高概率闪退）

| 项目 | 内容 |
|------|------|
| **文件** | `ui/widgets/dashboard_widget.py` |
| **行号** | 283 |
| **严重等级** | 🔴 P0 — 必然触发 |

**问题代码：**

```python
# _render_health 方法中（第283行）
acc = self.account_service.get_account(bid) if vault == 'accounts' else None
```

**根因分析：**

- `_render_health(self, accounts, c, ww)` 方法中**没有任何名为 `vault` 的变量或参数**。
- 虽然 `_build()` 方法中定义了 `vault = self.vault`，但 `_render_health` 是独立方法，无法访问 `_build` 的局部变量。
- 当仪表盘完成泄露检测并尝试渲染结果时（即用户看到"检测完成"后），会触发 `NameError: name 'vault' is not defined`，直接导致程序崩溃。

**修复方案：**

```python
# 将 vault == 'accounts' 改为 self.vault == 'accounts'
acc = self.account_service.get_account(bid) if self.vault == 'accounts' else None
```

---

### 1.2 `health_check_dialog.py` — 主线程同步 HTTP + `processEvents()` 重入（极高概率闪退）

| 项目 | 内容 |
|------|------|
| **文件** | `ui/dialogs/health_check_dialog.py` |
| **行号** | 564~571 |
| **严重等级** | 🔴 P0 — 用户关闭对话框或快速点击时触发 |

**问题代码：**

```python
def _run_breach_check(self):
    # ...
    for i, pwd in enumerate(pwd_list):
        self.progress.setValue(i + 1)
        result = self.checker.check_breach(pwd)  # ← 同步 HTTP 请求，阻塞主线程
        if result is None:
            network_error = True
        elif result:
            breached_pwds.append(pwd)
        QApplication.processEvents()  # ← 处理事件循环，可能导致重入
```

**根因分析：**

1. **`check_breach()` 在主线程同步执行 HTTP 请求**（每个请求 5~15 秒超时）。如果密码数量多（如 50 个），UI 将卡死数十秒至数分钟。
2. **`QApplication.processEvents()` 允许事件循环处理其他事件**：
   - 用户可能在此期间**再次点击"检测泄露密码"按钮**，导致 `_run_breach_check()` **重入执行**。
   - 用户可能在此期间**关闭对话框**，但循环仍在继续访问 `self.progress`、`self.checker`、`self.tab_breached` 等 UI 对象，导致**访问已销毁的 C++ 对象**，程序闪退。
3. 当前 `check_breach()` 使用 `urllib.request.urlopen()`，没有设置禁用代理的 handler，在某些代理/VPN 环境下可能导致连接挂起，超时后才返回，加剧卡顿。

**修复方案（推荐）：**

参考 `dashboard_widget.py` 中 `_BreachCheckThread` 的实现方式，将泄露检测逻辑移到独立的 `QThread` 子线程中执行：

1. 在 `health_check_dialog.py` 中创建与 `_BreachCheckThread` 类似的子线程类（或复用现有线程类）。
2. 子线程通过信号 (`pyqtSignal`) 向 UI 线程报告进度和结果。
3. 主线程只负责更新进度条和最终展示，不执行任何网络请求。
4. 在对话框关闭时（`closeEvent`）调用线程的 `requestInterruption()` 并 `wait()` 等待线程结束，防止信号发送到已销毁对象。

---

### 1.3 线程生命周期管理不当（中高概率闪退）

| 项目 | 内容 |
|------|------|
| **文件** | `ui/dialogs/health_check_dialog.py`（673~683 行）、`ui/widgets/dashboard_widget.py`（372~376 行） |
| **严重等级** | 🟠 P1 |

**问题描述：**

- `AiRecommendationThread` 和 `_BreachCheckThread` 在启动时，均未处理"旧线程仍在运行"的情况。
- 如果用户在检测过程中**关闭对话框**或**切换仪表盘视图**，但子线程仍在运行，信号会继续发射到已销毁的 Python/C++ 对象。
- PyQt 中向已销毁对象发射信号可能导致**段错误 (Segmentation Fault)** 或**程序闪退**。

**修复方案：**

- 在启动新线程前，先检查旧线程状态并等待结束：
  ```python
  if hasattr(self, '_ai_thread') and self._ai_thread and self._ai_thread.isRunning():
      self._ai_thread.requestInterruption()
      self._ai_thread.wait(3000)
  ```
- 在对话框/组件的 `closeEvent()` 或析构逻辑中，确保所有子线程已结束：
  ```python
  def closeEvent(self, event):
      if hasattr(self, '_ai_thread') and self._ai_thread and self._ai_thread.isRunning():
          self._ai_thread.requestInterruption()
          self._ai_thread.wait(5000)
      event.accept()
  ```

---

### 1.4 `dashboard_widget.py` — 潜在的 `KeyError`

| 项目 | 内容 |
|------|------|
| **文件** | `ui/widgets/dashboard_widget.py` |
| **行号** | 346~355 |
| **严重等级** | 🟡 P2 — 边界条件下触发 |

**问题代码：**

```python
for group in results.get('reused_groups', []):
    if group:
        p = group[0].password or ''
        if p and p not in pwd_list:
            pwd_list.append(p)
            ids = [a.id for a in group]
            pwd_to_ids[p] = ids
        elif p:
            for a in group:
                pwd_to_ids[p].append(a.id)  # ← 如果 p 不在 pwd_to_ids 中会 KeyError
```

**修复方案：**

```python
        elif p:
            if p in pwd_to_ids:
                for a in group:
                    pwd_to_ids[p].append(a.id)
            else:
                pwd_to_ids[p] = [a.id for a in group]
```

---

### 1.5 `dashboard_widget.py` — 不可达代码

| 项目 | 内容 |
|------|------|
| **文件** | `ui/dialogs/health_check_dialog.py` |
| **行号** | 463~478 |
| **严重等级** | 🟢 P3 — 代码异味，不会导致闪退 |

**问题代码：**

```python
def _make_weak_item(self, acc, strength) -> QListWidgetItem:
    try:
        # ...
        return item       # ← 正常返回
    except Exception:
        return QListWidgetItem("加载失败")  # ← 异常返回
    return item           # ← 永远不会执行到
```

**修复方案：** 删除最后一行不可达的 `return item`。

---

## 二、🟠 P1 — 暗黑主题适配问题

> 项目已建立完善的 `ThemeColors` 色板系统（`core/theme_manager.py`），但部分 UI 代码仍使用硬编码颜色，导致在暗黑主题下不协调或不可见。

### 2.1 严重不适配（硬编码颜色，主题切换后明显不协调）

#### 2.1.1 `ui/main_window.py` — 撤销横幅（Undo Banner）

| 行号 | 问题代码 | 问题描述 |
|------|---------|---------|
| 1961 | `color: white;` | 消息文字硬编码白色 |
| 1969 | `background: white; color: #333;` | 撤销按钮硬编码白底深灰字 |
| 1976 | `color: white;` | 关闭按钮硬编码白色 |
| 1981 | `background-color: #333;` | 横幅背景硬编码深灰色 `#333` |

**暗黑主题影响：** `#333` 背景与主题背景色 `#1E1E1E` / `#252525` 几乎融为一体；整套样式完全脱离 `ThemeColors` 管理。

**修复方案：** 使用 `ThemeColors` 中的 `bg_card`、`text_primary`、`text_on_dark` 等属性动态构建样式字符串。

---

#### 2.1.2 `ui/main_window.py` — Toast 提示

| 行号 | 问题代码 | 问题描述 |
|------|---------|---------|
| 5860 | `background-color: rgba(0,0,0,0.78);` | 背景硬编码黑色半透明 |
| 5861 | `color: white;` | 文字硬编码白色 |

**暗黑主题影响：** 黑色半透明背景会与深色界面背景几乎完全融合，导致 Toast 不可见。

**修复方案：** 使用 `c.bg_card` / `c.bg_secondary` 配合透明度，或根据主题动态调整背景色。

---

#### 2.1.3 `ui/lock_screen.py` — 锁屏输入框

| 行号 | 问题代码 | 问题描述 |
|------|---------|---------|
| 89 | `background-color: rgba(255, 255, 255, 0.1);` | 输入框背景硬编码白色半透明 |
| 90 | `border: 1px solid rgba(255, 255, 255, 0.3);` | 边框硬编码白色半透明 |

**暗黑主题影响：** 在暗黑主题下，白色半透明会在深色背景上产生不想要的灰雾效果。

**修复方案：** 使用主题色板中的 `bg_card` 或 `bg_tertiary` 配合透明度。

---

#### 2.1.4 `ui/tag_editor_dialog.py` — AI 智能生成标签按钮

| 行号 | 问题代码 | 问题描述 |
|------|---------|---------|
| 132 | `background-color: #9c27b0;` | 硬编码紫色 |
| 133 | `color: white;` | 硬编码白色文字 |
| 139 | `background-color: #7b1fa2;` | 硬编码 hover 深紫色 |

**暗黑主题影响：** 该按钮使用了完全脱离主题系统的紫色系，在暗黑主题下会格格不入。

**修复方案：** 改用 `accent_blue` 系列或使用主题色板扩展。

---

#### 2.1.5 `ui/account_dialog.py` — 密码强度建议文字

| 行号 | 问题代码 | 问题描述 |
|------|---------|---------|
| 1439 | `color: #E57373;` | 硬编码浅红色 |
| 1442 | `color: #4CAF50;` | 硬编码绿色 |

**暗黑主题影响：** `#E57373` 在浅色主题下对比度不足；应统一使用 `colors.accent_red` / `colors.accent_green`。

---

### 2.2 中等不适配（功能颜色硬编码，在暗黑主题下过亮/过暗）

#### 2.2.1 密码强度标签硬编码色（多处）

| 文件 | 行号 | 问题代码 |
|------|------|---------|
| `ui/widgets/account_list_item.py` | 113~116 | `"弱": "#f44336"`, `"中": "#FF9800"`, `"强": "#4CAF50"`, `"极强": "#2196F3"` |
| `ui/widgets/dashboard_widget.py` | 196 | `cmap = {"弱": "#f44336", "中": "#FF9800", "强": "#4CAF50", "极强": "#2196F3"}` |

**暗黑主题影响：** Material Design 标准色在浅色主题下对比度良好，但在暗黑主题下饱和度过高、过于刺眼。

**修复方案：** 统一收敛到 `ThemeColors` 中的 `accent_red` / `accent_orange` / `accent_green` / `accent_blue`。

---

#### 2.2.2 `ui/widgets/dashboard_widget.py` — 统计卡片

| 行号 | 问题代码 | 问题描述 |
|------|---------|---------|
| 96~99 | `#2196F3`, `#4CAF50`, `#FF9800`, `#9C27B0` | 硬编码卡片背景色 |
| 108 | `color:white;` | 数字文字硬编码白色 |
| 110 | `color:rgba(255,255,255,0.85);` | 标题文字硬编码白色 85% 透明 |

**暗黑主题影响：** 四个统计卡片完全使用硬编码色，且文字固定白色，在暗黑主题下会异常突兀。

**修复方案：** 卡片颜色使用主题色板中的 `accent_blue`、`accent_green`、`accent_orange` 等，文字使用 `text_on_accent` 或 `text_on_dark`。

---

#### 2.2.3 按钮 hover 态硬编码白色（多处）

| 文件 | 行号 | 问题代码 |
|------|------|---------|
| `ui/widgets/dashboard_widget.py` | 228 | `color:white;`（重复密码组展开项 hover） |
| `ui/widgets/dashboard_widget.py` | 251 | `color:white;`（泄露检测按钮） |
| `ui/dialogs/health_check_dialog.py` | 662 | `color: white;`（获取 AI 建议按钮 hover） |

**修复方案：** 统一改为 `colors.text_on_dark` 或 `colors.text_on_accent`。

---

### 2.3 轻级不适配（Qt 全局颜色 / 图标颜色）

#### 2.3.1 `Qt.GlobalColor` 使用不当

| 文件 | 行号 | 问题代码 |
|------|------|---------|
| `ui/dialogs/health_check_dialog.py` | 434, 447, 455, 618 | `Qt.GlobalColor.gray`（空状态提示文字） |
| `ui/dialogs/health_check_dialog.py` | 474, 612 | `Qt.GlobalColor.red`（风险项文字） |

**暗黑主题影响：** `Qt.GlobalColor` 在不同主题下的表现不可控。`gray` 在暗黑主题下可能保持中灰色，导致在深色背景上对比度不足。

**修复方案：** 替换为 `QColor(colors.text_tertiary)` 和 `QColor(colors.accent_red)`。

---

#### 2.3.2 图标头像颜色数组（高饱和度 Material 色）

| 文件 | 行号 | 问题代码 |
|------|------|---------|
| `ui/widgets/account_list_item.py` | 299 | `colors = ['#E57373', '#F06292', ...]`（15 个硬编码 Material 色） |
| `ui/widgets/url_list_item.py` | 232 | `colors = ['#E57373', '#F06292', ...]`（15 个硬编码 Material 色） |

**暗黑主题影响：** 在暗黑主题下色彩饱和度过高，视觉上不协调。

**修复方案：** 为暗黑主题单独配置一套低饱和度的配色，或在 `ThemeColors` 中新增 `icon_palette: list[str]` 字段。

---

#### 2.3.3 `ui/account_dialog.py` — `JustifyLabel` 自定义绘制未显式设置画笔

| 行号 | 问题代码 |
|------|---------|
| 440~481 | `paintEvent` 中创建 `QPainter` 后未显式设置 `painter.setPen()` |

**暗黑主题影响：** 依赖当前 widget 的 palette 前景色。如果父级或全局 palette 被 qt-material 深度修改，文字颜色可能异常。

**修复方案：** 显式设置 `painter.setPen(QColor(colors.text_primary))`。

---

## 三、🟡 P1~P2 — 代码质量与架构债务

### 3.1 🔴 SQLite 多线程访问无锁保护（数据损坏风险）

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `core/database.py` | 46 | `sqlite3.connect(..., check_same_thread=False)` 禁用了线程安全检查，但**没有任何线程锁** |
| `core/url_database.py` | 41 | 同上 |
| `services/account_service.py` | 307 | 直接在外部调用 `self.db.cursor.execute(...)` 和 `self.db.conn.commit()` |
| `services/url_service.py` | 298 | 同上 |
| `ui/lock_screen.py` | 219 | 在 UI 线程直接操作 `self.db.cursor.execute(...)` |

**风险：** AI 后台线程、泄露检测线程、UI 线程可能并发访问数据库，导致数据竞争、损坏或 "database is locked" 错误。

**修复方案：**
- 在 `DatabaseManager` / `URLDatabaseManager` 中添加 `threading.Lock()`
- 所有 `execute` + `commit` 操作使用 `with self._lock:` 保护
- 或移除 `check_same_thread=False`，为每个线程创建独立连接

---

### 3.2 🔴 大量空 `except` / 异常吞没（隐藏真实 Bug）

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `models/account.py` | 34 | `except:` 无任何处理，吞没 JSON 解析错误 |
| `models/url_item.py` | 33 | `except:` 无任何处理 |
| `ai/ollama_client.py` | 34 | `except:` 吞没网络/服务异常 |
| `services/ai_assistant_service.py` | 1428 | 裸 `except:` |
| `services/url_service.py` | 319 | 裸 `except:` |
| `ui/recycle_bin_dialog.py` | 107 | 裸 `except:` |
| `ui/widgets/dashboard_widget.py` | 164, 173, 194, 417 | `except Exception: pass` |

**风险：** 真正的异常被静默吞没，导致故障排查极其困难，且可能在异常后继续执行错误状态。

**修复方案：** 至少使用 `except Exception as e: logger.warning("...: %s", e)`，绝不使用裸 `except:`。

---

### 3.3 🟠 密码验证逻辑缺陷（误判风险）

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `main.py` | 345 | `if decrypted == row['app_name']: raise ValueError(...)` |

**风险：** 若明文恰好等于原始密文（如极短文本且未加密时），会**误判为密码错误**。

**修复方案：** 使用 `CryptoManager.verify_password()` 方法或捕获解密异常来判断密码正确性，而非比较字符串。

---

### 3.4 🟠 资源泄漏

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `_test_init.py` | 16 | `config = json.load(open(config_path, ...))` 文件句柄未关闭 |
| `core/clipboard.py` | 68~71 | `__del__` 中 `self._timer.is_alive()` 后再 `cancel()` 是线程不安全的 |
| `core/logger.py` | — | `TimedRotatingFileHandler` 未在程序退出时显式 `close()` |

**修复方案：**
- `_test_init.py` 使用 `with open(...) as f: config = json.load(f)`
- `ClipboardManager` 使用 `threading.Lock()` 保护 timer 操作，或改用 `QTimer`
- 在应用退出时显式关闭所有日志 handler

---

### 3.5 🟠 潜在敏感信息泄露

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `core/database.py` | 174~176 | `_decrypt_field()` 解密失败时返回**原始密文**到 UI |
| `ui/account_dialog.py` | 39 | 将数据写入硬编码的 `debug_output.txt`，可能包含密码 |
| `ui/settings_dialog.py` | 32 | 同上 |
| `ai/ollama_client.py` | 167~170 | debug 日志可能输出 AI 响应内容，若包含密码会泄露 |

**修复方案：**
- 解密失败返回空字符串或标记 `[解密失败]`，而非原始密文
- 删除生产代码中的 `debug_output.txt` 写入逻辑，改用标准 logging
- AI 日志中对敏感字段进行脱敏处理

---

### 3.6 🟡 硬编码路径与配置

| 文件 | 问题描述 |
|------|---------|
| `main.py`, `ui/main_window.py`, `services/semantic_search_service.py`, `scripts/migrate_category_separator.py`, `_test_init.py` | `.local_password_vault` 在 **12 处**硬编码，未集中到配置模块 |
| `ui/account_dialog.py:39`, `ui/settings_dialog.py:32` | `debug_output.txt` 硬编码为相对路径，会在工作目录创建文件 |

**修复方案：** 在 `core/constants.py` 中统一定义 `DATA_DIR = Path.home() / '.local_password_vault'`。

---

### 3.7 🟡 SQL 拼接风险（低风险但应规范）

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `core/database.py` | 364 | `f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?"` |
| `core/url_database.py` | 220, 501 | 同上 |
| `ui/main_window.py` | 3224, 3227 | `f"UPDATE {table} SET..."` |

**说明：** 当前 `fields` 和 `table` 均为内部构建/有白名单校验，相对安全。但应使用参数化查询处理所有动态部分，或对表名/字段名使用严格白名单校验并记录审计日志。

---

### 3.8 🟡 类型安全与 `None` 引用风险

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `services/semantic_search_service.py` | 411, 423 | `data.get('vectors', {}).items()`，若 `data` 为 `None` 会抛出 `AttributeError` |
| `ui/main_window.py` | 3020, 3062, 3123, 3142, 3172 | 冗长的 `getattr` / `dict.get` 回退链 |
| `core/repositories.py` | 192 | `Account.from_dict(data)` 假设 `data` 是完整字典 |

---

### 3.9 🟡 并发设计问题

| 文件 | 问题描述 |
|------|---------|
| `services/ai_service_manager.py` | 使用 `threading.Lock()` 实现单例，但 `__init__` 中创建了 `QThread` 子线程，Qt 对象应在 QApplication 线程中创建 |
| `core/clipboard.py` | 使用 `threading.Timer` 而非 `QTimer`，在 PyQt 应用中混用原生线程和 Qt 线程模型，可能导致事件循环冲突 |

---

### 3.10 🟡 超大模块（维护困难）

| 文件 | 行数 | 问题 |
|------|------|------|
| `ui/main_window.py` | **6968 行** | 远超合理范围，包含 UI 布局、事件处理、AI 交互、分类管理、导入导出等大量职责 |
| `services/ai_tools.py` | **2192 行** | 工具定义过于集中 |
| `services/ai_assistant_service.py` | **1706 行** | AI 助手逻辑过于庞大 |
| `ai/ollama_client.py` | **1153 行** | 客户端包含过多职责 |

**修复方案：** 按职责拆分（如 `main_window.py` 拆分为 `controllers/` 下的多个模块）。

---

### 3.11 🟡 重复代码

| 文件 | 问题描述 |
|------|---------|
| `core/database.py` vs `core/url_database.py` | 分类排序、重命名、升级等逻辑几乎完全相同（`category_order` 管理、`rename_category_order`、`promote_category`、`reparent_category`、`delete_category`） |
| `ui/account_dialog.py` vs `ui/url_dialog.py` | 大量 UI 布局逻辑重复 |
| `services/account_service.py` vs `services/url_service.py` | 分类管理逻辑重复 |

**修复方案：** 提取 `BaseCategoryManager` 抽象基类，统一分类操作逻辑。

---

### 3.12 🟡 逻辑不一致与细节问题

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `core/crypto.py` | 30 | 注释写 "默认 ITERATIONS=100000"，但实际默认值是 `600000` |
| `main.py` | 286~287, 327 | `crypto = None; db = None` 在 `if/else` 两个分支中重复初始化，逻辑冗余 |
| `services/ai_worker_thread.py` | 298 | 任务失败时不将状态设为 `OFFLINE`，仅记录错误。若 Ollama 服务已崩溃，状态仍显示 `ONLINE` |
| `services/ai_service_manager.py` | — | 单例持有 `AIWorkerThread` 引用，而 `AIWorkerThread` 通过信号连接回 `AIServiceManager`。如果 `shutdown()` 未被调用，可能造成循环引用导致对象无法被 GC |

---

### 3.13 🟢 未使用的导入/变量（部分示例）

| 文件 | 行号 | 问题描述 |
|------|------|---------|
| `main.py` | 270 | `import json` 在函数内部，可以提到文件顶部 |
| `services/export_service.py` | 170 | `import base64` 在函数内部重复导入 |
| `ai/ollama_client.py` | 585 | `import re` 在函数内部重复导入 |

---

## 附录：修复优先级速查表

| 优先级 | 问题 | 涉及文件 | 预计工作量 |
|-------|------|---------|-----------|
| **P0** | 修复 `dashboard_widget.py` 的 `vault` 未定义 | `ui/widgets/dashboard_widget.py` | 1 分钟 |
| **P0** | 将 `health_check_dialog.py` 泄露检测改为子线程 | `ui/dialogs/health_check_dialog.py` | 2~4 小时 |
| **P1** | 为 SQLite 添加线程锁 | `core/database.py`, `core/url_database.py` | 2~3 小时 |
| **P1** | 修复裸 `except` 块 | 全项目（约 10+ 处） | 1~2 小时 |
| **P1** | 修复主窗口 Undo 横幅/Toast 硬编码颜色 | `ui/main_window.py` | 30 分钟 |
| **P1** | 修复密码验证逻辑 | `main.py` | 30 分钟 |
| **P1** | 修复锁屏/标签编辑器等硬编码颜色 | `ui/lock_screen.py`, `ui/tag_editor_dialog.py`, `ui/account_dialog.py` | 1~2 小时 |
| **P1** | 统一密码强度颜色到 ThemeColors | `ui/widgets/account_list_item.py`, `ui/widgets/dashboard_widget.py` | 30 分钟 |
| **P2** | 修复资源泄漏（文件句柄、timer） | `_test_init.py`, `core/clipboard.py` | 30 分钟 |
| **P2** | 移除/保护 debug_output.txt 写入 | `ui/account_dialog.py`, `ui/settings_dialog.py` | 30 分钟 |
| **P2** | 提取硬编码路径到常量模块 | 多处 | 1~2 小时 |
| **P2** | 修复 `Qt.GlobalColor` 使用 | `ui/dialogs/health_check_dialog.py` | 15 分钟 |
| **P3** | 拆分超大模块 | `ui/main_window.py`, `services/ai_tools.py` | 1~2 天 |
| **P3** | 提取重复的分类管理逻辑 | `core/database.py`, `core/url_database.py` | 4~6 小时 |
| **P3** | 清理未使用的导入 | 全项目 | 30 分钟 |

---

## 总结

### 最紧急的修复（立即执行）

1. **`dashboard_widget.py` 第 283 行**：将 `vault == 'accounts'` 改为 `self.vault == 'accounts'` —— 这是一个 **一行代码修复即可解决闪退** 的问题。
2. **`health_check_dialog.py` 的 `_run_breach_check`**：将同步 HTTP 请求改为子线程执行，并在线程关闭时正确清理 —— 这是解决"检测到快结束或结束时闪退"的根因。

### 次优先修复（本周内）

1. 为 SQLite 数据库操作添加线程锁（数据安全）。
2. 全面清理裸 `except` 块（可观测性）。
3. 修复暗黑主题下硬编码颜色导致的视觉问题。

### 长期优化（后续迭代）

1. 拆分超大模块（`main_window.py` 近 7000 行）。
2. 提取重复逻辑（分类管理、数据库操作）。
3. 统一资源管理和生命周期（线程、文件句柄、日志 handler）。

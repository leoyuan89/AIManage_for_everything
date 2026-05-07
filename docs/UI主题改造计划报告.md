# UI 主题改造计划报告

> 日期：2026-05-07
> 分支：branch1
> 状态：调研完成，待执行

---

## 1. 摘要

本项目使用 PyQt6 + qt-material 作为 UI 框架，但目前存在严重的主题适配问题：
- **暗色主题几乎不可用**：切换后界面丑陋，大量区域颜色错乱
- **根因是 200+ 处硬编码的浅色主题颜色值**覆盖了 qt-material 的全局深色样式

本报告详细分析问题、调研替代方案，并制定分阶段改造计划。

---

## 2. 当前 UI 架构分析

### 2.1 主题引擎：qt-material

| 项目 | 详情 |
|------|------|
| 主题引擎 | `qt-material>=2.14`（`requirements.txt` 第6行） |
| 浅色主题 | `light_blue.xml`（qt-material 内置） |
| 深色主题 | `dark_blue.xml`（qt-material 内置） |
| 管理模块 | `core/theme_manager.py`（27行，单函数） |
| 配置持久化 | `%USERPROFILE%\.local_password_vault\config.json` → `"theme"` 字段 |

### 2.2 主题切换流程

```
用户点击"主题设置" → ThemeSettingsDialog(2个RadioButton)
    → 保存 theme 到 config.json
    → 发射 theme_applied 信号
    → MainWindow._apply_theme()
    → apply_theme_to_app(app, 'light'|'dark')
    → qt_material.apply_stylesheet(app, theme='xxx.xml')
```

### 2.3 关键发现：qt-material 实际上未安装

在目标 Conda 环境 `D:\Anaconda\envs\Passwordmanage` 中，`conda activate Passwordmanage` 指向的是 `D:\Python\Python310\python.exe`，**qt-material 未安装**。这意味着：
- 目前的浅色界面全靠内联 `setStyleSheet()` 硬编码样式渲染
- `theme_manager.py` 中的 `apply_stylesheet` 调用因 `ImportError` 被静默吞掉
- 即使未来安装了 qt-material，也存在下文所述的颜色冲突问题

### 2.4 内联样式统计

全局共 **200+ 处** `setStyleSheet()` 调用：

| 文件 | setStyleSheet 调用数 | 主要颜色 |
|------|---------------------|---------|
| `ui/main_window.py` | ~112 | `#f5f5f5`, `#fafafa`, `#333`, `#ddd`, `#1976D2` |
| `ui/account_dialog.py` | ~50 | `white`, `#f5f5f5`, `#2196F3`, `#e3f2fd` |
| `ui/settings_dialog.py` | ~20 | `#f5f5f5`, `#2196F3`, `#666`, `#999` |
| `ui/url_dialog.py` | ~10 | 同上 |
| `main.py` | 2 | `#2196F3`, `#1976D2` |
| 其他 dialog | ~15 | 散落各处 |

---

## 3. 问题诊断

### 3.1 核心问题：硬编码浅色颜色值

整个项目中的颜色值全部是**浅色主题专用**的，按类别如下：

**背景色**（12+ 种）:
```
#f5f5f5  → 顶部栏、底部栏、选择栏、账号列表、分类选择栏
#fafafa  → 左侧面板、右侧AI面板
#f0f0f0  → 拖放区域、库切换按钮(mark checked)
#f9f9f9  → OCR结果预览
#eeeeee  → 分类树hover
white    → 多项背景
#e3f2fd  → AI筛选横幅、分类树选中、全选按钮
#e8f4fd  → Plan模式badge
#fef2ea  → Build模式badge
```

**文字色**（10+ 种）:
```
#1a1a1a, #1d1d1f, #515154 → 深色文字（在深色背景下完全不可见）
#333    → 列表标题
#666, #888, #999, #86868b → 灰色辅助文字
#cccccc → 箭头等装饰元素
#f44336 → 红色警告/错误
#2196F3, #1976D2, #1565C0, #90CAF9 → 蓝色系
#4CAF50, #45a049 → 绿色
#FF6B35, #E55A2B, #E65100 → 橙色
```

**边框色**（6+ 种）:
```
#ddd, #ccc, #e0e0e0, #e5e5e5, #90CAF9, #90caf9
```

### 3.2 暗色主题失效的机制

```
┌─────────────────────────────────────────────────────────────┐
│  qt-material 全局深色样式表                                   │
│  将 QApplication 所有 widget 的默认颜色改为深色               │
│  （背景→深色, 文字→浅色, 边框→深灰色）                        │
│                         ↓                                    │
│  setStyleSheet() 内联样式（widget级别）                       │
│  background-color: #f5f5f5; ← 覆盖为浅灰色！                  │
│  color: #333;               ← 覆盖为深色文字！                │
│  border: 1px solid #ddd;    ← 覆盖为浅色边框！                │
│                         ↓                                    │
│  结果：全局深色 + 局部浅色 = 灾难                              │
│  例如：左侧面板深灰背景上顶着 #fafafa 的白色块，               │
│        深色背景上显示 #333 黑色文字（几乎看不见）              │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 具体受损区域

切换暗色主题后，以下区域会明显错乱：

1. **顶部工具栏**：`background-color: #f5f5f5` → 在深色主题中呈白色块
2. **库切换按钮**：unchecked 状态 `#f0f0f0` 背景 + `#333` 文字 → 白底黑字突兀
3. **左侧分类面板**：`background-color: #fafafa` → 白色块
4. **分类树**：多套硬编码样式（normal/edit/reorganize 模式），全部浅色
5. **账号列表**：`background-color: #f5f5f5` → 浅灰底色
6. **账号卡片列表项**：hover/selected 状态全部硬编码浅色
7. **右侧AI面板**：`background-color: #fafafa` → 白色块
8. **AI模式按钮**：Plan(蓝)/Build(橙) 在深色背景上饱和度过高
9. **底部状态栏**：`background-color: #f5f5f5` + `color: #666` → 白底灰字
10. **字母导航条**：蓝色文字在深色背景上过于刺眼
11. **所有Dialog**：设置、账号编辑、导入导出等对话框的硬编码浅色背景和文字

### 3.4 次要问题

1. **只有2个主题选项**（浅/深），无中间色调或自定义能力
2. **无动态切换**：切换主题后不会通知子组件更新样式，只靠 qt-material 全局覆盖（但被内联样式阻止）
3. **无主题预览**：用户只能在保存后才能看到效果
4. **素材目录为空**：`assets/` 完全空，无图标/图片资源
5. **AI面板的welcome卡片**（行5244-5340）：使用 iOS 风格颜色（`#1d1d1f`, `#86868b`），与 Material Design 风格不一致

---

## 4. 主题方案调研

### 4.1 qt-material 现状评估

**优点**：
- 提供 20+ 种内置 Material Design 主题（`light_blue`, `dark_blue`, `light_cyan`, `dark_teal` 等）
- 覆盖 Qt 常见控件的全局样式（按钮、输入框、滚动条、菜单等）
- API 简单：`apply_stylesheet(app, theme='xxx.xml')`

**缺点**：
- 对自定义 widget 内联样式无能为力 → 本项目核心痛点
- 主题定制不灵活，需自己写 XML
- 某些控件样式不尽人意（如 QTreeWidget 缩进、QTableWidget 表头）
- 不支持主题变量/动态切换回调

**结论**：qt-material 适合作为**底层基础样式引擎**，处理通用控件的深浅色适配，但不能解决本项目 200+ 处内联样式的兼容问题。

### 4.2 替代方案对比

| 方案 | 描述 | 优点 | 缺点 | 适合本项目？ |
|------|------|------|------|------------|
| **QDarkStyleSheet** | 知名开源 PyQt 深色主题包 | 开箱即用，控件覆盖全 | 只支持深色，无浅色；与 Material 风格不兼容 | ❌ |
| **pyqt-darktheme** | 轻量 PyQt 深色主题 | 简单，文件少 | 同上，只有深色 | ❌ |
| **QPalette 系统** | 利用 Qt 内置 QPalette 机制 | 原生支持，无额外依赖，所有 widget 自动适配 | 表达能力有限，无法做到精美的卡片/圆角/阴影效果 | ❌ |
| **自定义双份 QSS 文件** | 手写 `light.qss` + `dark.qss` 全局样式表 | 完全掌控，效果精准 | 需大量手写，维护成本高 | ❌ |
| **ThemeColors + 动态样式生成** | Python 类定义色板，运行时生成 QSS | 灵活、类型安全、易维护、与现有代码兼容 | 需要改造所有 setStyleSheet 调用点 | ✅ **推荐** |
| **qt-material + ThemeColors 混合** | qt-material 管通用控件 + ThemeColors 管自定义样式 | 结合两者优势 | 需要处理好两者的叠加关系 | ✅ **推荐** |

### 4.3 推荐方案：ThemeColors + qt-material 混合架构

```
┌──────────────────────────────────────────────────────┐
│                 ThemeManager (单例)                   │
│  ┌─────────────────────────────────────────────────┐ │
│  │  ThemeColors (DataClass)                        │ │
│  │  - 背景色: bg_primary, bg_secondary, bg_card... │ │
│  │  - 文字色: text_primary, text_secondary...      │ │
│  │  - 边框色: border_light, border_strong...       │ │
│  │  - 强调色: accent_blue, accent_red, accent_...  │ │
│  │  - light_palette / dark_palette                 │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────┐ │
│  │  qt-material (底层引擎)                          │ │
│  │  - light_blue.xml / dark_blue.xml               │ │
│  │  - 处理 QPushButton, QLineEdit, QScrollBar 等   │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  theme_changed = pyqtSignal(str)  # 'light' | 'dark'  │
│  current_colors: ThemeColors     # 当前色板            │
│                                                       │
│  Methods:                                             │
│    apply_theme(theme_name)      # 切换主题             │
│    generate_stylesheet(widget, preset) # 生成QSS       │
└──────────────────────────────────────────────────────┘
```

**配色方案设计**（Material Design 3 风格）：

| Token | 浅色值 | 深色值 | 用途 |
|-------|--------|--------|------|
| `bg_primary` | `#FFFFFF` | `#1E1E1E` | 主背景 |
| `bg_secondary` | `#F5F5F5` | `#252525` | 次要背景（面板、卡片） |
| `bg_tertiary` | `#EEEEEE` | `#2D2D2D` | 三级背景（hover） |
| `bg_surface` | `#FAFAFA` | `#1A1A1A` | 表面/浮层 |
| `bg_selected` | `#E3F2FD` | `#1A3A5C` | 选中态 |
| `text_primary` | `#1A1A1A` | `#E0E0E0` | 主要文字 |
| `text_secondary` | `#666666` | `#AAAAAA` | 次要文字 |
| `text_tertiary` | `#999999` | `#777777` | 三级文字 |
| `border_default` | `#DDDDDD` | `#3D3D3D` | 默认边框 |
| `border_light` | `#E5E5E5` | `#333333` | 浅色边框 |
| `accent_blue` | `#1976D2` | `#64B5F6` | 蓝色强调 |
| `accent_blue_bg` | `#E3F2FD` | `#1A3A5C` | 蓝色强调背景 |
| `accent_red` | `#F44336` | `#EF5350` | 红色/危险 |
| `accent_green` | `#4CAF50` | `#66BB6A` | 绿色/成功 |
| `accent_orange` | `#FF6B35` | `#FF8A65` | 橙色/炽阳 |
| `accent_orange_bg` | `#FFF3E0` | `#3E2723` | 橙色背景 |

---

## 5. 修改计划

### 阶段 1：基础设施搭建（预计 2-3 小时）

**1.1 安装 qt-material**
```powershell
conda activate Passwordmanage
pip install qt-material>=2.14
```

**1.2 重写 `core/theme_manager.py`**

新建 `ThemeColors` 数据类和增强版 `ThemeManager`：

```python
# core/theme_manager.py (新)
from dataclasses import dataclass
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal

@dataclass
class ThemeColors:
    """主题色板"""
    # 背景
    bg_primary: str       # 主背景
    bg_secondary: str     # 面板/bar 背景
    bg_tertiary: str      # hover/highlight
    bg_surface: str       # 侧边栏/AI面板
    bg_selected: str      # 选中态
    bg_card: str          # 卡片背景
    
    # 文字
    text_primary: str
    text_secondary: str
    text_tertiary: str
    text_on_accent: str   # 强调色上的文字（通常白色）
    
    # 边框
    border_default: str
    border_light: str
    border_focus: str     # 聚焦边框
    
    # 强调色
    accent_blue: str
    accent_blue_bg: str
    accent_red: str
    accent_green: str
    accent_orange: str
    accent_orange_bg: str
    
    # 语义色
    color_success: str
    color_warning: str
    color_error: str

# Light / Dark 预设
LIGHT_COLORS = ThemeColors(...)
DARK_COLORS = ThemeColors(...)

class ThemeManager(QObject):
    theme_changed = pyqtSignal(str, ThemeColors)
    
    _instance = None
    
    @classmethod
    def instance(cls): ...
    
    def apply_theme(self, app, theme_name): ...
    def get_colors(self) -> ThemeColors: ...
    def style(self, widget_type, preset) -> str: ...  # 生成主题感知的QSS
```

**1.3 在 `main.py` 中初始化单例**

确保应用启动时创建全局 `ThemeManager` 实例。

---

### 阶段 2：主窗口适配（预计 4-6 小时）

这是工作量最大的部分。`ui/main_window.py` 中约 112 处 `setStyleSheet()` 需要改造。

**改造策略**：每个硬编码的 QSS 块改为调用 `ThemeManager.instance().style(...)` 动态生成。

**分类处理**：

| 区域 | 行号范围 | 改造项数 | 优先级 |
|------|---------|---------|--------|
| 顶部工具栏 | 1604-1699 | ~8 | P0 |
| 左侧分类面板 | 1705-1908 | ~15 | P0 |
| 中间账号列表 | 1912-1991 | ~12 | P0 |
| 右侧AI面板 | 1996-2270 | ~20 | P0 |
| 底部工具栏 | 2278-2384 | ~12 | P0 |
| 账号列表项组件 | 240-460, 964-1032 | ~20 | P0 |
| 字母导航条 | 2387-2415 | ~2 | P1 |
| 分类树样式 | 1773-1852, 1071-1147 | ~8 | P0 |
| AI模式切换 | 2043-2093, 3691-3711 | ~6 | P1 |
| Welcome卡片 | 5244-5340 | ~10 | P1 |
| 确认对话框内联样式 | ~4393, ~2225-2251 | ~4 | P1 |

**示例改造**：

改造前：
```python
top_bar.setStyleSheet("background-color: #f5f5f5; border-bottom: 1px solid #ddd;")
```

改造后：
```python
top_bar.setStyleSheet(theme.style("top_bar"))
```

其中 `theme.style("top_bar")` 在浅色模式下返回：
```css
background-color: #F5F5F5; border-bottom: 1px solid #DDDDDD;
```
在深色模式下返回：
```css
background-color: #252525; border-bottom: 1px solid #3D3D3D;
```

**2.1 添加主题切换响应**

在 `_apply_theme()` 方法中增加：刷新所有已创建 widget 的样式表。

```python
def _apply_theme(self, theme_name):
    ThemeManager.instance().apply_theme(QApplication.instance(), theme_name)
    self._refresh_all_styles()  # 重新应用所有内联样式
```

---

### 阶段 3：对话框适配（预计 2-3 小时）

| 文件 | setStyleSheet 数 | 改造要点 |
|------|-----------------|---------|
| `ui/account_dialog.py` | ~50 | 背景、按钮、标签、OCR区域 |
| `ui/settings_dialog.py` | ~20 | 按钮列表、说明文字 |
| `ui/url_dialog.py` | ~10 | 与 account_dialog 类似 |
| `ui/import_dialog.py` | ~5 | 背景、表格 |
| `ui/export_dialog.py` | ~3 | 按钮 |
| `ui/lock_screen.py` | ~5 | 输入框、解锁按钮（本身已半透明深色） |
| `main.py` | 2 | 确认/登录按钮 |

这些对话框大部分在创建时会从 `ThemeManager` 获取当前色板，自动适配。无需额外的主题切换监听（对话框是模态的，切换主题时才重新打开）。

---

### 阶段 4：优化与微调（预计 1-2 小时）

1. **视觉一致性检查**：确保所有 widget 在浅/深模式下颜色协调
2. **特殊元素处理**：
   - AI Thinking 区域（QTextBrowser）的 markdown 渲染色
   - QTableWidget 的 grid/highlight 色
   - QTreeWidget 的缩进指示线颜色
3. **Edge cases**：
   - 选中态/悬停态在深色背景下对比度是否足够
   - 红色警告文字在深色背景下是否可读
   - 代码块/JSON 在 AI 回复中的显示
4. **删除无用代码**：AI welcome 卡片中的 iOS 风格颜色（`#1d1d1f` 等）统一为 Material Design 色板

---

## 6. 附加建议

1. **图标系统**：目前 `assets/` 为空，按钮全部用文字（+、炽阳、设置、锁定等）。建议后续引入图标库（如 `qtawesome` 或 Material Design Icons 字体）提升视觉效果。

2. **字体系统**：目前混用系统默认字体和自定义 `QFont`。建议统一为系统 UI 字体（Windows: Segoe UI, macOS: SF Pro, Linux: Noto Sans）。

3. **圆角与阴影**：目前大量使用 `border-radius` 但无阴影。qt-material 提供 shadow 支持，可适当添加提升层次感。

4. **过渡动画**：主题切换是无动画的瞬间切换。可考虑添加短暂的 `QPropertyAnimation` 过渡。

5. **主题选项扩展**：改造完成后，可轻松扩展更多主题色（如 `light_cyan`, `dark_teal` 等 qt-material 内置主题），只需在 `ThemeColors` 中定义对应色板即可。

---

## 7. 风险与注意事项

| 风险 | 缓解措施 |
|------|---------|
| 改造工作量较大（200+处） | 分阶段执行，每阶段完成后测试验证 |
| 改动可能引入新 bug | 保持 git 提交细粒度，每改完一个文件提交一次 |
| 部分 widget 样式可能遗漏 | 改造后做一次完整的 grep 检查残留硬编码颜色 |
| qt-material 与自定义样式冲突 | ThemeColors 色板设计时考虑与 qt-material 色调一致性 |
| 性能影响 | `style()` 方法返回静态字符串，无运行时开销 |

---

## 8. 待确认问题

1. **qt-material 安装情况**：当前环境实际未安装 qt-material，是否需要在此次改造中一并安装？
2. **颜色偏好**：上述建议的 Material Design 3 配色方案是否需要调整？有没有特定的品牌色/偏好色？
3. **主题数量**：是否需要超过 2 个主题（如增加「浅灰」「深蓝」等中间选项）？
4. **图标库**：是否在本次改造中一并引入 qtawesome 或 Material Icons？
5. **是否需要提供截图**：当前 UI 的实际显示效果以便更精确地评估？

---

*本报告将作为后续改造的指导文档，实际执行时可根据进展情况动态调整。*

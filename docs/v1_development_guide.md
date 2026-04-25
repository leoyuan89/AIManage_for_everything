# 本地密码保险箱 - V1 软件开发指导文档

> 文档版本：v1.0
> 编写日期：2026-04-23
> 目标：指导 MVP 1-4 完整开发

---

## 1. 技术架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                         表现层 (UI Layer)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  主窗口       │  │  添加/编辑弹窗 │  │  设置/锁定/导出   │   │
│  │  - 分类导航   │  │  - 手动输入   │  │  - 主密码设置    │   │
│  │  - 账号列表   │  │  - OCR截图   │  │  - 密保问题      │   │
│  │  - 搜索框     │  │  - AI分类    │  │  - 导出Excel    │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                      业务逻辑层 (Service Layer)                │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ AccountSvc │ │ CategorySvc│ │ SearchSvc  │ │ CryptoSvc│ │
│  │ - CRUD     │ │ - AI分类   │ │ - 精确搜索 │ │ - 加密   │ │
│  │ - 排序     │ │ - 缓存管理 │ │ - 语义搜索 │ │ - 解密   │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ OCRService │ │ ExportSvc  │ │ SyncSvc    │ │ LockSvc  │ │
│  │ - Paddle   │ │ - Excel    │ │ - PWA HTML │ │ - 会话   │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────┘ │
├─────────────────────────────────────────────────────────────┤
│                       数据访问层 (DAO Layer)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                 DatabaseManager                        │   │
│  │  - SQLite 连接池                                      │   │
│  │  - 加解密字段透明处理（写入前加密，读取后解密）          │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                        外部服务层                              │
│  ┌─────────────────┐  ┌──────────────────────────────────┐  │
│  │  Ollama Client  │  │         PaddleOCR Engine          │  │
│  │  - HTTP API     │  │  - 截图文字识别                    │  │
│  └─────────────────┘  └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心设计决策

### 2.1 加密方案：应用层加密（方案 A）

**原理**：SQLite 数据库文件本身是明文的，但写入的每个字段（除 id、created_at、updated_at 外）都经过 AES-256-GCM 加密。

**密钥派生**：
```
主密码 + 随机盐(32字节) 
    ↓ PBKDF2-HMAC-SHA256, 100000 次迭代
派生密钥(32字节) 
    ↓ 作为 AES-256-GCM 的密钥
加密/解密数据
```

**存储结构**：
- 盐值存储在独立配置文件 `config.json` 中（明文存储，用于下次派生密钥）
- 密保问题答案也用这个密钥加密后存储
- 密钥文件恢复：生成一个 256-bit 随机密钥，保存为 `.key` 文件，加密主数据库密钥

### 2.2 搜索策略：分层搜索

```
用户输入搜索词
    ↓
第一层：精确匹配（本地 SQLite LIKE 查询）
  - 匹配 app_name、url、username、remark
  - 结果立即展示（零延迟）
    ↓
第二层：语义搜索（调用 Gemma 4 E4B）
  - 仅当精确匹配结果不足时触发
  - Prompt: "用户在找什么账号？从以下列表中匹配..."
  - 返回置信度 > 0.6 的结果
  - 结果展示在精确匹配下方，标注"智能推荐"
```

### 2.3 剪贴板安全机制

```
用户点击"复制密码"
    ↓
密码写入剪贴板
    ↓
启动 20 秒倒计时线程
    ↓
20 秒后检查剪贴板内容
    - 如果仍是该密码 → 清空剪贴板
    - 如果用户已复制其他内容 → 不干预
```

### 2.4 PWA 同步方案

```
用户点击"生成密包"
    ↓
读取所有账号数据
    ↓
用主密码派生的密钥加密 JSON 数据（AES-256-GCM）
    ↓
生成 single-file HTML（内含解密 JS + 加密数据）
    ↓
保存为 vault_YYYYMMDD.html
    ↓
用户手动复制到手机
    ↓
手机浏览器打开 → 输入主密码 → 本地 JS 解密展示
```

### 2.5 UI 主题方案

**采用 qt-material 库实现 Material Design 风格**

```python
from qt_material import apply_stylesheet

# 应用浅色蓝色主题
apply_stylesheet(app, theme='light_blue.xml')
```

**主题选择**：`light_blue.xml`
- 浅色背景，蓝色强调色
- 现代 Material Design 风格
- 与"苹果备忘录 + 1Password 简洁感"的设计理念一致
- 无需手动配置颜色，一套主题统一所有控件样式

**安装**：`pip install qt-material`（已加入 requirements.txt）

---

## 3. 数据库设计

### 3.1 表结构

```sql
-- 账号主表
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name BLOB NOT NULL,        -- AES-256-GCM 加密
    url BLOB,                       -- AES-256-GCM 加密
    username BLOB NOT NULL,        -- AES-256-GCM 加密
    password BLOB NOT NULL,        -- AES-256-GCM 加密
    category TEXT NOT NULL,        -- 明文（AI 分类结果，无需加密）
    remark BLOB,                    -- AES-256-GCM 加密
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI 分类缓存表
CREATE TABLE category_cache (
    app_name_hash TEXT PRIMARY KEY,  -- app_name 的 SHA256 哈希（用于快速查重，不存原文）
    category TEXT NOT NULL,
    hit_count INTEGER DEFAULT 1,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 配置表（存储主密码盐值、密保问题等）
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value BLOB                       -- 敏感值加密，非敏感值明文
);
```

### 3.2 加密字段说明

| 字段 | 加密方式 | 说明 |
|------|---------|------|
| app_name, url, username, password, remark | AES-256-GCM + nonce | 每条记录独立 nonce，防止模式分析 |
| category | 明文 | 用于 UI 筛选和搜索，不敏感 |
| config.value | 视 key 而定 | `master_key_salt` 明文，`security_answer` 加密 |

### 3.3 数据访问约定

- **写入**：业务层传入明文 → DAO 层自动加密 → 存入 SQLite
- **读取**：DAO 层从 SQLite 读取密文 → 自动解密 → 返回明文给业务层
- **搜索**：精确搜索时，对加密字段无法直接 LIKE，解决方案：
  - 内存中加载所有记录后解密，再 Python 端过滤（数据量 < 1000 条完全可行）
  - 或增加 `app_name_search_index` 字段存储 app_name 的明文前缀（牺牲少量隐私换性能）
  
**决策**：采用内存过滤方案（ simplicity > performance，1000 条数据毫秒级）。

---

## 4. 模块划分与职责

```
local_password_vault/
├── main.py                     # 程序入口
├── requirements.txt            # 依赖清单
│
├── config/
│   └── settings.py             # 全局配置（数据库路径、模型名、超时时间等）
│
├── core/
│   ├── __init__.py
│   ├── crypto.py               # 加密引擎：密钥派生、AES-256-GCM 加解密
│   ├── database.py             # 数据库管理：连接、建表、DAO 基类
│   └── clipboard.py            # 剪贴板管理：安全复制、定时清空
│
├── services/
│   ├── __init__.py
│   ├── account_service.py      # 账号 CRUD、排序
│   ├── category_service.py     # AI 分类、缓存管理
│   ├── search_service.py       # 精确搜索 + 语义搜索
│   ├── ocr_service.py          # PaddleOCR 截图识别
│   ├── export_service.py       # Excel 导出、加密备份
│   └── sync_service.py         # PWA HTML 生成
│
├── models/
│   ├── __init__.py
│   └── account.py              # 数据模型：Account dataclass
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py          # 主窗口：分类导航 + 账号列表 + 搜索
│   ├── account_dialog.py       # 添加/编辑弹窗
│   ├── detail_dialog.py        # 账号详情弹窗（查看密码）
│   ├── settings_dialog.py      # 设置：主密码、密保、主题
│   └── lock_screen.py          # 会话锁定界面
│
├── ai/
│   ├── __init__.py
│   └── ollama_client.py        # Ollama HTTP API 封装
│
├── templates/
│   └── pwa_template.html       # PWA HTML 模板（含 WebCrypto JS）
│
└── assets/
    └── icon.png                # 应用图标
```

---

## 5. 核心类定义

### 5.1 Account 模型

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Account:
    id: Optional[int] = None
    app_name: str = ""
    url: str = ""
    username: str = ""
    password: str = ""
    category: str = "其他"  # 默认分类
    remark: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

### 5.2 CryptoManager 接口

```python
class CryptoManager:
    def __init__(self, master_password: str, salt: Optional[bytes] = None):
        """初始化，传入主密码和盐值（首次使用不传 salt，自动生成）"""
        pass
    
    @property
    def salt(self) -> bytes:
        """返回当前盐值（需保存到配置文件）"""
        pass
    
    def encrypt(self, plaintext: str) -> bytes:
        """AES-256-GCM 加密，返回 nonce + tag + ciphertext 的拼接"""
        pass
    
    def decrypt(self, ciphertext: bytes) -> str:
        """AES-256-GCM 解密"""
        pass
    
    def derive_key(self, password: str, salt: bytes) -> bytes:
        """PBKDF2 密钥派生"""
        pass
```

### 5.3 OllamaClient 接口

```python
class OllamaClient:
    def __init__(self, model: str = "gemma4:4b", host: str = "http://localhost:11434"):
        pass
    
    def categorize(self, app_name: str, url: str = "") -> str:
        """返回分类：社交/金融/邮箱/游戏/工作/其他"""
        pass
    
    def semantic_search(self, query: str, app_list: list[str]) -> list[tuple[str, float]]:
        """语义搜索，返回 [(app_name, confidence), ...]"""
        pass
```

---

## 6. UI 交互逻辑

### 6.1 主窗口布局

```
┌──────────────────────────────────────────────────────┐
│  [🔍 搜索框...]              [+] 添加账号  [⚙] 设置   │
├──────────┬───────────────────────────────────────────┤
│          │                                           │
│  📁 分类  │   A                                       │
│  ────────│   ┌─────────────────────────────────┐     │
│  ○ 全部  │   │ 支付宝         138****1234      │     │
│  ● 金融  │   │  alipay.com                     │     │
│  ○ 社交  │   └─────────────────────────────────┘     │
│  ○ 邮箱  │                                           │
│  ○ 游戏  │   B                                       │
│  ○ 工作  │   ┌─────────────────────────────────┐     │
│  ○ 其他  │   │ 百度网盘       myname@163.com   │     │
│          │   │  pan.baidu.com                  │     │
│          │   └─────────────────────────────────┘     │
│          │                                           │
├──────────┴───────────────────────────────────────────┤
│  [🔒 锁定]  [📤 导出]  [📱 同步到手机]               │
└──────────────────────────────────────────────────────┘
```

**交互规则**：
- 账号列表项：点击展开详情（非弹窗，而是列表项下方展开）
- 展开后显示：完整账号、密码（••••，点击👁切换显示）、备注、网址
- 操作按钮：复制账号、复制密码、编辑、删除

### 6.2 添加/编辑弹窗

```
┌──────────────────────────────────────────┐
│  添加账号                        [×]     │
├──────────────────────────────────────────┤
│  [手动输入]  [📷 截图导入]               │
├──────────────────────────────────────────┤
│  应用名 *  [________________]            │
│  网址      [________________]            │
│  账号 *    [________________]            │
│  密码 *    [________________] [👁]       │
│  备注      [________________]            │
│  分类      [金融 ▼]  (AI 智能分类 ✨)    │
├──────────────────────────────────────────┤
│           [取消]  [保存]                 │
└──────────────────────────────────────────┘
```

**AI 分类流程**：
1. 用户输入应用名，失去焦点时触发
2. 检查 category_cache 表（用 app_name 的 SHA256 哈希匹配）
3. 有缓存 → 直接填充分类
4. 无缓存 → 调用 Ollama API（异步，显示"正在分析..."）
5. 返回结果 → 填充分类下拉框，用户可修改
6. 用户保存后 → 写入 category_cache

**截图导入流程**：
1. 切换到"截图导入"标签页
2. 拖放或选择图片文件
3. 调用 PaddleOCR 识别文字
4. 用正则表达式提取可能的账号/密码（如 `账号[:：]\s*(\S+)`）
5. 自动填充到对应字段，不确定的字段留空
6. 用户确认修正后保存

### 6.3 详情展开面板

```
┌──────────────────────────────────────────┐
│ 支付宝                          [编辑] [🗑]│
│ alipay.com                               │
│ ──────────────────────────────────────── │
│ 账号: myaccount@163.com        [复制]    │
│ 密码: ••••••••                 [复制] [👁]│
│ 备注: 绑定了银行卡，请勿修改密码         │
│ 分类: 金融                               │
│ 创建: 2026-04-20                         │
└──────────────────────────────────────────┘
```

### 6.4 会话锁定

- 触发条件：5 分钟无鼠标/键盘操作
- 锁定状态：主窗口遮罩，显示密码输入框
- 输入主密码 → 验证通过后恢复
- 注意：锁定期间数据仍在内存中，只是 UI 遮罩

---

## 7. API 与数据流

### 7.1 首次启动流程

```
用户打开程序
    ↓
检查数据库文件是否存在
    ↓ 否
创建数据库 + 建表
显示"设置主密码"向导
    ↓
输入主密码 + 确认密码
    ↓
生成随机盐值 → PBKDF2 派生密钥
    ↓
提示设置密保问题（可选）
    ↓
生成密钥文件（可选，保存到用户指定路径）
    ↓
保存 salt、密保问题加密答案到 config 表
    ↓
进入主窗口
```

### 7.2 账号添加数据流

```
用户点击 [+] 添加
    ↓
弹出 AccountDialog
用户输入信息
    ↓
失去焦点 / 点击 AI 分类按钮
    ↓
CategoryService 处理：
  1. 计算 app_name SHA256
  2. 查 category_cache
  3. 命中 → 返回缓存
  4. 未命中 → 调用 OllamaClient.categorize()
  5. 返回结果填充下拉框
    ↓
用户点击保存
    ↓
AccountService.add_account(account)
    ↓
DatabaseManager 加密各字段
    ↓
INSERT INTO accounts
    ↓
更新 UI 列表
```

### 7.3 搜索数据流

```
用户在搜索框输入"我的游戏账号"
    ↓
SearchService.search(query)
    ↓
第一层：精确搜索
  SELECT * FROM accounts
  加载所有记录到内存 → 逐条解密
  对 app_name, url, username, remark 做子串匹配
  返回精确匹配列表（立即展示）
    ↓
如果精确匹配结果 < 3 条
  第二层：语义搜索
  提取所有 app_name 列表
  构造 Prompt 调用 OllamaClient.semantic_search()
  返回 [(app_name, confidence)]
  根据 app_name 从数据库提取完整记录
  在 UI 中标注"智能推荐"
    ↓
合并结果展示
```

---

## 8. 关键算法与 Prompt 设计

### 8.1 AI 分类 Prompt

```
你是一款密码管理软件的分类助手。请根据应用名称和网址，
判断该账号属于以下哪个分类：社交、金融、邮箱、游戏、工作、其他。

规则：
- 只返回分类名称中的一个词，不要解释
- 如果无法判断，返回"其他"

应用名称：{app_name}
网址：{url}

分类：
```

### 8.2 语义搜索 Prompt

```
用户正在密码管理软件中搜索账号，他说："{query}"

软件中存储的账号列表如下（每行一个应用名）：
{app_list}

请从列表中找出用户可能想找的应用，返回匹配的应用名。
只返回应用名，每行一个，不要解释。如果没有匹配的，返回"无"。

匹配结果：
```

### 8.3 密码强度评估（可选扩展）

```python
def check_password_strength(password: str) -> dict:
    """
    返回 {"score": 0-4, "label": "弱/中/强", "warnings": [...]}
    """
    # 0-1: 弱（长度<8，纯数字/字母）
    # 2: 中（长度>=8，含两种字符类型）
    # 3-4: 强（长度>=12，含三种及以上字符类型）
```

---

## 9. 异常处理策略

| 场景 | 处理方案 |
|------|---------|
| Ollama 未启动 | 分类功能降级为手动选择，提示"AI 服务不可用" |
| OCR 识别失败 | 弹窗提示"未识别到文字，请手动输入" |
| 主密码输入错误 | 提示剩余尝试次数，连续 5 次错误需等待 1 分钟 |
| 数据库文件损坏 | 提示"数据文件损坏，尝试从备份恢复" |
| 导出时文件被占用 | 提示"文件被占用，请关闭后重试" |
| 内存中数据解密失败 | 记录日志，跳过该条数据，展示"部分数据损坏" |

---

## 10. 开发里程碑（MVP 分解）

### MVP 1：基础框架 + 加密存储（1 周）

**目标**：能增删改查账号，数据加密存储

**任务清单**：
- [ ] 搭建项目结构（main.py、core/、services/、ui/、models/）
- [ ] 实现 CryptoManager（PBKDF2 + AES-256-GCM）
- [ ] 实现 DatabaseManager（SQLite 建表 + 加解密透明处理）
- [ ] 实现 Account 模型 + AccountService（CRUD）
- [ ] 实现主窗口 UI（PyQt6）：分类导航、账号列表、搜索框
- [ ] 实现添加/编辑弹窗
- [ ] 实现主密码设置与验证流程
- [ ] 实现剪贴板复制（含 20 秒自动清空）

**验收标准**：
- 能添加账号，关闭程序再打开数据仍在
- 用文本编辑器打开 SQLite 文件，看不到任何明文密码
- 复制密码后 20 秒剪贴板自动清空

### MVP 2：OCR + AI 分类（1 周）

**目标**：截图导入账号，AI 自动分类

**任务清单**：
- [ ] 集成 PaddleOCR（OCRService）
- [ ] 实现截图导入流程（文件选择 → OCR → 字段提取 → 自动填充）
- [ ] 集成 OllamaClient（HTTP 调用 Gemma 4 E4B）
- [ ] 实现 CategoryService（缓存管理 + AI 分类）
- [ ] 在添加弹窗中集成 AI 分类功能
- [ ] 实现批量分类功能（对已有未分类记录）
- [ ] 优化 OCR 字段提取正则规则

**验收标准**：
- 上传一张含账号密码的截图，能自动填充字段
- 输入"支付宝"自动分类为"金融"
- 分类错误的可以手动修改并记住

### MVP 3：搜索 + 导出（3-5 天）

**目标**：分层搜索、Excel 导出

**任务清单**：
- [ ] 实现精确搜索（内存过滤，支持拼音首字母？可选）
- [ ] 实现语义搜索（OllamaClient.semantic_search）
- [ ] 搜索结果展示优化（精确匹配优先，语义匹配标注）
- [ ] 实现首字母排序（A-Z 索引）
- [ ] 实现"最近添加"排序
- [ ] 实现 Excel 导出（openpyxl，可选含/不含密码）
- [ ] 实现加密备份导出（.vault 文件）

**验收标准**：
- 搜索"游戏"能找到分类为游戏的账号
- 搜索"支付宝那个"能通过语义找到支付宝
- 导出的 Excel 文件用 Excel 能正常打开

### MVP 4：PWA 同步 + 优化（3-5 天）

**目标**：手机离线同步，UI 美化

**任务清单**：
- [ ] 设计 PWA HTML 模板（含 WebCrypto AES 解密 JS）
- [ ] 实现 SyncService（生成加密 HTML）
- [ ] 实现设置页面（主题切换、密保问题、密钥文件）
- [ ] 实现会话锁定（5 分钟无操作自动锁定）
- [ ] UI 美化（深色/浅色主题、动画过渡）
- [ ] 弱密码检测（可选）
- [ ] 密码生成器（可选）

**验收标准**：
- 生成的 HTML 文件在手机浏览器打开能正常解密
- 切换主题后所有界面颜色正常
- 闲置 5 分钟后自动锁定

---

## 11. 配置文件说明

`config.json`（存储在用户目录 `.local_password_vault/` 下）：

```json
{
  "version": "1.0",
  "master_key_salt": "base64_encoded_salt",
  "security_question": "您母亲的姓氏是？",
  "security_answer_encrypted": "base64_encrypted_answer",
  "key_file_enabled": true,
  "theme": "dark",
  "auto_lock_minutes": 5,
  "clipboard_clear_seconds": 20,
  "ollama_model": "gemma4:4b",
  "ollama_host": "http://localhost:11434"
}
```

---

## 12. 安全注意事项

1. **内存安全**：Account 对象在内存中是明文，程序崩溃可能产生 core dump。Python 层面难以完全避免，但可定期 `del` 不再使用的密码变量。
2. **密钥不落地**：派生密钥只存在于内存，不保存到磁盘。
3. **截图清理**：OCR 完成后，询问用户是否删除原截图文件（默认删除）。
4. **备份安全**：.vault 备份文件用主密码加密，但需提醒用户妥善保管。
5. **密钥文件**：如启用密钥文件恢复，提醒用户将 .key 文件存放到安全位置（如 U 盘），不要和数据库放一起。

---

## 13. 待确认问题（开发前最终确认）

以下问题已确认，记录在此：

| 问题 | 决策 |
|------|------|
| 加密方案 | A：应用层 AES-256-GCM |
| 主密码恢复 | 允许密保问题 + 密钥文件 |
| 剪贴板清空 | 20 秒，仅清空密码 |
| PWA 同步 | 手动复制文件，主密码解密 |
| AI 分类 | 用户可自定义分类 |
| 搜索策略 | 先精确匹配，再语义搜索 |
| 列表显示 | 应用名 + 脱敏账号 |
| 详情展开 | 点击展开，显示完整信息 |

---

**下一步行动**：
1. 确认本 v1 文档无遗漏
2. 开始 MVP 1 开发：搭建项目框架 + 加密模块
3. 每完成一个 MVP 进行代码 Review

---

*文档结束*

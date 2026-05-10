# Agent 工作指南

## 项目背景
本地密码保险箱 - 一个基于 PyQt6 的密码管理软件，集成本地 AI（Ollama + Gemma4:4b）进行智能分类、语义搜索和 AI 助手对话。

## 截图流程规范

**必须由用户主动提供截图，禁止自动截图。**

- 当需要查看 UI 效果时，**通知用户并请求截图**，让用户自行截取并发送
- 不要尝试用代码自动截图窗口
- 用户发送截图后，仔细阅读并根据截图反馈进行针对性调整

## 程序运行规范

**不要自动运行程序，除非用户明确要求。**

- 代码修改完成后，通知用户修改完成，由用户自行决定是否运行
- 不要在每次修改后自动启动程序
- 用户说"启动"或"运行"时才执行

## 技术栈
- Python 3.11
- PyQt6 6.11.0
- Ollama (gemma4:4b) - 仅支持 `/api/generate`，不支持 `/api/embeddings`
- SQLite + cryptography (密码加密存储)

## AI 大模型超时限制

AI 助手调用大模型时的超时限制：
- **最低 5 分钟（300 秒）**，最长 10 分钟（600 秒）
- **不允许改到更低！！！**
- 涉及文件：`ai/ollama_client.py`、`services/ai_*.py`、`ui/dialogs/health_check_dialog.py` 等所有实例化 `OllamaClient` 的位置

## 环境配置

**项目专用 Conda 环境**：`D:\Anaconda\envs\Passwordmanage`

- 后续如需运行代码、导入测试或执行任何 Python 脚本，**必须使用该环境**，禁止直接使用系统默认 Python 环境。
- 激活方式：`conda activate Passwordmanage`
- 该环境已预装 PyQt6、cryptography、openpyxl、pypinyin、paddleocr、qt-material、requests 等全部依赖。

---

## 自定义工作指令

### 记录问题
当用户说"记录问题"时，将本次排查的 Bug/问题按以下格式追加到 `docs/debug_journal.md`：

- **日期**
- **现象**
- **排查过程**
- **根因**
- **解决方案**
- **经验总结**

参考文件中已有记录的格式和结构。

### 更新至更新日志
当用户说"更新至更新日志"、"追加至更新日志"或"更新 CHANGELOG"时，将本次所有改动按以下分类追加到 `docs/CHANGELOG.md`：

- **新增**：全新功能、模块、特性
- **优化**：现有功能的改进、性能提升、代码重构
- **修复**：Bug 修复

格式参考已有记录：`## [未发布] — YYYY-MM-DD` 或在现有未发布版本下追加。如果已存在同一天的未发布条目，直接在该条目下补充，不要新建。

"""HelpDialog - 使用帮助对话框"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QWidget
)
from PyQt6.QtCore import Qt
from core.theme_manager import ThemeManager
from core.icon_manager import IconManager


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.setWindowIcon(IconManager.app_icon())
        self.setWindowTitle("使用帮助")
        self.setMinimumSize(600, 640)
        self.resize(680, 800)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(32, 24, 32, 16)
        h_layout.setSpacing(4)
        lbl_title = QLabel("使用帮助")
        lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 22px; font-weight: 600;")
        h_layout.addWidget(lbl_title)
        lbl_sub = QLabel("SecretManage 完整使用指南")
        lbl_sub.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 14px;")
        h_layout.addWidget(lbl_sub)
        main_layout.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {colors.border_light};")
        main_layout.addWidget(sep)

        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(32, 20, 32, 12)
        c_layout.setSpacing(0)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 简介
        intro = QLabel(
            "SecretManage 是一款纯本地密码管理器，所有数据均采用 AES-256-GCM 加密存储，"
            "AI 功能完全在本地运行（Ollama + gemma4:4b），无需联网即可使用，确保你的隐私绝对安全。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.7; padding-bottom: 24px;")
        c_layout.addWidget(intro)

        # ==================== 章节 1：快速入门 ====================
        self._add_section(c_layout, "🚀 快速入门")

        self._add_feature_card(
            c_layout,
            "设置主密码",
            "首次启动时，系统会要求你设置一个主密码。这是解锁保险箱、加密和解密所有数据的唯一密钥。",
            steps=[
                "首次打开应用时，在弹出的密码框中输入你的主密码。",
                "主密码不会存储在本地任何位置，程序仅保存其派生出的加密密钥。",
                "请务必牢记主密码，建议写在纸上妥善保管。一旦遗忘，所有数据将无法恢复。",
                "主密码建议包含大小写字母、数字和特殊符号，长度不少于 8 位。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "界面概览",
            "SecretManage 采用三栏式布局，直观高效。",
            steps=[
                "左侧边栏：账号/网址列表、搜索框、分类筛选、排序选项。",
                "中间区域：账号详情展示、编辑表单、批量操作工具栏。",
                "右侧面板：AI 助手「炽阳」对话面板（可展开/收起）。",
                "顶部工具栏：双库切换、添加按钮、设置、健康检查、使用帮助等。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "添加你的第一条数据",
            "你可以添加账号或网址，所有信息都会在本地加密保存。",
            steps=[
                "点击顶部「+ 添加账号」或「添加网址」按钮。",
                "在弹出的对话框中填写标题、用户名、密码、网址等信息。",
                "选择或输入分类和标签（支持二级分类，如「工作 > 开发工具」）。",
                "点击「保存」完成添加。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "密码库与网址库",
            "SecretManage 支持两套独立的数据库，数据互不干扰。",
            steps=[
                "点击顶部工具栏的「密码库」或「网址库」按钮进行切换。",
                "密码库：用于存储各类账号密码（如邮箱、社交、支付等）。",
                "网址库：用于存储常用网址、书签及其相关信息。",
                "两个库的分类、标签、收藏等数据完全独立，支持分别导入导出。",
            ]
        )

        c_layout.addSpacing(24)
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div)
        c_layout.addSpacing(24)

        # ==================== 章节 2：账号与网址管理 ====================
        self._add_section(c_layout, "📁 账号与网址管理")

        self._add_feature_card(
            c_layout,
            "添加与编辑条目",
            "支持单条添加和批量添加，编辑时所有修改实时生效。",
            steps=[
                "单个添加：点击「+ 添加账号/网址」，填写所有字段后保存。",
                "批量添加：点击批量添加按钮，按格式一次性输入多条数据。",
                "编辑条目：在列表中点击条目，中间区域会显示详情，点击「编辑」即可修改。",
                "修改分类：可直接在编辑框中输入新的分类路径（如「生活 > 购物」），系统会自动创建层级。",
                "标签管理：支持为一条数据添加多个标签，用逗号或空格分隔。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "分类与标签系统",
            "灵活的二级分类结构和多标签系统，帮助你组织海量数据。",
            steps=[
                "二级分类：分类格式为「一级 > 二级」，如「工作 > 开发工具」。",
                "拖拽调整：在分类树中，你可以拖拽分类节点来调整层级结构。",
                "多标签：一条数据可拥有多个标签，如「重要, 支付, 工作」。",
                "筛选：点击左侧分类树中的任意节点，列表会自动筛选该分类下的所有条目。",
                "智能分类：使用 AI 助手可以自动分析内容并建议合理的分类方案。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "收藏与排序",
            "快速访问重要账号，多种排序方式满足不同场景。",
            steps=[
                "收藏条目：在详情页点击「收藏」按钮，该条目会加入收藏夹。",
                "查看收藏：点击左侧「收藏」筛选，只显示已收藏的条目。",
                "排序方式：支持按名称（A-Z / Z-A）、创建时间、最近修改时间排序。",
                "分类内排序：在某一分类筛选状态下排序，只影响当前视图。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "搜索与高级筛选",
            "快速定位目标条目，支持关键词搜索和多重条件组合。",
            steps=[
                "关键词搜索：在左侧搜索框输入标题、用户名、网址等关键词，实时过滤列表。",
                "分类筛选：点击左侧分类树的节点，只显示该分类及其子分类的条目。",
                "标签筛选：部分版本支持按标签筛选，点击标签即可过滤。",
                "AI 语义搜索：在「炽阳」面板中用自然语言描述需求，AI 会理解意图并返回结果。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "一键复制与剪贴板保护",
            "快速复制敏感信息，同时提供自动清理机制防止泄露。",
            steps=[
                "复制用户名：点击详情页的用户名旁的复制按钮，或点击列表中的用户名。",
                "复制密码：点击密码旁的复制按钮。出于安全考虑，密码默认以掩码显示。",
                "复制网址：点击网址即可复制到剪贴板。",
                "剪贴板保护：复制的密码会在 30 秒后自动从剪贴板清除，防止被恶意程序窃取。",
                "你也可以在设置中调整剪贴板自动清空的时间间隔。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "删除与回收站",
            "误删的数据会先进入回收站，给你一次后悔的机会。",
            steps=[
                "移入回收站：选中条目后点击「删除」，数据会被移入回收站而非立即清除。",
                "恢复条目：进入回收站，选中条目后点击「恢复」即可回到原位置。",
                "彻底删除：在回收站中点击「彻底删除」，数据将被永久移除且无法恢复。",
                "批量删除：支持多选后批量移入回收站，超过 50 条时会触发二次确认。",
            ]
        )

        c_layout.addSpacing(24)
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div2)
        c_layout.addSpacing(24)

        # ==================== 章节 3：数据迁移 ====================
        self._add_section(c_layout, "📥 数据迁移")

        self._add_feature_card(
            c_layout,
            "导入数据",
            "从其他密码管理器或文件格式迁移数据到 SecretManage。",
            steps=[
                "打开「设置 → 导入」，选择你要导入的文件。",
                "支持的格式：Bitwarden JSON/CSV、LastPass CSV、1Password CSV、KeePass XML、Excel（.xlsx/.xls）、Markdown/纯文本、加密备份（.vault）。",
                "导入时，系统会自动解析分类信息，如果分类不存在会自动创建。",
                "导入不会自动去重，建议导入后在列表中手动检查并合并重复项。",
                "从 .vault 加密备份恢复时，需要输入原主密码才能解密数据。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "导出数据",
            "将数据导出为其他格式，便于备份或迁移。",
            steps=[
                "打开「设置 → 导出」，选择导出格式。",
                "明文导出（CSV/Excel/JSON）：数据未经加密，请妥善保管，导出后建议立即删除文件。",
                "加密备份（.vault）：最安全的迁移方式，支持跨设备恢复，恢复时需输入原主密码。",
                "导出时可以选择导出整个库，或仅导出当前筛选结果。",
            ]
        )

        c_layout.addSpacing(24)
        div3 = QFrame()
        div3.setFrameShape(QFrame.Shape.HLine)
        div3.setFixedHeight(1)
        div3.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div3)
        c_layout.addSpacing(24)

        # ==================== 章节 4：AI 助手「炽阳」 ====================
        self._add_section(c_layout, "🤖 AI 助手「炽阳」")

        ai_intro = QLabel(
            "炽阳是 SecretManage 内置的本地 AI 助手，基于 Ollama + gemma4:4b 本地运行，"
            "数据不会上传任何云端服务器。支持 Plan（只读查询）与 Build（确认后执行）两种模式。\n\n"
            "点击右侧面板顶部的「炽阳」标题，即可查看详细的使用说明、功能列表和示例指令。"
        )
        ai_intro.setWordWrap(True)
        ai_intro.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.7; padding-bottom: 18px;")
        c_layout.addWidget(ai_intro)

        self._add_feature_card(
            c_layout,
            "首次使用提示",
            "首次与炽阳对话时，模型需要加载到内存中，响应可能较慢。",
            steps=[
                "发送任意消息（如「你好」）完成「神经连接预热」。",
                "预热完成后，后续对话会更加流畅。",
                "如果持续无响应，请检查 Ollama 服务是否正常运行。",
            ]
        )

        c_layout.addSpacing(24)
        div4 = QFrame()
        div4.setFrameShape(QFrame.Shape.HLine)
        div4.setFixedHeight(1)
        div4.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div4)
        c_layout.addSpacing(24)

        # ==================== 章节 5：安全与隐私 ====================
        self._add_section(c_layout, "🔒 安全与隐私")

        self._add_feature_card(
            c_layout,
            "AES-256-GCM 加密存储",
            "所有账号密码均使用 AES-256-GCM 算法加密。主密码通过 PBKDF2 派生加密密钥，即使数据库文件被盗，没有主密码也无法破解。",
            steps=[
                "加密算法：采用业界标准的 AES-256-GCM 对称加密。",
                "密钥派生：主密码通过 PBKDF2-HMAC-SHA256 多次迭代派生密钥，抵抗暴力破解。",
                "无后门：程序不存储主密码明文，开发者也无法绕过加密访问你的数据。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "本地 AI 运行",
            "AI 模型通过 Ollama 在本地运行，所有查询和数据处理都在你的设备上完成，不会上传任何云端服务器，彻底杜绝隐私泄露。",
            steps=[
                "完全离线：AI 推理过程不需要联网。",
                "数据不出境：你的账号信息、密码、网址等敏感数据仅在本地内存中被 AI 处理。",
                "模型私有化：你可以通过 Ollama 自行管理模型版本和参数。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "剪贴板自动清空",
            "复制的密码会在 30 秒后自动从剪贴板清除，防止被后台恶意程序窃取。你可以在设置中调整清空时间。",
            steps=[
                "默认保护：密码复制后 30 秒自动清空剪贴板。",
                "自定义时间：可在「设置 → 安全」中调整自动清空时间（10 秒 ~ 300 秒）。",
                "手动清空：点击顶部工具栏的「清空剪贴板」按钮可立即清除。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "安全健康检查",
            "定期运行安全健康检查，评估主密码强度、检测重复密码和弱密码风险，并给出改进建议。",
            steps=[
                "启动检查：点击顶部工具栏的盾牌图标即可运行健康检查。",
                "检查项目：主密码强度、重复密码、弱密码、长期未修改的密码。",
                "改进建议：检查结果会以报告形式展示，点击建议可直接跳转到对应条目进行处理。",
            ]
        )

        self._add_feature_card(
            c_layout,
            "无网络依赖",
            "核心功能完全离线运行，不需要注册账号、不需要联网验证，你的数据只属于你自己。",
            steps=[
                "无需注册：没有账号体系，没有云服务绑定。",
                "纯本地存储：数据库文件默认存储在应用目录下，可自定义路径。",
                "自主可控：你可以随时导出、备份或迁移数据，不受任何服务商限制。",
            ]
        )

        c_layout.addSpacing(24)
        div5 = QFrame()
        div5.setFrameShape(QFrame.Shape.HLine)
        div5.setFixedHeight(1)
        div5.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div5)
        c_layout.addSpacing(24)

        # ==================== 章节 6：快捷键与使用技巧 ====================
        self._add_section(c_layout, "💡 快捷键与使用技巧")

        shortcuts = [
            ("Ctrl + F", "聚焦搜索框"),
            ("Ctrl + N", "添加新条目"),
            ("Ctrl + M", "进入 / 退出批量选择模式"),
            ("Delete", "删除当前选中条目"),
            ("Escape", "清除搜索 / 退出选择模式"),
            ("Ctrl + D", "切换深色 / 浅色主题"),
            ("Ctrl + L", "锁定应用"),
            ("Ctrl + 1", "切换到密码库"),
            ("Ctrl + 2", "切换到网址库"),
            ("Ctrl + Z", "撤销批量删除"),
        ]
        self._add_shortcuts_card(c_layout, shortcuts)

        tips = [
            "双击列表中的条目可快速进入编辑模式。",
            "在搜索框中输入内容时，列表会实时过滤，无需按回车。",
            "拖拽分类节点可以快速调整层级结构。",
            "收藏夹中的条目会显示星标，方便一眼识别。",
            "批量选择模式下，按住 Ctrl 并拖动鼠标可框选多个条目。",
            "在 AI 面板中，可用「刚才找到的」「前面那些」指代历史搜索结果。",
            "导出的 .vault 文件是最安全的备份方式，建议定期导出并存放到安全位置。",
            "密码生成器支持自定义长度和字符类型，可在添加账号时快速调用。",
            "点击左侧列表的表头可以进行快速排序切换。",
            "回收站中的条目仍然占用数据库空间，确认无用后建议彻底删除。",
        ]
        self._add_tips_card(c_layout, tips)

        c_layout.addSpacing(24)
        div6 = QFrame()
        div6.setFrameShape(QFrame.Shape.HLine)
        div6.setFixedHeight(1)
        div6.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div6)
        c_layout.addSpacing(24)

        # ==================== 章节 7：常见问题 ====================
        self._add_section(c_layout, "❓ 常见问题")

        faqs = [
            ("忘记主密码怎么办？", "主密码是加密密钥的唯一来源，程序不存储也无法重置主密码。请务必牢记，建议将主密码写在纸上妥善保管。一旦遗忘，所有加密数据将永久无法访问。"),
            ("AI 响应慢或卡顿？", "首次查询需要加载模型，可能较慢。发送任意消息完成「预热」后会流畅很多。若持续卡顿，请检查 Ollama 是否正常运行，或尝试重启 Ollama 服务。"),
            ("如何备份数据？", "推荐通过「设置 → 导出」生成加密备份（.vault），这是最安全的备份方式。也可导出为 Excel/CSV，但需注意明文安全风险。建议定期备份。"),
            ("导入时出现重复数据？", "目前导入不会自动去重，建议导入后在列表中手动检查并合并重复项。你可以使用搜索功能快速定位重复标题。"),
            ("支持多设备同步吗？", "SecretManage 是纯本地应用，暂不支持云同步。你可以通过加密备份文件（.vault）手动在设备间迁移数据，恢复时需输入原主密码。"),
            ("可以更改主密码吗？", "当前版本暂不支持直接修改主密码。如需更换，建议导出加密备份后重新安装应用并设置新主密码，再导入数据。"),
            ("数据库文件在哪里？", "数据库文件默认存储在应用目录下，名为 secretmanage.db。你可以通过设置查看或更改存储路径。"),
        ]
        for question, answer in faqs:
            self._add_faq_item(c_layout, question, answer)

        c_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # Footer
        footer = QWidget()
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(32, 8, 32, 18)
        f_layout.addStretch()
        btn = QPushButton("完成")
        btn.setFixedSize(120, 34)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.accent_orange_dark}; color: {colors.text_on_accent}; border: none;
                border-radius: 17px; font-size: 14px; font-weight: 500;
            }}
            QPushButton:hover {{ background-color: {colors.accent_orange_dark}; }}
            QPushButton:pressed {{ background-color: {colors.accent_orange_dark}; }}
        """)
        btn.clicked.connect(self.accept)
        f_layout.addWidget(btn)
        f_layout.addStretch()
        main_layout.addWidget(footer)

    # -------------------- 辅助方法 --------------------

    def _add_section(self, layout, title: str):
        colors = ThemeManager.instance().colors
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 18px; font-weight: 600; padding-bottom: 12px;")
        layout.addWidget(lbl)

    def _add_subtitle(self, layout, text: str):
        colors = ThemeManager.instance().colors
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-top: 8px; padding-bottom: 8px;")
        layout.addWidget(lbl)

    def _add_paragraph(self, layout, text: str):
        colors = ThemeManager.instance().colors
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.7; padding-bottom: 18px;")
        layout.addWidget(lbl)

    def _add_feature_card(self, layout, title: str, desc: str, steps: list = None, examples: list = None):
        colors = ThemeManager.instance().colors
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-bottom: 4px; padding-top: 2px;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-bottom: 8px;")
        layout.addWidget(lbl_desc)

        if steps or examples:
            card = QWidget()
            card.setObjectName("helpCard")
            card.setStyleSheet(f"""
                #helpCard {{
                    background-color: {colors.bg_primary};
                    border-radius: 10px;
                    border: 1px solid {colors.border_subtle};
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(6)

            if steps:
                for i, step in enumerate(steps, 1):
                    step_lbl = QLabel(f"{i}.  {step}")
                    step_lbl.setWordWrap(True)
                    step_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.7;")
                    card_layout.addWidget(step_lbl)

            if examples:
                for ex in examples:
                    ex_lbl = QLabel(f'"{ex}"')
                    ex_lbl.setWordWrap(True)
                    ex_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.7;")
                    card_layout.addWidget(ex_lbl)

            layout.addWidget(card)

        layout.addSpacing(18)

    def _add_example_card(self, layout, examples: list):
        colors = ThemeManager.instance().colors
        card = QWidget()
        card.setObjectName("helpCard")
        card.setStyleSheet(f"""
            #helpCard {{
                background-color: {colors.bg_primary};
                border-radius: 10px;
                border: 1px solid {colors.border_subtle};
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(6)
        for ex in examples:
            ex_lbl = QLabel(f'"{ex}"')
            ex_lbl.setWordWrap(True)
            ex_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.7;")
            card_layout.addWidget(ex_lbl)
        layout.addWidget(card)

    def _add_bullet_list(self, layout, items: list):
        colors = ThemeManager.instance().colors
        bullet_widget = QWidget()
        b_layout = QVBoxLayout(bullet_widget)
        b_layout.setContentsMargins(14, 10, 14, 10)
        b_layout.setSpacing(8)
        for item in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("\u2022")
            dot.setStyleSheet(f"color: {colors.text_disabled}; font-size: 14px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)
            txt = QLabel(item)
            txt.setWordWrap(True)
            txt.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.6;")
            row.addWidget(dot)
            row.addWidget(txt, 1)
            b_layout.addLayout(row)
        layout.addWidget(bullet_widget)
        layout.addSpacing(12)

    def _add_tips_card(self, layout, tips: list):
        colors = ThemeManager.instance().colors
        tips_card = QWidget()
        tips_card.setObjectName("helpTipsCard")
        tips_card.setStyleSheet(f"""
            #helpTipsCard {{
                background-color: {colors.bg_primary};
                border-radius: 12px;
                border: 1px solid {colors.border_subtle};
            }}
        """)
        tips_layout = QVBoxLayout(tips_card)
        tips_layout.setContentsMargins(18, 16, 18, 16)
        tips_layout.setSpacing(10)
        tips_title = QLabel("使用小贴士")
        tips_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500;")
        tips_layout.addWidget(tips_title)
        for tip in tips:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("\u2022")
            dot.setStyleSheet(f"color: {colors.text_disabled}; font-size: 14px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignTop)
            txt = QLabel(tip)
            txt.setWordWrap(True)
            txt.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px; line-height: 1.6;")
            row.addWidget(dot)
            row.addWidget(txt, 1)
            tips_layout.addLayout(row)
        layout.addWidget(tips_card)

    def _add_shortcuts_card(self, layout, shortcuts: list):
        colors = ThemeManager.instance().colors
        card = QWidget()
        card.setObjectName("helpShortcutsCard")
        card.setStyleSheet(f"""
            #helpShortcutsCard {{
                background-color: {colors.bg_primary};
                border-radius: 12px;
                border: 1px solid {colors.border_subtle};
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(8)
        title = QLabel("快捷键一览")
        title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500;")
        card_layout.addWidget(title)
        for key, desc in shortcuts:
            row = QHBoxLayout()
            row.setSpacing(12)
            row.setContentsMargins(0, 0, 0, 0)
            key_lbl = QLabel(key)
            key_lbl.setStyleSheet(f"""
                color: {colors.accent_blue_text};
                background-color: {colors.accent_blue_bg};
                font-size: 12px;
                font-weight: 600;
                padding: 2px 8px;
                border-radius: 4px;
            """)
            key_lbl.setFixedHeight(22)
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(f"color: {colors.text_primary}; font-size: 13px;")
            row.addWidget(key_lbl)
            row.addWidget(desc_lbl, 1)
            card_layout.addLayout(row)
        layout.addWidget(card)

    def _add_faq_item(self, layout, question: str, answer: str):
        colors = ThemeManager.instance().colors
        lbl_q = QLabel(question)
        lbl_q.setWordWrap(True)
        lbl_q.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 600; padding-top: 10px; padding-bottom: 4px;")
        layout.addWidget(lbl_q)
        lbl_a = QLabel(answer)
        lbl_a.setWordWrap(True)
        lbl_a.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.7; padding-bottom: 14px;")
        layout.addWidget(lbl_a)

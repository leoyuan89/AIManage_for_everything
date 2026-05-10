"""LocalHelpDialog - 炽阳 使用说明对话框"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QWidget
)
from PyQt6.QtCore import Qt
from core.theme_manager import ThemeManager

class LocalHelpDialog(QDialog):
    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self.setWindowTitle("炽阳 使用说明")
        self.setMinimumSize(540, 620)
        self.resize(580, 700)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(32, 24, 32, 16)
        h_layout.setSpacing(4)
        lbl_title = QLabel("炽阳")
        lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 22px; font-weight: 600;")
        h_layout.addWidget(lbl_title)
        lbl_sub = QLabel("你的本地密码库 AI 助手")
        lbl_sub.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 14px;")
        h_layout.addWidget(lbl_sub)
        main_layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {colors.border_light};")
        main_layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(32, 20, 32, 12)
        c_layout.setSpacing(0)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        intro = QLabel("基于 Ollama + gemma4:4b 本地运行，数据不会上传云端。\n"
                       "支持 Plan（只读查询）与 Build（确认后执行）两种模式。")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; line-height: 1.7; padding-bottom: 24px;")
        c_layout.addWidget(intro)

        # Plan
        plan_header = QHBoxLayout()
        plan_header.setSpacing(10)
        plan_badge = QLabel("Plan")
        plan_badge.setStyleSheet(f"color: {colors.accent_blue}; background-color: {colors.accent_blue_bg_light}; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;")
        plan_name = QLabel("规划模式")
        plan_name.setStyleSheet(f"color: {colors.text_primary}; font-size: 17px; font-weight: 600;")
        plan_header.addWidget(plan_badge)
        plan_header.addWidget(plan_name)
        plan_header.addStretch()
        c_layout.addLayout(plan_header)

        desc_plan = QLabel("仅查询和分析现有数据，不会修改、添加或删除任何内容。")
        desc_plan.setWordWrap(True)
        desc_plan.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-top: 4px; padding-bottom: 18px;")
        c_layout.addWidget(desc_plan)

        features_plan = [
            ("语义搜索", "用自然语言描述你想找的内容，炽阳会理解意图并返回相关结果。",
             ["帮我找一下跟学习有关的账号", "有哪些支付类的网站"]),
            ("条件筛选", "按分类、标签等条件精确筛选条目。",
             ["列出分类是工作>开发工具的所有账号", "筛选标签包含「支付」的网址"]),
            ("分类与统计", "查看当前库的分类结构、统计信息和最近变更记录。",
             ["看一下我有哪些分类", "统计一下密码库里有多少条数据", "最近修改了哪些账号"]),
            ("密码强度检测", "分析密码强度等级，仅做检测不保存。",
             ["检测一下这个密码强不强：MyP@ssw0rd"]),
        ]
        for title, desc, examples in features_plan:
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-bottom: 4px; padding-top: 2px;")
            c_layout.addWidget(lbl_title)
            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-bottom: 8px;")
            c_layout.addWidget(lbl_desc)
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
            c_layout.addWidget(card)
            c_layout.addSpacing(18)

        c_layout.addSpacing(24)
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div)
        c_layout.addSpacing(24)

        # Build
        build_header = QHBoxLayout()
        build_header.setSpacing(10)
        build_badge = QLabel("Build")
        build_badge.setStyleSheet(f"color: {colors.accent_orange_text}; background-color: {colors.accent_orange_bg}; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 12px;")
        build_name = QLabel("构建模式")
        build_name.setStyleSheet(f"color: {colors.text_primary}; font-size: 17px; font-weight: 600;")
        build_header.addWidget(build_badge)
        build_header.addWidget(build_name)
        build_header.addStretch()
        c_layout.addLayout(build_header)

        desc_build = QLabel("执行增删改操作前会展示预览，经你确认后才会生效。")
        desc_build.setWordWrap(True)
        desc_build.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-top: 4px; padding-bottom: 18px;")
        c_layout.addWidget(desc_build)

        features_build = [
            ("批量新增", "一次性添加多条账号或网址。",
             ["批量添加：B站 username1 pass1，知乎 username2 pass2"]),
            ("批量更新与重组", "批量修改分类、标签、备注，或由 AI 智能调整分类结构。",
             ["把金融类的账号都改成金融与支付", "帮我把未分类的网址整理一下", "给刚才找到的账号都加上「重要」标签"]),
            ("AI 生成备注并应用", "为指定条目生成备注，预览确认后写入数据库。",
             ["给 GitHub 生成一条备注并加上", "帮刚才找到的账号都生成备注"]),
            ("智能整理", "AI 自动分析数据并建议分类方案，支持细分二级子类。",
             ["帮我把教育类的账号细分一下二级分类", "整理一下重复的网址"]),
            ("批量操作", "将条目移入回收站、批量修改分类或标签，超过 50 条时额外二次确认。",
             ["删除所有分类是测试的账号", "把刚才筛选出来的网址删掉"]),
            ("生成强密码", "生成随机高强度密码，可指定长度和字符类型。",
             ["生成一个 16 位的强密码", "帮我生成不含特殊字符的 12 位密码"]),
        ]
        for title, desc, examples in features_build:
            lbl_title = QLabel(title)
            lbl_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 500; padding-bottom: 4px; padding-top: 2px;")
            c_layout.addWidget(lbl_title)
            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet(f"color: {colors.welcome_sub}; font-size: 13px; padding-bottom: 8px;")
            c_layout.addWidget(lbl_desc)
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
            c_layout.addWidget(card)
            c_layout.addSpacing(18)

        c_layout.addSpacing(24)
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background-color: {colors.border_light};")
        c_layout.addWidget(div2)
        c_layout.addSpacing(20)

        # 小贴士
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
        tips = [
            "首次使用请发送任意消息完成「神经连接预热」。",
            "支持上下文对话，可用「刚才找到的」「前面那些」指代历史结果。",
            "Build 模式下所有操作先展示预览表格，可勾选后再确认执行。",
            "不确定操作是否安全时，先切到 Plan 模式询问。",
        ]
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
        c_layout.addWidget(tips_card)

        c_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

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

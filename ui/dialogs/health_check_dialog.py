"""
密码健康检查对话框
检测弱密码、重复密码、泄露密码，并提供 AI 安全建议
"""
import hashlib
import urllib.request
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QPushButton, QProgressBar, QTabWidget,
    QListWidget, QListWidgetItem, QFrame, QTextBrowser,
    QScrollArea, QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from core.theme_manager import ThemeManager
from core.icon_manager import IconManager
from core.password_strength import evaluate_password_strength
from core.icon_manager import IconManager

logger = logging.getLogger(__name__)


class AiRecommendationThread(QThread):
    """后台线程：获取 AI 安全建议，不阻塞 UI"""
    finished = pyqtSignal(str)  # HTML 内容
    
    def __init__(self, results, ai_assistant):
        super().__init__()
        self._results = results
        self._ai_assistant = ai_assistant
    
    def run(self):
        from services.ai_service_manager import AIServiceManager
        from ai.ollama_client import OllamaClient
        
        weak_names = [item['account'].app_name for item in self._results['weak']]
        reused_summary = []
        for group in self._results['reused_groups']:
            names = [g['account'].app_name for g in group]
            reused_summary.append(f"{'、'.join(names)} ({len(names)}个账号)")
        
        summary = f"弱密码: {len(self._results['weak'])}个"
        if weak_names:
            summary += f", 涉及: {'、'.join(weak_names[:10])}"
        summary += f"\n重复密码组: {len(self._results['reused_groups'])}组"
        if reused_summary:
            summary += f", 涉及: {'; '.join(reused_summary[:5])}"
        
        prompt = f"""Based on the following password security issues, provide 3-5 actionable recommendations in Chinese. 
Keep it concise, each recommendation on one line starting with a number.

{summary}"""
        
        try:
            ai_manager = AIServiceManager.instance()
            # 已在 AiRecommendationThread 后台线程中执行，不阻塞主线程
            ollama = OllamaClient(model=ai_manager.get_state().model_name or "gemma4:4b", timeout=300)
            
            full_response = ""
            for token in ollama.generate_stream(prompt, temperature=0.5):
                if self.isInterruptionRequested():
                    return
                full_response += token
            
            # Convert to simple HTML
            text = full_response.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            lines = text.strip().split('\n')
            import re
            color = "#e0e0e0"
            html = f'<div style="color:{color}; line-height:1.7;">'
            for line in lines:
                line = line.strip()
                if not line:
                    html += '<br/>'
                    continue
                line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
                html += f'<p>{line}</p>'
            html += '</div>'
            self.finished.emit(html)
        except Exception as e:
            logger.exception("AI recommendations failed")
            # Fall back to generic
            fallback = """
            <ol>
            <li><b>修改弱密码：</b>为标记为"弱"或"中"的账号设置更复杂的密码。</li>
            <li><b>避免重复使用密码：</b>每个重要账号应使用独立密码。</li>
            <li><b>定期更换密码：</b>建议每3-6个月更换一次重要账号的密码。</li>
            <li><b>启用双因素认证：</b>对于支持2FA的服务，开启双因素认证。</li>
            </ol>
            """
            self.finished.emit(fallback)


class _BreachCheckThread(QThread):
    progress = pyqtSignal(int)
    finished_check = pyqtSignal(list)
    error_msg = pyqtSignal(str)

    def __init__(self, pwd_list, pwd_to_ids):
        super().__init__()
        self.pwd_list = pwd_list
        self.pwd_to_ids = pwd_to_ids

    def _check_one_prefix(self, prefix, items, opener):
        import urllib.request
        suffix_dict = {suffix: pwd for pwd, suffix in items}
        try:
            req = urllib.request.Request(
                f'https://api.pwnedpasswords.com/range/{prefix}',
                headers={'User-Agent': 'LocalPasswordVault'}
            )
            with opener.open(req, timeout=5) as resp:
                response_text = resp.read().decode()
                breached = []
                for line in response_text.splitlines():
                    parts = line.strip().split(':')
                    if len(parts) >= 2:
                        hit_suffix = parts[0]
                        if hit_suffix in suffix_dict:
                            pwd = suffix_dict[hit_suffix]
                            ids = self.pwd_to_ids.get(pwd, [])
                            breached.extend(ids)
                            del suffix_dict[hit_suffix]
                return list(set(breached))
        except Exception as e:
            return e

    def run(self):
        import urllib.request
        prefix_map = {}
        for pwd in self.pwd_list:
            sha1 = hashlib.sha1(pwd.encode()).hexdigest().upper()
            prefix = sha1[:5]
            suffix = sha1[5:]
            if prefix not in prefix_map:
                prefix_map[prefix] = []
            prefix_map[prefix].append((pwd, suffix))
        
        total = len(prefix_map)
        if total == 0:
            self.finished_check.emit([])
            return

        no_proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(no_proxy_handler)
        
        breached = []
        completed = 0
        all_failed = True
        last_error = None
        
        with ThreadPoolExecutor(max_workers=6) as exe:
            future_to_prefix = {
                exe.submit(self._check_one_prefix, p, items, opener): p
                for p, items in prefix_map.items()
            }
            for fut in as_completed(future_to_prefix):
                if self.isInterruptionRequested():
                    break
                result = fut.result()
                if isinstance(result, Exception):
                    last_error = str(result)
                else:
                    all_failed = False
                    breached.extend(result)
                completed += 1
                self.progress.emit(completed)
        
        if self.isInterruptionRequested():
            return
        
        if all_failed and total > 0:
            err_lower = (last_error or '').lower()
            net_errors = ('ssl', 'timed out', 'connection', 'getaddrinfo', 'name resolution', 'unreachable', 'refused')
            if any(k in err_lower for k in net_errors):
                self.error_msg.emit('网络连接失败，无法访问泄露密码检测服务（api.pwnedpasswords.com）。\n'
                                    '可能原因：DNS 解析失败、网络不通、或该服务在您所在地区被屏蔽。\n'
                                    '建议检查网络连接，或稍后再试。')
            elif last_error:
                self.error_msg.emit(f'检测失败: {last_error}')
            return
        self.finished_check.emit(list(set(breached)))


class HealthChecker:
    def __init__(self, account_service, crypto, ai_assistant=None):
        self.account_service = account_service
        self.crypto = crypto
        self.ai_assistant = ai_assistant

    def run_check(self):
        accounts = self.account_service.get_all_accounts()
        results = {
            'total': len(accounts),
            'weak': [],
            'reused_groups': [],
            'breached': [],
            'all_accounts': accounts
        }

        # 1. Weak password check (密码已由 service 层解密，直接使用)
        for acc in accounts:
            try:
                pwd = acc.password or ''
                if not pwd:
                    continue
                strength = evaluate_password_strength(pwd)
                if strength['label'] in ('弱', '中'):
                    results['weak'].append({'account': acc, 'strength': strength, 'password': pwd})
            except Exception:
                pass

        # 2. Reused password check
        pwd_map = {}
        for acc in accounts:
            try:
                pwd = acc.password or ''
                if not pwd:
                    continue
                h = hashlib.sha256(pwd.encode()).hexdigest()
                if h not in pwd_map:
                    pwd_map[h] = []
                pwd_map[h].append({'account': acc, 'password': pwd})
            except Exception:
                pass
        for h, accs in pwd_map.items():
            if len(accs) > 1:
                results['reused_groups'].append(accs)

        return results

    def check_breach(self, password: str) -> Optional[bool]:
        import hashlib
        sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        try:
            req = urllib.request.Request(
                f'https://api.pwnedpasswords.com/range/{prefix}',
                headers={'User-Agent': 'LocalPasswordVault'}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                for line in resp.read().decode().splitlines():
                    if line.split(':')[0] == suffix:
                        return True
        except Exception as e:
            logger.debug(f"HIBP check error: {e}")
            return None
        return False


class HealthCheckDialog(QDialog):
    def __init__(self, account_service, crypto, ai_assistant=None, parent=None):
        super().__init__(parent)
        self.setWindowIcon(IconManager.app_icon())
        self.account_service = account_service
        self.crypto = crypto
        self.ai_assistant = ai_assistant
        self.checker = HealthChecker(account_service, crypto, ai_assistant)
        self._results = None
        self._breach_checked = False
        self._ai_loading = False
        self._last_ai_html = None  # 缓存上次 AI 建议

        self.setWindowTitle("密码健康检查")
        self.setMinimumSize(680, 560)
        self.resize(720, 600)
        self.setup_ui()

        QTimer.singleShot(100, self._start_check)

    def setup_ui(self):
        self._colors = ThemeManager.instance().colors
        c = self._colors

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {c.bg_primary};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # --- Title ---
        title = QLabel("密码健康检查")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {c.text_primary};")
        layout.addWidget(title)

        subtitle = QLabel("检测弱密码、重复使用和泄露风险，保障账号安全")
        subtitle.setStyleSheet(f"color: {c.text_secondary}; font-size: 12px;")
        layout.addWidget(subtitle)

        # --- Progress Bar ---
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {c.bg_tertiary};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {c.accent_blue};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress)

        # --- Summary Cards ---
        self.summary_widget = QWidget()
        summary_layout = QHBoxLayout(self.summary_widget)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)

        self.card_total = self._make_card("总条目", "0", c.accent_blue, c.accent_blue_bg)
        self.card_weak = self._make_card("弱密码", "0", c.accent_red, c.accent_red_bg)
        self.card_reused = self._make_card("重复密码组", "0", c.accent_orange, c.accent_orange_bg)
        self.card_breached = self._make_card("泄露密码", "--", c.accent_red_dark, c.accent_red_bg)

        summary_layout.addWidget(self.card_total)
        summary_layout.addWidget(self.card_weak)
        summary_layout.addWidget(self.card_reused)
        summary_layout.addWidget(self.card_breached)
        layout.addWidget(self.summary_widget)
        self.summary_widget.hide()

        # --- Network Warning ---
        self.network_warning = QLabel("")
        self.network_warning.setStyleSheet(f"""
            color: {c.accent_orange_text};
            font-size: 11px;
            padding: 6px 10px;
            background-color: {c.accent_orange_bg};
            border-radius: 4px;
        """)
        self.network_warning.setWordWrap(True)
        self.network_warning.hide()
        layout.addWidget(self.network_warning)

        # --- Tabs ---
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {c.border_default};
                border-radius: 6px;
                background-color: {c.bg_primary};
                padding: 8px;
            }}
            QTabBar::tab {{
                padding: 8px 16px;
                border: 1px solid {c.border_light};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                background-color: {c.bg_tertiary};
                color: {c.text_secondary};
            }}
            QTabBar::tab:selected {{
                background-color: {c.bg_primary};
                color: {c.accent_blue};
                font-weight: bold;
            }}
        """)

        self.tab_weak = QListWidget()
        self.tab_weak.setStyleSheet(f"QListWidget {{ border: none; background: {c.bg_primary}; }}")
        self.tab_weak.currentItemChanged.connect(self._on_weak_item_clicked)

        self.tab_reused = QListWidget()
        self.tab_reused.setStyleSheet(f"QListWidget {{ border: none; background: {c.bg_primary}; }}")

        self.tab_breached = QListWidget()
        self.tab_breached.setStyleSheet(f"QListWidget {{ border: none; background: {c.bg_primary}; }}")

        self.tabs.addTab(self.tab_weak, "弱密码 (0)")
        self.tabs.addTab(self.tab_reused, "重复密码 (0)")
        self.tabs.addTab(self.tab_breached, "泄露密码 (0)")
        self.tabs.hide()
        layout.addWidget(self.tabs, 1)

        # --- AI Recommendations ---
        self.ai_label = QLabel("AI 安全建议")
        self.ai_label.setStyleSheet(f"color: {c.text_primary}; font-size: 13px; font-weight: bold;")
        self.ai_label.hide()
        layout.addWidget(self.ai_label)

        self.ai_browser = QTextBrowser()
        self.ai_browser.setOpenExternalLinks(True)
        self.ai_browser.setMaximumHeight(180)
        self.ai_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {c.ai_result_bg};
                border: 1px solid {c.border_light};
                border-radius: 6px;
                padding: 10px;
                color: {c.text_primary};
            }}
        """)
        self.ai_browser.hide()
        layout.addWidget(self.ai_browser)

        # --- Bottom buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_check_breach = QPushButton("检测泄露密码")
        self.btn_check_breach.setFixedHeight(36)
        self.btn_check_breach.setFixedWidth(140)
        self.btn_check_breach.setStyleSheet(f"""
            QPushButton {{
                background-color: {c.accent_red_dark};
                color: {c.text_on_dark};
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {c.accent_red};
            }}
            QPushButton:disabled {{
                background-color: {c.bg_tertiary};
                color: {c.text_disabled};
            }}
        """)
        self.btn_check_breach.clicked.connect(self._run_breach_check)
        self.btn_check_breach.hide()
        btn_layout.addWidget(self.btn_check_breach)

        btn_close = QPushButton("关闭")
        btn_close.setFixedHeight(36)
        btn_close.setFixedWidth(80)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {c.bg_tertiary};
                color: {c.text_primary};
                border: 1px solid {c.border_default};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {c.bg_hover};
            }}
        """)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _make_card(self, title: str, value: str, color: str, bg_color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 8px;
                border: 1px solid transparent;
            }}
        """)
        card.setFixedHeight(70)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"color: {color}; font-size: 11px;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(lbl_title)

        lbl_value = QLabel(value)
        lbl_font = QFont()
        lbl_font.setPointSize(18)
        lbl_font.setBold(True)
        lbl_value.setFont(lbl_font)
        lbl_value.setStyleSheet(f"color: {color};")
        lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(lbl_value)

        return card

    def _start_check(self):
        self.checker = HealthChecker(self.account_service, self.crypto, self.ai_assistant)
        try:
            results = self.checker.run_check()
        except Exception as e:
            logger.exception("Health check failed")
            self.progress.hide()
            return

        self._results = results
        try:
            self._populate_ui()
        except Exception as e:
            logger.exception("Health check UI populate failed")

    def _populate_ui(self):
        c = self._colors
        results = self._results

        self.progress.hide()
        self.summary_widget.show()
        self.tabs.show()

        weak_count = len(results['weak'])
        reused_count = len(results['reused_groups'])
        total = results['total']

        # Update cards
        self.card_total.findChildren(QLabel)[1].setText(str(total))
        self.card_weak.findChildren(QLabel)[1].setText(str(weak_count))
        self.card_reused.findChildren(QLabel)[1].setText(str(reused_count))

        # Populate weak tab
        if weak_count > 0:
            for item in results['weak']:
                acc = item['account']
                strength = item['strength']
                list_item = self._make_weak_item(acc, strength)
                self.tab_weak.addItem(list_item)
        else:
            empty_item = QListWidgetItem("没有弱密码")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setForeground(QColor(c.text_tertiary))
            self.tab_weak.addItem(empty_item)

        self.tabs.setTabText(0, f"弱密码 ({weak_count})")

        # Populate reused tab
        if reused_count > 0:
            for group in results['reused_groups']:
                list_item = self._make_reused_group_item(group)
                self.tab_reused.addItem(list_item)
        else:
            empty_item = QListWidgetItem("没有重复使用的密码")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setForeground(QColor(c.text_tertiary))
            self.tab_reused.addItem(empty_item)

        self.tabs.setTabText(1, f"重复密码 ({reused_count})")

        # Breach tab — 优先读取本地缓存
        cached = self.account_service.db.get_breach_results('accounts') if hasattr(self.account_service.db, 'get_breach_results') else None
        if cached:
            self._breach_checked = True
            breached_ids = cached.get('breached_ids', [])
            self._results['breached'] = breached_ids
            breached_count = len(breached_ids)
            self.card_breached.findChildren(QLabel)[1].setText(str(breached_count))
            self.tabs.setTabText(2, f"泄露密码 ({breached_count})")
            self.tab_breached.clear()
            if breached_count > 0:
                for bid in breached_ids:
                    acc = self.account_service.get_account(bid)
                    if acc:
                        text = f"{acc.app_name}  —  {acc.mask_username()}  —  {acc.category or '未分类'}"
                        item = QListWidgetItem(text)
                        item.setData(Qt.ItemDataRole.UserRole, bid)
                        font = QFont()
                        font.setPointSize(11)
                        item.setFont(font)
                        item.setForeground(QColor(c.accent_red))
                        self.tab_breached.addItem(item)
            else:
                msg = "未发现泄露密码"
                empty_item = QListWidgetItem(msg)
                empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
                empty_item.setForeground(QColor(c.text_tertiary))
                self.tab_breached.addItem(empty_item)
            self.btn_check_breach.setText("重新检测泄露密码")
        else:
            empty_item = QListWidgetItem("点击下方按钮检测泄露密码")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setForeground(QColor(c.text_tertiary))
            self.tab_breached.addItem(empty_item)
            self.tabs.setTabText(2, "泄露密码")
            self.btn_check_breach.setText("检测泄露密码")

        self.btn_check_breach.show()
        # 显示缓存的 AI 建议，或提供获取按钮
        self._show_ai_recommendations()

    def _make_weak_item(self, acc, strength) -> QListWidgetItem:
        try:
            c = self._colors
            badge_color_map = {
                "弱": c.accent_red,
                "中": c.accent_orange,
                "强": c.accent_green,
                "极强": c.accent_blue,
            }
            badge_color = badge_color_map.get(strength['label'], c.accent_red)
            username = getattr(acc, 'mask_username', lambda: acc.username or '')()
            text = f"{acc.app_name}  —  {username}  [{strength['label']}]  —  {acc.category or '未分类'}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, acc.id)
            font = QFont()
            font.setPointSize(11)
            item.setFont(font)
            item.setForeground(QColor(c.accent_red))
            return item
        except Exception:
            return QListWidgetItem("加载失败")

    def _make_reused_group_item(self, group) -> QListWidgetItem:
        c = self._colors
        names = []
        for g in group:
            acc = g['account']
            names.append(f"{acc.app_name}({acc.mask_username()})")
        text = f"共有 {len(group)} 个账号使用相同密码：{'、'.join(names)}"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, [g['account'].id for g in group])

        font = QFont()
        font.setPointSize(11)
        item.setFont(font)
        return item

    def _on_weak_item_clicked(self, current, previous):
        if current is None:
            return
        acc_id = current.data(Qt.ItemDataRole.UserRole)
        if acc_id is None:
            return
        QTimer.singleShot(50, lambda: self._open_account_dialog(acc_id))

    def _open_account_dialog(self, acc_id: int):
        from ui.account_dialog import AccountDialog
        from models.account import Account
        if hasattr(self.parent(), 'db'):
            db = self.parent().db
        else:
            return
        acc = self.account_service.get_account(acc_id)
        if acc is None:
            return
        dialog = AccountDialog(db, account=acc, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_check()

    def _refresh_check(self):
        if hasattr(self, '_breach_thread') and self._breach_thread is not None and self._breach_thread.isRunning():
            self._breach_thread.requestInterruption()
            self._breach_thread.wait(3000)
        self.tab_weak.clear()
        self.tab_reused.clear()
        self.tab_breached.clear()
        self._breach_checked = False
        self.card_breached.findChildren(QLabel)[1].setText("--")
        self.ai_browser.hide()
        self.ai_label.hide()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.summary_widget.hide()
        self.tabs.hide()
        self.btn_check_breach.hide()
        self.network_warning.hide()
        QTimer.singleShot(100, self._start_check)

    def _run_breach_check(self):
        # 允许重新检测，覆盖上次结果

        results = self._results
        if results is None:
            return

        # Stop any existing thread
        if hasattr(self, '_breach_thread') and self._breach_thread is not None and self._breach_thread.isRunning():
            self._breach_thread.requestInterruption()
            self._breach_thread.wait(3000)

        self._breach_has_error = False
        self.btn_check_breach.setEnabled(False)
        self.btn_check_breach.setText("检测中...")

        # Collect passwords to check: weak + one from each reused group
        pwd_list = []
        pwd_to_ids = {}
        for item in results['weak']:
            pwd = item.get('password', '')
            if pwd:
                if pwd not in pwd_to_ids:
                    pwd_to_ids[pwd] = []
                    pwd_list.append(pwd)
                pwd_to_ids[pwd].append(item['account'].id)
        for group in results['reused_groups']:
            if group:
                pwd = group[0].get('password', '')
                if pwd:
                    if pwd not in pwd_to_ids:
                        pwd_to_ids[pwd] = []
                        pwd_list.append(pwd)
                    for g in group:
                        pwd_to_ids[pwd].append(g['account'].id)

        # Compute unique prefixes for accurate progress range
        prefixes = set()
        for pwd in pwd_list:
            sha1 = hashlib.sha1(pwd.encode()).hexdigest().upper()
            prefixes.add(sha1[:5])
        total_prefixes = len(prefixes)
        self.progress.setRange(0, total_prefixes)
        self.progress.setValue(0)
        self.progress.show()

        self._breach_thread = _BreachCheckThread(pwd_list, pwd_to_ids)
        self._breach_thread.progress.connect(self._on_breach_progress)
        self._breach_thread.finished_check.connect(self._on_breach_finished)
        self._breach_thread.error_msg.connect(self._on_breach_error)
        self._breach_thread.start()

    def _on_breach_progress(self, value):
        self.progress.setValue(value)

    def _on_breach_finished(self, breached_ids):
        if getattr(self, '_breach_has_error', False):
            return

        self._breach_checked = True
        self.progress.hide()
        self.btn_check_breach.setText("重新检测泄露密码")
        self.btn_check_breach.setEnabled(True)

        # 保存结果到数据库
        if hasattr(self.account_service.db, 'save_breach_results'):
            self.account_service.db.save_breach_results('accounts', breached_ids, getattr(self, '_breach_total', 0))

        results = self._results
        results['breached'] = breached_ids

        # Update card
        breached_count = len(breached_ids)
        self.card_breached.findChildren(QLabel)[1].setText(str(breached_count))
        self.tabs.setTabText(2, f"泄露密码 ({breached_count})")

        # Populate breach tab
        self.tab_breached.clear()
        if breached_count > 0:
            for bid in breached_ids:
                acc = self.account_service.get_account(bid)
                if acc:
                    text = f"{acc.app_name}  —  {acc.mask_username()}  —  {acc.category or '未分类'}"
                    item = QListWidgetItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, bid)
                    font = QFont()
                    font.setPointSize(11)
                    item.setFont(font)
                    item.setForeground(QColor(self._colors.accent_red))
                    self.tab_breached.addItem(item)
        else:
            msg = "未发现泄露密码"
            empty_item = QListWidgetItem(msg)
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setForeground(QColor(self._colors.text_tertiary))
            self.tab_breached.addItem(empty_item)

        self.ai_label.show()
        if hasattr(self, '_btn_get_ai'):
            self._btn_get_ai.show()
        self.ai_browser.hide()
        self.tabs.show()
        self.btn_check_breach.show()
        self.summary_widget.show()

    def _on_breach_error(self, msg):
        self._breach_has_error = True
        self._breach_checked = True
        self.progress.hide()
        self.btn_check_breach.setText("检测完成")
        self.btn_check_breach.setEnabled(True)
        self.network_warning.setText(msg)
        self.network_warning.show()

        results = self._results
        results['breached'] = []

        # Update breach tab
        self.tab_breached.clear()
        empty_item = QListWidgetItem("检测失败，请稍后重试")
        empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
        empty_item.setForeground(QColor(self._colors.text_tertiary))
        self.tab_breached.addItem(empty_item)

        # Update card
        self.card_breached.findChildren(QLabel)[1].setText("0")
        self.tabs.setTabText(2, "泄露密码 (0)")

        self.ai_label.show()
        if hasattr(self, '_btn_get_ai'):
            self._btn_get_ai.show()
        self.ai_browser.hide()
        self.tabs.show()
        self.btn_check_breach.show()
        self.summary_widget.show()

    def closeEvent(self, event):
        if hasattr(self, '_breach_thread') and self._breach_thread is not None and self._breach_thread.isRunning():
            self._breach_thread.requestInterruption()
            self._breach_thread.wait(3000)
        event.accept()

    def _show_ai_recommendations(self):
        """显示 AI 建议 — 有缓存则显示缓存，否则显示按钮"""
        if self._last_ai_html:
            self.ai_label.setText("AI 安全建议")
            self.ai_label.show()
            self.ai_browser.setHtml(self._last_ai_html)
            self.ai_browser.show()
            return
        
        if self.ai_assistant is None:
            self._show_ai_request_button()
            return
        
        from services.ai_service_manager import AIServiceManager
        if not AIServiceManager.instance().is_available():
            self._show_ai_request_button()
            return
        
        self._show_ai_request_button()
    
    def _show_ai_request_button(self):
        """显示获取 AI 建议的按钮"""
        self.ai_label.setText("AI 安全建议")
        self.ai_label.show()
        self.ai_browser.hide()
        
        c = self._colors
        # Remove old button if exists
        if hasattr(self, '_btn_get_ai'):
            self._btn_get_ai.deleteLater()
        
        self._btn_get_ai = QPushButton("获取 AI 安全建议")
        self._btn_get_ai.setFixedHeight(32)
        self._btn_get_ai.setStyleSheet(f"""
            QPushButton {{
                background-color: {c.accent_blue_bg};
                color: {c.accent_blue};
                border: 1px solid {c.accent_blue_light};
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {c.accent_blue}; color: white; }}
            QPushButton:disabled {{ background-color: {c.bg_tertiary}; color: {c.text_disabled}; }}
        """)
        self._btn_get_ai.clicked.connect(self._run_ai_thread)
        # Insert button in layout after ai_label (need to find the right position)
        idx = self.layout().indexOf(self.ai_label)
        if idx >= 0:
            self.layout().insertWidget(idx + 1, self._btn_get_ai)
        else:
            self.layout().addWidget(self._btn_get_ai)

    def _run_ai_thread(self):
        """在后台线程运行 AI 建议请求"""
        if hasattr(self, '_btn_get_ai'):
            self._btn_get_ai.setEnabled(False)
            self._btn_get_ai.setText("AI 生成中...")
        self.ai_label.setText("AI 安全建议（生成中...）")
        self.ai_browser.hide()
        
        self._ai_thread = AiRecommendationThread(self._results, self.ai_assistant)
        self._ai_thread.finished.connect(self._on_ai_done)
        self._ai_thread.start()
    
    def _on_ai_done(self, html):
        self._last_ai_html = html
        if hasattr(self, '_btn_get_ai'):
            self._btn_get_ai.hide()
        self.ai_label.setText("AI 安全建议")
        self.ai_browser.setHtml(html)
        self.ai_browser.show()

    def _show_generic_recommendations(self):
        self.ai_label.setText("安全建议（本地规则）")
        self.ai_label.show()
        self.ai_browser.show()

        html = """
        <ol>
        <li><b>修改弱密码：</b>为标记为"弱"或"中"的账号设置更复杂的密码，建议至少12位，包含大小写字母、数字和特殊字符。</li>
        <li><b>避免重复使用密码：</b>每个重要账号应使用独立密码，可以使用密码生成器创建高强度随机密码。</li>
        <li><b>定期更换密码：</b>建议每3-6个月更换一次重要账号的密码（如邮箱、金融类）。</li>
        <li><b>启用双因素认证：</b>对于支持2FA的服务，开启双因素认证增加安全层。</li>
        <li><b>使用密码管理器：</b>将所有密码集中存储在本软件中，避免使用记事本或浏览器记住密码。</li>
        </ol>
        """
        self.ai_browser.setHtml(html)

    def _markdown_to_html(self, text: str) -> str:
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        c = self._colors

        lines = text.strip().split('\n')
        html_lines = [f'<div style="color:{c.text_primary}; line-height:1.7;">']

        for line in lines:
            line = line.strip()
            if not line:
                html_lines.append('<br/>')
                continue
            # Bold
            import re
            line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
            html_lines.append(f'<p>{line}</p>')

        html_lines.append('</div>')
        return ''.join(html_lines)

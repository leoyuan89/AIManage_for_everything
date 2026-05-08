from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QFrame, QScrollArea, QProgressBar, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QFont, QColor

from core.theme_manager import ThemeManager
from core.password_strength import evaluate_password_strength
import hashlib
import logging

logger = logging.getLogger(__name__)


class DashboardWidget(QScrollArea):
    def __init__(self, account_service, url_service, vault='accounts', parent=None):
        super().__init__(parent)
        self.account_service = account_service
        self.url_service = url_service
        self.vault = vault
        self._cb = None
        self._health_results = None
        self._breach_running = False
        self._built = False
        
        # 读取本地泄露检测缓存（避免 set_vault 首次调用时 vault_changed=False 跳过重读）
        service = account_service if vault == 'accounts' else url_service
        if hasattr(service.db, 'get_breach_results'):
            cached = service.db.get_breach_results(vault)
            if cached:
                self._breach_checked = True
                self._breach_ids = cached.get('breached_ids', [])
            else:
                self._breach_checked = False
                self._breach_ids = []
        else:
            self._breach_checked = False
            self._breach_ids = []
        
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        
        self._container = QWidget()
        self._container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(20, 16, 20, 16)
        self._layout.setSpacing(12)
        self.setWidget(self._container)

        # 固定 health 容器，避免异步渲染时位置错乱
        self._health_container = QWidget()
        hl = QVBoxLayout(self._health_container)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)

    def set_vault(self, vault):
        vault_changed = vault != self.vault
        self.vault = vault
        if vault_changed:
            # 切换页面时保留 health_results，但读取本地泄露检测缓存
            self._breach_running = False
            self._built = False
            service = self.account_service if vault == 'accounts' else self.url_service
            if hasattr(service.db, 'get_breach_results'):
                cached = service.db.get_breach_results(vault)
                if cached:
                    self._breach_checked = True
                    self._breach_ids = cached.get('breached_ids', [])
                else:
                    self._breach_checked = False
                    self._breach_ids = []
        if not self._built:
            QTimer.singleShot(0, self._build)
        else:
            self.update()

    def set_callback(self, cb):
        self._cb = cb

    def refresh(self):
        self._built = False
        self._health_results = None
        # 保留本地泄露缓存，避免刷新页面后丢失
        # self._breach_checked = False
        # self._breach_ids = []
        self._build()

    def _action(self, act, data=None):
        if self._cb:
            self._cb(act, data)

    def _build(self):
        container = self._container
        lay = self._layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is self._health_container:
                self._clear_layout(w.layout())
                continue
            if w:
                w.hide()
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        
        c = ThemeManager.instance().colors
        
        vault = self.vault
        service = self.account_service if vault == 'accounts' else self.url_service
        accounts = service.get_all_accounts() if vault == 'accounts' else service.get_all_urls()
        
        vw = self.viewport().width()
        ww = vw - 40 if vw > 100 else 560

        # ===== summary cards =====
        cards_w = QWidget()
        cards_l = QHBoxLayout(cards_w)
        cards_l.setSpacing(16)
        cards_l.setContentsMargins(0, 0, 0, 0)
        
        all_acc = self.account_service.get_all_accounts()
        all_url = self.url_service.get_all_urls()
        
        recent_7 = self._get_recent_items(accounts, 7)
        
        card_specs = [
            ("总条目", len(accounts), c.accent_blue, None),
            ("密码库", len(all_acc), c.accent_green, None),
            ("网址库", len(all_url), c.accent_orange, None),
            ("本周新增", len(recent_7), c.accent_blue_dark, recent_7),
        ]
        
        for title, count, color, click_data in card_specs:
            card = QFrame()
            card.setFixedHeight(78)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.setStyleSheet(f"""
                QFrame {{
                    background: {c.bg_secondary};
                    border-radius: 10px;
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 12, 0, 12)
            cl.setSpacing(4)
            cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            n = QLabel(str(count))
            n.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
            n.setStyleSheet(f"color: {color};")
            n.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(n)
            
            t = QLabel(title)
            t.setStyleSheet(f"color: {c.text_secondary}; font-size: 12px;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(t)
            
            if click_data is not None:
                card.setCursor(Qt.CursorShape.PointingHandCursor)
                card.mousePressEvent = lambda e, items=click_data, color=color: self._show_recent_popup(items, color)
            
            cards_l.addWidget(card)
        lay.addWidget(cards_w)

        # ===== quick actions =====
        acts = QHBoxLayout(); acts.setSpacing(8)
        for txt, act in [("+ 添加账号", 'add'), ("📥 导入", 'import'), ("🔄 刷新", 'refresh')]:
            btn = QPushButton(txt); btn.setFixedHeight(30)
            btn.setStyleSheet(f"background:{c.bg_tertiary}; color:{c.text_primary}; border:1px solid {c.border_default}; border-radius:4px; padding:0 12px; font-size:12px;")
            btn.clicked.connect(lambda checked=False, a=act: self._action(a))
            acts.addWidget(btn)
        acts.addStretch(); lay.addLayout(acts)

        # ===== health check container =====
        if vault == 'accounts':
            lay.addWidget(self._health_container)

            if self._health_results is None:
                QTimer.singleShot(30, self._run_health_check)
            elif self._health_results:
                self._render_health(accounts, c, ww)

        # ===== recent items =====
        lay.addSpacing(8)
        lbl_recent = QLabel("最近添加")
        lbl_recent.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        lbl_recent.setStyleSheet(f"color:{c.text_primary};")
        lay.addWidget(lbl_recent)
        
        def sk(a):
            return getattr(a, 'created_at', '') or ''
        for acc in sorted(accounts, key=sk, reverse=True)[:8]:
            name = getattr(acc, 'app_name', '') or getattr(acc, 'title', '') or '?'
            cat = getattr(acc, 'category', '') or ''
            f = QFrame()
            f.setCursor(Qt.CursorShape.PointingHandCursor)
            f.setStyleSheet(f"QFrame {{ background:transparent; border-bottom:1px solid {c.border_light}; padding:3px 8px; }} QFrame:hover {{ background:{c.bg_hover}; }}")
            fl = QHBoxLayout(f)
            fl.setContentsMargins(4, 2, 4, 2)
            fl.addWidget(QLabel(name))
            fl.addStretch()
            fl.addWidget(QLabel(cat))
            f.mousePressEvent = lambda e, a=acc: self._action('edit', a)
            lay.addWidget(f)

        lay.addStretch()
        self._built = True

    def _run_health_check(self):
        accounts = self.account_service.get_all_accounts()
        results = {'weak': [], 'reused_groups': [], 'total': len(accounts)}
        
        for acc in accounts:
            try:
                pwd = acc.password or ''
                if not pwd: continue
                s = evaluate_password_strength(pwd)
                if s['label'] in ('弱', '中'):
                    results['weak'].append({'account': acc, 'strength': s})
            except Exception:
                logger.warning("密码强度评估失败", exc_info=True)
        
        pwd_map = {}
        for acc in accounts:
            try:
                pwd = acc.password or ''
                if not pwd: continue
                h = hashlib.sha256(pwd.encode()).hexdigest()
                pwd_map.setdefault(h, []).append(acc)
            except Exception:
                logger.warning("密码哈希计算失败", exc_info=True)
        for accs in pwd_map.values():
            if len(accs) > 1:
                results['reused_groups'].append(accs)
        
        # 保留已有的泄露检测结果（从 health_results 或 _breach_ids 恢复）
        if self._health_results and 'breached_ids' in self._health_results:
            results['breached_ids'] = self._health_results['breached_ids']
        elif self._breach_checked and self._breach_ids:
            results['breached_ids'] = self._breach_ids
        
        self._health_results = results
        self._render_health(accounts, ThemeManager.instance().colors, self.viewport().width() - 40)

    def _clear_layout(self, layout):
        """彻底清理 layout 中的所有 widget 和嵌套 layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _render_health(self, accounts, c, ww):
        # 先停止 timer、断开进度条引用，避免清理时访问已删除对象
        if hasattr(self, '_breach_refresh_timer') and self._breach_refresh_timer:
            self._breach_refresh_timer.stop()
            self._breach_refresh_timer = None
        self._breach_progress = None
        
        lay = self._health_container.layout()
        self._clear_layout(lay)
        results = self._health_results
        
        # ===== strength distribution =====
        lbl = QLabel("密码强度分布"); lbl.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color:{c.text_primary};")
        lay.addWidget(lbl)
        
        sc = {"弱": 0, "中": 0, "强": 0, "极强": 0}
        for acc in accounts:
            try:
                pwd = acc.password or ''
                if pwd: sc[evaluate_password_strength(pwd)['label']] += 1
            except Exception:
                logger.warning("密码强度分布统计失败", exc_info=True)
        
        cmap = {"弱": c.accent_red, "中": c.accent_orange, "强": c.accent_green, "极强": c.accent_blue}
        total = max(len(accounts), 1)
        
        for level in ("弱", "中", "强", "极强"):
            cnt = sc[level]
            row = QHBoxLayout(); row.setSpacing(6)
            ln = QLabel(level); ln.setFixedWidth(40); ln.setStyleSheet(f"color:{cmap[level]}; font-weight:bold; font-size:14px;"); row.addWidget(ln)
            
            bar_w = QWidget(); bar_w.setFixedHeight(24)
            ratio = cnt / total
            bar_w.setStyleSheet(f"background:{cmap[level]}; border-radius:6px;")
            bar_w.setMinimumWidth(max(int(ratio * (ww - 240)), 6))
            bar_w.setCursor(Qt.CursorShape.PointingHandCursor)
            bar_w.mousePressEvent = lambda e, l=level: self._action('strength', l)
            row.addWidget(bar_w)
            
            lc = QLabel(f"{cnt} 个"); lc.setStyleSheet(f"color:{c.text_secondary}; font-size:13px;")
            lc.setCursor(Qt.CursorShape.PointingHandCursor)
            lc.mousePressEvent = lambda e, l=level: self._action('strength', l)
            row.addWidget(lc); row.addStretch(); lay.addLayout(row)

        # ===== reused groups =====
        rc = len(results['reused_groups'])
        if rc > 0:
            lbl = QLabel(f"重复密码组 ({rc})"); lbl.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color:{c.text_primary};")
            lay.addWidget(lbl)
            
            for gi, group in enumerate(results['reused_groups'][:8]):
                names = [a.app_name for a in group]
                cnt_label = f"{len(group)} 个账号"
                # expandable group header — 整体背景色卡片
                is_dark = c.bg_primary == '#1E1E1E'
                if is_dark:
                    group_bg = c.accent_blue_bg
                    group_hover = c.accent_blue_bg_hover
                else:
                    group_bg = c.accent_orange_bg
                    group_hover = '#FDE8D8'

                header = QFrame()
                header.setCursor(Qt.CursorShape.PointingHandCursor)
                header.setStyleSheet(f"""
                    QFrame {{
                        background:{group_bg};
                        border-radius:6px;
                    }}
                """)
                hl = QHBoxLayout(header)
                hl.setContentsMargins(12, 10, 12, 10)
                hl.setSpacing(0)

                lbl_header = QLabel(f"🔗 {cnt_label}: {', '.join(names[:3])}{'...' if len(names)>3 else ''}")
                lbl_header.setStyleSheet(f"color:{c.text_primary}; font-size:12px;")
                lbl_header.setWordWrap(True)
                hl.addWidget(lbl_header)

                def _on_enter(event, h=header, bg=group_hover):
                    h.setStyleSheet(f"QFrame {{ background:{bg}; border-radius:6px; }}")
                def _on_leave(event, h=header, bg=group_bg):
                    h.setStyleSheet(f"QFrame {{ background:{bg}; border-radius:6px; }}")
                header.enterEvent = _on_enter
                header.leaveEvent = _on_leave

                # store group data
                header._group = group
                header._expanded = False
                header._container = None
                header.mousePressEvent = lambda e, h=header: self._toggle_group(h, c)
                lay.addWidget(header)

        # ===== breach check =====
        lay.addSpacing(4)
        lbl = QLabel("泄露密码检测"); lbl.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color:{c.text_primary};")
        lay.addWidget(lbl)
        
        if self._breach_running:
            btn_text = "检测中…"
        else:
            btn_text = "重新检测泄露密码（在线）" if self._breach_checked else "检测泄露密码（在线）"
        btn = QPushButton(btn_text)
        btn.setFixedHeight(30)
        btn.setStyleSheet(f"background:{c.accent_red_dark}; color:{c.text_on_dark}; border-radius:4px; font-weight:bold; padding:0 16px;")
        if self._breach_running:
            btn.setEnabled(False)
        btn.clicked.connect(self._run_breach_check)
        lay.addWidget(btn)

        if self._breach_running:
            self._breach_progress = QProgressBar()
            self._breach_progress.setFixedHeight(4)
            self._breach_progress.setTextVisible(False)
            total = getattr(self, '_breach_total', 0)
            self._breach_progress.setRange(0, max(total, 1))
            self._breach_progress.setValue(getattr(self, '_breach_progress_value', 0))
            lay.addWidget(self._breach_progress)
            if not hasattr(self, '_breach_refresh_timer') or self._breach_refresh_timer is None:
                self._breach_refresh_timer = QTimer(self)
                self._breach_refresh_timer.timeout.connect(self._refresh_breach_progress)
                self._breach_refresh_timer.start(200)
        else:
            if hasattr(self, '_breach_refresh_timer') and self._breach_refresh_timer:
                self._breach_refresh_timer.stop()
                self._breach_refresh_timer = None
        
        if self._breach_checked and not self._breach_running:
            breached = self._breach_ids or results.get('breached_ids', [])
            if breached:
                # 按密码 SHA256 哈希分组
                pwd_groups = {}
                for bid in breached:
                    acc = self.account_service.get_account(bid) if self.vault == 'accounts' else None
                    if acc and acc.password:
                        h = hashlib.sha256(acc.password.encode()).hexdigest()
                        pwd_groups.setdefault(h, []).append(acc)

                multi_groups = [g for g in pwd_groups.values() if len(g) >= 2]
                single_accounts = [g[0] for g in pwd_groups.values() if len(g) == 1]
                multi_groups.sort(key=lambda g: len(g), reverse=True)

                group_count = len(pwd_groups)
                total_count = sum(len(g) for g in pwd_groups.values())
                warn = QLabel(f"⚠ 检测到 {group_count} 组泄露密码（涉及 {total_count} 个账号）：")
                warn.setStyleSheet(f"color:{c.accent_red}; font-weight:bold; font-size:12px;")
                lay.addWidget(warn)

                is_dark = c.bg_primary == '#1E1E1E'
                if is_dark:
                    group_bg = c.accent_blue_bg
                    group_hover = c.accent_blue_bg_hover
                else:
                    group_bg = c.accent_orange_bg
                    group_hover = '#FDE8D8'

                # 多账号组：按个数降序
                for group in multi_groups:
                    header = QFrame()
                    header.setCursor(Qt.CursorShape.PointingHandCursor)
                    header.setStyleSheet(f"""
                        QFrame {{
                            background:{group_bg};
                            border-radius:6px;
                        }}
                    """)
                    hl = QHBoxLayout(header)
                    hl.setContentsMargins(12, 10, 12, 10)
                    hl.setSpacing(0)

                    lbl_header = QLabel(f"🔒 {len(group)} 个账号使用相同泄露密码")
                    lbl_header.setStyleSheet(f"color:{c.text_primary}; font-size:12px;")
                    lbl_header.setWordWrap(True)
                    hl.addWidget(lbl_header)

                    def _on_enter(event, h=header, bg=group_hover):
                        h.setStyleSheet(f"QFrame {{ background:{bg}; border-radius:6px; }}")
                    def _on_leave(event, h=header, bg=group_bg):
                        h.setStyleSheet(f"QFrame {{ background:{bg}; border-radius:6px; }}")
                    header.enterEvent = _on_enter
                    header.leaveEvent = _on_leave

                    header._group = group
                    header._expanded = False
                    header._container = None
                    header.mousePressEvent = lambda e, h=header: self._toggle_group(h, c)
                    lay.addWidget(header)

                # 单账号：合并为一组
                if single_accounts:
                    header = QFrame()
                    header.setCursor(Qt.CursorShape.PointingHandCursor)
                    header.setStyleSheet(f"""
                        QFrame {{
                            background:{group_bg};
                            border-radius:6px;
                        }}
                    """)
                    hl = QHBoxLayout(header)
                    hl.setContentsMargins(12, 10, 12, 10)
                    hl.setSpacing(0)

                    lbl_header = QLabel(f"🔓 {len(single_accounts)} 个非重复的泄露密码")
                    lbl_header.setStyleSheet(f"color:{c.text_primary}; font-size:12px;")
                    lbl_header.setWordWrap(True)
                    hl.addWidget(lbl_header)

                    def _on_enter_s(event, h=header, bg=group_hover):
                        h.setStyleSheet(f"QFrame {{ background:{bg}; border-radius:6px; }}")
                    def _on_leave_s(event, h=header, bg=group_bg):
                        h.setStyleSheet(f"QFrame {{ background:{bg}; border-radius:6px; }}")
                    header.enterEvent = _on_enter_s
                    header.leaveEvent = _on_leave_s

                    header._group = single_accounts
                    header._expanded = False
                    header._container = None
                    header.mousePressEvent = lambda e, h=header: self._toggle_group(h, c)
                    lay.addWidget(header)
            else:
                safe_lbl = QLabel("✓ 未发现泄露密码")
                safe_lbl.setStyleSheet(f"color:{c.accent_green}; font-size:12px; font-weight:bold;")
                lay.addWidget(safe_lbl)
        elif not self._breach_running:
            hint = QLabel("暂无检测记录，请点击按钮开始检测")
            hint.setStyleSheet(f"color:{c.text_tertiary}; font-size:11px;")
            lay.addWidget(hint)

    def _toggle_group(self, header, c):
        if header._expanded:
            if header._container:
                header._container.deleteLater()
                header._container = None
            header._expanded = False
            return
        
        header._expanded = True
        container = QWidget()
        vl = QVBoxLayout(container); vl.setContentsMargins(16, 4, 4, 4); vl.setSpacing(2)
        for acc in header._group:
            f = QFrame(); f.setCursor(Qt.CursorShape.PointingHandCursor)
            f.setStyleSheet(f"QFrame {{ background:transparent; border-bottom:1px solid {c.border_light}; padding:2px 6px; }} QFrame:hover {{ background:{c.bg_hover}; }}")
            fl = QHBoxLayout(f); fl.setContentsMargins(2, 1, 2, 1)
            fl.addWidget(QLabel(acc.app_name)); fl.addStretch()
            fl.addWidget(QLabel(acc.category or ''))
            f.mousePressEvent = lambda e, a=acc: self._action('edit', a)
            vl.addWidget(f)
        header._container = container
        # insert after header
        idx = self._health_container.layout().indexOf(header)
        if idx >= 0:
            self._health_container.layout().insertWidget(idx + 1, container)

    def _refresh_breach_progress(self):
        if hasattr(self, '_breach_progress') and self._breach_progress:
            self._breach_progress.setValue(getattr(self, '_breach_progress_value', 0))

    def _run_breach_check(self):
        if self._breach_running:
            return
        self._breach_running = True
        self._breach_checked = False
        self._breach_progress_value = 0
        self._build()
        
        results = self._health_results
        pwd_list = []
        pwd_to_ids = {}
        for item in results.get('weak', []):
            p = item['account'].password or ''
            if p and p not in pwd_list:
                pwd_list.append(p)
                pwd_to_ids[p] = [item['account'].id]
            elif p:
                pwd_to_ids[p].append(item['account'].id)
        for group in results.get('reused_groups', []):
            if group:
                p = group[0].password or ''
                if p and p not in pwd_list:
                    pwd_list.append(p)
                    ids = [a.id for a in group]
                    pwd_to_ids[p] = ids
                elif p:
                    if p in pwd_to_ids:
                        for a in group:
                            pwd_to_ids[p].append(a.id)
                    else:
                        pwd_to_ids[p] = [a.id for a in group]
        
        if not pwd_list:
            self._breach_running = False
            self._breach_checked = True
            self._breach_ids = []
            if self._health_results:
                self._health_results['breached_ids'] = []
            # 保存空结果到数据库
            service = self.account_service if self.vault == 'accounts' else self.url_service
            if hasattr(service.db, 'save_breach_results'):
                service.db.save_breach_results(self.vault, [], 0)
            self._build()
            return
        
        import hashlib as _hl
        unique_prefixes = len(set(_hl.sha1(p.encode()).hexdigest().upper()[:5] for p in pwd_list))
        self._breach_total = unique_prefixes
        self._breach_progress.setRange(0, unique_prefixes)
        self._breach_progress.setValue(0)
        self._breach_progress.show()

        self._breach_thread = _BreachCheckThread(pwd_list, pwd_to_ids)
        self._breach_thread.progress.connect(self._on_breach_progress)
        self._breach_thread.finished_check.connect(self._on_breach_finished)
        self._breach_thread.error_msg.connect(self._on_breach_error)
        self._breach_thread.start()

        self._breach_refresh_timer = QTimer(self)
        self._breach_refresh_timer.timeout.connect(self._refresh_breach_progress)
        self._breach_refresh_timer.start(200)

    def _on_breach_progress(self, value):
        self._breach_progress_value = value
    
    def _on_breach_error(self, msg):
        from PyQt6.QtWidgets import QMessageBox
        self._breach_running = False
        self._breach_checked = False
        if hasattr(self, '_breach_refresh_timer') and self._breach_refresh_timer:
            self._breach_refresh_timer.stop()
            self._breach_refresh_timer = None
        self._build()
        QMessageBox.warning(self, '检测失败', msg)

    def _on_breach_finished(self, breached_ids):
        self._breach_running = False
        self._breach_checked = True
        self._breach_ids = breached_ids
        if self._health_results:
            self._health_results['breached_ids'] = breached_ids
        self._breach_progress_value = 0
        if hasattr(self, '_breach_refresh_timer') and self._breach_refresh_timer:
            self._breach_refresh_timer.stop()
            self._breach_refresh_timer = None
        # 保存结果到数据库
        service = self.account_service if self.vault == 'accounts' else self.url_service
        if hasattr(service.db, 'save_breach_results'):
            service.db.save_breach_results(self.vault, breached_ids, getattr(self, '_breach_total', 0))
        self._build()

    def _get_recent_items(self, accounts, days):
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        recent = []
        for acc in accounts:
            created = getattr(acc, 'created_at', None)
            if isinstance(acc, dict): created = acc.get('created_at', None)
            if created:
                try:
                    if isinstance(created, str): created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if created and created >= cutoff: recent.append(acc)
                except Exception:
                    logger.debug("日期解析失败: %s", created, exc_info=True)
        return recent

    def _show_recent_popup(self, items, color):
        self._action('show_recent', {'items': items, 'color': color})


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
            return e  # 返回异常对象表示失败

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

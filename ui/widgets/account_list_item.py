from PyQt6.QtWidgets import QWidget, QCheckBox
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush

from core.theme_manager import ThemeManager
from core.clipboard import ClipboardManager

import logging

logger = logging.getLogger(__name__)

_clipboard_manager = ClipboardManager()


class AccountListItem(QWidget):
    """自定义账号列表项（自绘优化版）"""

    _COPY_BTNS = [("URL", "_on_copy_url"), ("ID", "_on_copy_username"), ("PW", "_on_copy_password")]

    def __init__(self, account, badges: list = None, selection_mode: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("accountListItem")
        self.account = account
        self.badges = badges or []
        self._compact_mode = False
        self._checkbox_clicked = False
        self._clipboard = _clipboard_manager
        self.on_check_changed = None
        self._selection_mode = selection_mode
        self._column_visible = {
            'icon': True, 'app_name': True, 'username': True,
            'strength': True, 'category': True, 'arrow': True, 'time': True,
        }
        self._hovered_btn = -1
        self._copy_btn_rects = []

        self.checkbox = QCheckBox(self)
        self.checkbox.setFixedSize(24, 24)
        self.checkbox.toggled.connect(self._on_check_state_changed)
        self.checkbox.setVisible(selection_mode)

        self.setFixedHeight(56)
        self.setMouseTracking(True)
        self._update_checkbox_style()

        self._strength_info = None
        if self.account.password:
            try:
                from core.password_strength import evaluate_password_strength
                result = evaluate_password_strength(self.account.password)
                self._strength_info = (result['label'], {
                    "弱": "accent_red", "中": "accent_orange",
                    "强": "accent_green", "极强": "accent_blue"
                }.get(result['label'], "text_tertiary"))
            except Exception:
                pass

        self._time_text = self._build_time_text()

    def _update_checkbox_style(self):
        colors = ThemeManager.instance().colors
        self.setStyleSheet(f"""
            #accountListItem QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 3px;
            }}
            #accountListItem QCheckBox::indicator:unchecked {{
                background-color: {colors.bg_primary};
                border: 2px solid {colors.text_secondary};
            }}
            #accountListItem QCheckBox::indicator:checked {{
                background-color: {colors.accent_blue};
                border: 2px solid {colors.accent_blue};
            }}
        """)

    def _build_time_text(self) -> str:
        time_parts = []
        created = self.account.created_at
        updated = self.account.updated_at
        if created:
            time_parts.append(f"创建:{self._format_db_time(created)}")
        if updated:
            time_parts.append(f"修改:{self._format_db_time(updated)}")
        return "  ".join(time_parts)

    def set_compact_mode(self, enabled: bool):
        if enabled == self._compact_mode:
            return
        self._compact_mode = enabled
        self.setFixedHeight(32 if enabled else 56)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = ThemeManager.instance().colors
        w = self.width()
        h = self.height()
        is_compact = self._compact_mode

        if self.autoFillBackground():
            painter.fillRect(self.rect(), QColor(colors.bg_primary))
        painter.setPen(QPen(QColor(colors.border_light), 1))
        painter.drawLine(0, h - 1, w, h - 1)

        x = 10
        if self._selection_mode:
            self.checkbox.move(x, (h - 24) // 2)
            self.checkbox.show()
            x += 34
        else:
            self.checkbox.hide()

        # 收藏星标
        if self.account.is_favorite:
            painter.setPen(QColor(colors.text_primary))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(x, (h - 16) // 2, 20, 16, Qt.AlignmentFlag.AlignCenter, "⭐")
            x += 20

        # 图标（紧凑模式隐藏）
        if self._column_visible.get('icon', True) and not is_compact:
            icon_color = self._generate_icon_color(self.account.app_name)
            painter.setBrush(QBrush(QColor(icon_color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(x, (h - 36) // 2, 36, 36)
            painter.setPen(QColor(colors.text_on_accent))
            painter.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
            painter.drawText(x, (h - 36) // 2, 36, 36, Qt.AlignmentFlag.AlignCenter, self._get_initial(self.account.app_name))
            x += 46

        text_x = x

        # 计算右侧固定占用宽度（顺序：分类 → 箭头 → 复制按钮）
        right_fixed = 10  # 右边距
        if not is_compact and not self._selection_mode:
            right_fixed += 3 * 28 + 10  # 3个按钮(26+2间距) + 间距
        if not is_compact and self._column_visible.get('arrow', True):
            right_fixed += 16 + 6
        if not is_compact and self._column_visible.get('category', True):
            cat_text = self.account.category or '其他'
            cat_fm = QFontMetrics(QFont("Microsoft YaHei", 10))
            right_fixed += cat_fm.horizontalAdvance(cat_text) + 12 + 6

        text_w = max(w - text_x - right_fixed, 20)

        if not is_compact:
            # === 第一行：标题 + 徽章 ===
            title_y = 8
            title_h = 18
            painter.setPen(QColor(colors.text_primary))
            title_font = QFont("Microsoft YaHei", 13)
            title_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(title_font)
            name = self.account.app_name or ''
            # 截断过长标题（使用 painter.fontMetrics 确保一致）
            fm_title = painter.fontMetrics()
            elided_name = fm_title.elidedText(name, Qt.TextElideMode.ElideRight, text_w)
            painter.drawText(text_x, title_y, text_w, title_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name)

            name_w = fm_title.horizontalAdvance(elided_name)
            badge_x = text_x + name_w + 6
            badge_y = title_y + 1

            for badge_text, badge_color in self.badges:
                if badge_x > text_x + text_w - 50:
                    break
                bfm = QFontMetrics(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
                bw = bfm.horizontalAdvance(badge_text) + 8
                bh = 14
                painter.setBrush(QBrush(QColor(badge_color + "33")))
                painter.setPen(QPen(QColor(badge_color), 1))
                painter.drawRoundedRect(badge_x, badge_y, bw, bh, 3, 3)
                painter.setPen(QColor(badge_color))
                painter.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
                painter.drawText(badge_x, badge_y, bw, bh, Qt.AlignmentFlag.AlignCenter, badge_text)
                badge_x += bw + 3

            # === 第二行：密码强度 + 账号 + 时间 ===
            sub_y = 30
            sub_h = 18
            sub_x = text_x
            sub_w = text_w

            # 密码强度放在第二行最前面，整齐对齐
            if self._strength_info and self._column_visible.get('strength', True):
                sl, sck = self._strength_info
                sc = getattr(colors, sck, colors.text_tertiary)
                sfm = QFontMetrics(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
                sw = sfm.horizontalAdvance(sl) + 8
                sh = 14
                painter.setBrush(QBrush(QColor(sc + "33")))
                painter.setPen(QPen(QColor(sc), 1))
                painter.drawRoundedRect(sub_x, sub_y + 2, sw, sh, 3, 3)
                painter.setPen(QColor(sc))
                painter.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
                painter.drawText(sub_x, sub_y + 2, sw, sh, Qt.AlignmentFlag.AlignCenter, sl)
                sub_x += sw + 6
                sub_w -= sw + 6

            painter.setPen(QColor(colors.text_tertiary))
            sub_font = QFont("Microsoft YaHei", 10)
            painter.setFont(sub_font)
            username = self.account.mask_username() or ''
            fm_sub = painter.fontMetrics()
            uname_max_w = min(fm_sub.horizontalAdvance(username) + 2, sub_w // 2)
            elided_username = fm_sub.elidedText(username, Qt.TextElideMode.ElideRight, uname_max_w)
            painter.drawText(sub_x, sub_y, uname_max_w, sub_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_username)

            if self._time_text and self._column_visible.get('time', True):
                uname_display_w = fm_sub.horizontalAdvance(elided_username)
                time_x = sub_x + uname_display_w + 10
                time_w = sub_w - uname_display_w - 10
                if time_w > 20:
                    painter.setPen(QColor(colors.text_disabled))
                    painter.setFont(QFont("Microsoft YaHei", 9))
                    painter.drawText(time_x, sub_y, time_w, sub_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._time_text)
        else:
            # === 紧凑模式 ===
            painter.setPen(QColor(colors.text_primary))
            title_font = QFont("Microsoft YaHei", 12)
            title_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(title_font)
            fm_title = QFontMetrics(title_font)
            elided_name = fm_title.elidedText(self.account.app_name or '', Qt.TextElideMode.ElideRight, text_w)
            painter.drawText(text_x, 4, text_w, 14, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name)

            painter.setPen(QColor(colors.text_tertiary))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(text_x, 17, text_w, 14, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.account.mask_username() or '')

        # === 右侧元素（正常模式，顺序：分类 → 箭头 → 复制按钮）===
        if not is_compact:
            rx = w - 10

            # 复制按钮（最右侧）
            self._copy_btn_rects = []
            if not self._selection_mode:
                btn_w, btn_h = 26, 26
                btn_spacing = 2
                for i, (label, _) in enumerate(self._COPY_BTNS):
                    bx = rx - (3 - i) * (btn_w + btn_spacing)
                    by = (h - btn_h) // 2
                    rect = QRect(bx, by, btn_w, btn_h)
                    self._copy_btn_rects.append(rect)

                    is_hovered = (i == self._hovered_btn)
                    if is_hovered:
                        painter.setBrush(QBrush(QColor(colors.accent_blue_bg)))
                        painter.setPen(QPen(QColor(colors.accent_blue), 1))
                    else:
                        painter.setBrush(QBrush(QColor(colors.bg_secondary)))
                        painter.setPen(QPen(QColor(colors.border_light), 1))
                    painter.drawRoundedRect(rect, 6, 6)

                    painter.setPen(QColor(colors.accent_blue if is_hovered else colors.text_tertiary))
                    painter.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
                rx -= 3 * (btn_w + btn_spacing) + 10

            # 箭头 ›
            if self._column_visible.get('arrow', True):
                rx -= 16
                painter.setPen(QColor(colors.text_disabled))
                painter.setFont(QFont("Microsoft YaHei", 16))
                painter.drawText(rx, (h - 20) // 2, 16, 20, Qt.AlignmentFlag.AlignCenter, "›")
                rx -= 6

            # 分类 pill（缩小）
            if self._column_visible.get('category', True):
                cat_text = self.account.category or '其他'
                cat_fm = QFontMetrics(QFont("Microsoft YaHei", 10))
                cw = cat_fm.horizontalAdvance(cat_text) + 12
                ch = 16
                rx -= cw
                painter.setBrush(QBrush(QColor(colors.bg_secondary)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(rx, (h - ch) // 2, cw, ch, 8, 8)
                painter.setPen(QColor(colors.text_secondary))
                painter.setFont(QFont("Microsoft YaHei", 10))
                painter.drawText(rx, (h - ch) // 2, cw, ch, Qt.AlignmentFlag.AlignCenter, cat_text)

        painter.end()

    def mouseMoveEvent(self, event):
        if self._selection_mode:
            # Ctrl+拖动多选支持
            from PyQt6.QtWidgets import QApplication
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                window = self.window()
                if window and getattr(window, '_drag_selecting', False) and hasattr(window, '_on_drag_select_move'):
                    global_pos = self.mapToGlobal(event.pos())
                    viewport_pos = window.account_list.viewport().mapFromGlobal(global_pos)
                    window._on_drag_select_move(viewport_pos)
            return super().mouseMoveEvent(event)
        if self._compact_mode:
            return super().mouseMoveEvent(event)
        prev = self._hovered_btn
        self._hovered_btn = -1
        for i, rect in enumerate(self._copy_btn_rects):
            if rect.contains(event.pos()):
                self._hovered_btn = i
                break
        if prev != self._hovered_btn:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered_btn != -1:
            self._hovered_btn = -1
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._selection_mode:
            window = self.window()
            if window and getattr(window, '_drag_selecting', False):
                window._drag_selecting = False
                window._drag_in_progress = False
                window._drag_checked_ids.clear()
                return
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        if self._compact_mode:
            return super().mousePressEvent(event)
        if self._selection_mode:
            # Ctrl+拖动多选支持
            from PyQt6.QtWidgets import QApplication
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                window = self.window()
                if window and hasattr(window, '_on_drag_select_move'):
                    window._drag_selecting = True
                    window._drag_in_progress = True
                    window._drag_checked_ids.clear()
                    global_pos = self.mapToGlobal(event.pos())
                    viewport_pos = window.account_list.viewport().mapFromGlobal(global_pos)
                    window._on_drag_select_move(viewport_pos)
                return
            return super().mousePressEvent(event)
        for i, (label, handler) in enumerate(self._COPY_BTNS):
            if i < len(self._copy_btn_rects) and self._copy_btn_rects[i].contains(event.pos()):
                getattr(self, handler)()
                return
        super().mousePressEvent(event)

    def set_selection_mode(self, enabled: bool):
        self._selection_mode = enabled
        self.checkbox.setVisible(enabled)
        self.update()

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool):
        self._checkbox_clicked = False
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)

    def _on_check_state_changed(self, state):
        self._checkbox_clicked = True
        if self.on_check_changed:
            self.on_check_changed(bool(state))

    def set_column_visible(self, column, visible):
        if column in self._column_visible:
            self._column_visible[column] = visible
            self.update()

    def _on_copy_url(self):
        try:
            url = self.account.url or ''
            if url:
                self._clipboard.copy_text(url)
                self._show_copy_toast("网址")
        except Exception as e:
            logger.warning("复制网址失败: %s", e)

    def _on_copy_username(self):
        try:
            username = self.account.username or ''
            if username:
                self._clipboard.copy_text(username)
                self._show_copy_toast("账号")
        except Exception as e:
            logger.warning("复制账号失败: %s", e)

    def _on_copy_password(self):
        try:
            password = self.account.password or ''
            if password:
                self._clipboard.copy_text(password, is_password=True)
                self._show_copy_toast("密码", is_password=True)
        except Exception as e:
            logger.warning("复制密码失败: %s", e)

    def _show_copy_toast(self, label, is_password=False):
        try:
            parent = self.window()
            if parent and hasattr(parent, 'show_copy_toast'):
                parent.show_copy_toast(f"{label}已复制", is_password=is_password)
        except Exception as e:
            logger.debug("显示复制提示失败: %s", e)

    def on_theme_changed(self):
        self._update_checkbox_style()
        self.update()

    @staticmethod
    def _format_db_time(value) -> str:
        if not value:
            return ''
        if hasattr(value, 'strftime'):
            try:
                from datetime import timezone
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone().strftime('%Y-%m-%d')
            except Exception:
                return value.strftime('%Y-%m-%d')
        try:
            from datetime import datetime, timezone
            s = str(value).replace('Z', '+00:00')
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.astimezone().strftime('%Y-%m-%d')
        except Exception:
            return str(value)[:10]

    @staticmethod
    def _generate_icon_color(text: str) -> str:
        colors = ['#E57373', '#F06292', '#BA68C8', '#9575CD', '#7986CB', '#64B5F6', '#4FC3F7', '#4DD0E1', '#4DB6AC', '#81C784', '#AED581', '#FFD54F', '#FFB74D', '#FF8A65', '#A1887F']
        hash_val = sum(ord(c) for c in text) if text else 0
        return colors[hash_val % len(colors)]

    @staticmethod
    def _get_initial(text: str) -> str:
        if not text:
            return '?'
        return text[0].upper()

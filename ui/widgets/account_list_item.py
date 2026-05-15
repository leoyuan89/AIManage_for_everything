from PyQt6.QtWidgets import QWidget, QCheckBox
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush

from core.theme_manager import ThemeManager
from core.clipboard import ClipboardManager

import json
import logging
import time
import math

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
            'icon': True, 'app_name': True, 'strength': True,
            'category': True, 'arrow': True, 'time': True,
            'tags': True, 'remark': True, 'ai_remark': True,
        }
        self._hovered_btn = -1
        self._copy_btn_rects = []
        self._press_handled = False  # True when mousePressEvent consumed the event (copy btn / checkbox)
        self._flash_active = False
        self._flash_timer = None
        self._flash_start_time = 0
        self._flash_duration = 2.0
        self._layout_margin = 10

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
            #accountListItem {{
                background-color: transparent;
                border: none;
            }}
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

    def _get_time_lines(self):
        """返回创建时间和修改时间作为独立的行，用于垂直排列"""
        create_line = ""
        update_line = ""
        if self.account.created_at:
            create_line = f"创建:{self._format_db_time(self.account.created_at)}"
        if self.account.updated_at:
            update_line = f"修改:{self._format_db_time(self.account.updated_at)}"
        return create_line, update_line

    def start_flash(self, duration_sec: float = 2.0, interval_ms: int = 60):
        """启动呼吸灯闪烁效果"""
        self._flash_active = True
        self._flash_start_time = time.time()
        self._flash_duration = duration_sec
        if self._flash_timer is None:
            self._flash_timer = QTimer(self)
            self._flash_timer.timeout.connect(self._on_flash_tick)
        self._flash_timer.start(interval_ms)
        self.update()

    def stop_flash(self):
        """停止呼吸灯闪烁"""
        self._flash_active = False
        if self._flash_timer:
            self._flash_timer.stop()
        self.update()

    def _on_flash_tick(self):
        """闪烁定时器回调"""
        self.update()
        if time.time() - self._flash_start_time > self._flash_duration:
            self._flash_active = False
            self._flash_timer.stop()
            self.update()

    def set_compact_mode(self, enabled: bool):
        if enabled == self._compact_mode:
            return
        self._compact_mode = enabled
        self.setFixedHeight(35 if enabled else 56)
        self.update()

    def _update_checkbox_geometry(self):
        """更新复选框位置和可见性（禁止在 paintEvent 中调用）"""
        if not hasattr(self, 'checkbox'):
            return
        if self._selection_mode:
            self.checkbox.show()
            h = self.height()
            self.checkbox.move(self._layout_margin, (h - 24) // 2)
        else:
            self.checkbox.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_checkbox_geometry()

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

        x = self._layout_margin
        if self._selection_mode:
            x += 34

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

        # 计算右侧固定占用宽度（顺序：分类 → 时间(垂直) → 箭头 → 复制按钮）
        right_fixed = 10  # 右边距
        if not is_compact and not self._selection_mode:
            right_fixed += 3 * 28 + 10  # 3个按钮(26+2间距) + 间距
        if not is_compact and self._column_visible.get('arrow', True):
            right_fixed += 16 + 6
        if not is_compact and self._column_visible.get('time', True):
            create_line, update_line = self._get_time_lines()
            if create_line or update_line:
                time_fm = QFontMetrics(QFont("Microsoft YaHei", 9))
                time_w = 0
                if create_line:
                    time_w = max(time_w, time_fm.horizontalAdvance(create_line))
                if update_line:
                    time_w = max(time_w, time_fm.horizontalAdvance(update_line))
                if time_w > 0:
                    right_fixed += time_w + 8
        if self._column_visible.get('category', True):
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

            # 标签 pills
            if self._column_visible.get('tags', True):
                tags = []
                try:
                    tags = json.loads(self.account.tags or '[]')
                except Exception:
                    pass
                if tags:
                    tag_font = QFont("Microsoft YaHei", 9, QFont.Weight.Bold)
                    tag_fm = QFontMetrics(tag_font)
                    th = 14
                    max_tag_x = text_x + text_w
                    for idx, tag in enumerate(tags[:3]):
                        tag_text = str(tag)
                        tw = tag_fm.horizontalAdvance(tag_text) + 12
                        if badge_x + tw > max_tag_x:
                            break
                        painter.setBrush(QBrush(QColor(colors.bg_secondary)))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawRoundedRect(badge_x, badge_y, tw, th, 7, 7)
                        painter.setPen(QColor(colors.text_secondary))
                        painter.setFont(tag_font)
                        painter.drawText(badge_x, badge_y, tw, th, Qt.AlignmentFlag.AlignCenter, tag_text)
                        badge_x += tw + 3
                    if len(tags) > 3:
                        extra_text = f"+{len(tags) - 3}"
                        tw = tag_fm.horizontalAdvance(extra_text) + 12
                        if badge_x + tw <= max_tag_x:
                            painter.setBrush(QBrush(QColor(colors.bg_secondary)))
                            painter.setPen(Qt.PenStyle.NoPen)
                            painter.drawRoundedRect(badge_x, badge_y, tw, th, 7, 7)
                            painter.setPen(QColor(colors.text_secondary))
                            painter.setFont(tag_font)
                            painter.drawText(badge_x, badge_y, tw, th, Qt.AlignmentFlag.AlignCenter, extra_text)

            # === 第二行：密码强度 + remark/ai_remark + 时间 ===
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

            # 脱敏账号（始终显示）
            painter.setPen(QColor(colors.text_tertiary))
            sub_font = QFont("Microsoft YaHei", 10)
            painter.setFont(sub_font)
            username = self.account.mask_username() or ''
            fm_sub = painter.fontMetrics()
            uname_max_w = min(fm_sub.horizontalAdvance(username) + 2, sub_w // 3)
            elided_username = fm_sub.elidedText(username, Qt.TextElideMode.ElideRight, uname_max_w)
            painter.drawText(sub_x, sub_y, uname_max_w, sub_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_username)
            sub_x += fm_sub.horizontalAdvance(elided_username) + 10
            sub_w -= fm_sub.horizontalAdvance(elided_username) + 10

            show_remark = self._column_visible.get('remark', True) and (self.account.remark or '').strip()
            show_ai = self._column_visible.get('ai_remark', True) and (self.account.ai_remark or '').strip()

            # remark / ai_remark 可用宽度（时间已移到右侧固定区域，不再占用第二行空间）
            remark_max_w = sub_w

            if show_remark or show_ai:
                painter.setFont(QFont("Microsoft YaHei", 10))
                fm_sub = painter.fontMetrics()
                draw_x = sub_x

                def _limit_chars(text, max_len=15):
                    if len(text) <= max_len:
                        return text
                    return text[:max_len] + '...'

                if show_remark:
                    raw_remark = (self.account.remark or '').strip().replace('\n', ' ')
                    remark_text = f"💬 {_limit_chars(raw_remark)}"
                    painter.setPen(QColor(colors.text_secondary))
                    rw = min(fm_sub.horizontalAdvance(remark_text), remark_max_w)
                    painter.drawText(draw_x, sub_y, rw, sub_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, remark_text)
                    draw_x += fm_sub.horizontalAdvance(remark_text)

                if show_remark and show_ai:
                    sep = " | "
                    sep_w = fm_sub.horizontalAdvance(sep)
                    if draw_x + sep_w <= sub_x + remark_max_w:
                        painter.setPen(QColor(colors.text_disabled))
                        painter.drawText(draw_x, sub_y, sep_w, sub_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sep)
                        draw_x += sep_w

                if show_ai:
                    raw_ai = (self.account.ai_remark or '').strip().replace('\n', ' ')
                    ai_text = f"🤖 {_limit_chars(raw_ai)}"
                    painter.setPen(QColor(colors.accent_blue))
                    remaining = max(sub_x + remark_max_w - draw_x, 0)
                    aw = min(fm_sub.horizontalAdvance(ai_text), remaining)
                    painter.drawText(draw_x, sub_y, aw, sub_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ai_text)
                    draw_x += fm_sub.horizontalAdvance(ai_text)

        else:
            # === 紧凑模式 ===
            painter.setPen(QColor(colors.text_primary))
            title_font = QFont("Microsoft YaHei", 11)
            title_font.setWeight(QFont.Weight.Medium)
            painter.setFont(title_font)
            fm_title = painter.fontMetrics()
            elided_name = fm_title.elidedText(self.account.app_name or '', Qt.TextElideMode.ElideRight, text_w)
            painter.drawText(text_x, 2, text_w, 15, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name)

            # 紧凑模式第二行：脱敏账号 + remark/ai_remark
            painter.setPen(QColor(colors.text_tertiary))
            painter.setFont(QFont("Microsoft YaHei", 9))
            fm_sub = painter.fontMetrics()
            username = self.account.mask_username() or ''
            elided_username = fm_sub.elidedText(username, Qt.TextElideMode.ElideRight, text_w // 3)
            uname_w = fm_sub.horizontalAdvance(elided_username)
            painter.drawText(text_x, 17, uname_w + 2, 13, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_username)

            draw_x = text_x + uname_w + 8
            remaining = text_w - uname_w - 8

            show_remark = self._column_visible.get('remark', True) and (self.account.remark or '').strip()
            show_ai = self._column_visible.get('ai_remark', True) and (self.account.ai_remark or '').strip()

            def _limit_chars(text, max_len=12):
                if len(text) <= max_len:
                    return text
                return text[:max_len] + '...'

            if show_remark or show_ai:
                if show_remark:
                    raw_remark = (self.account.remark or '').strip().replace('\n', ' ')
                    remark_text = f"💬 {_limit_chars(raw_remark)}"
                    painter.setPen(QColor(colors.text_secondary))
                    rw = min(fm_sub.horizontalAdvance(remark_text), remaining)
                    painter.drawText(draw_x, 17, rw, 13, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, remark_text)
                    draw_x += fm_sub.horizontalAdvance(remark_text)
                    remaining -= fm_sub.horizontalAdvance(remark_text)

                if show_remark and show_ai:
                    sep = " | "
                    sep_w = fm_sub.horizontalAdvance(sep)
                    if remaining > sep_w:
                        painter.setPen(QColor(colors.text_disabled))
                        painter.drawText(draw_x, 17, sep_w, 13, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sep)
                        draw_x += sep_w
                        remaining -= sep_w

                if show_ai:
                    raw_ai = (self.account.ai_remark or '').strip().replace('\n', ' ')
                    ai_text = f"🤖 {_limit_chars(raw_ai)}"
                    painter.setPen(QColor(colors.accent_blue))
                    aw = min(fm_sub.horizontalAdvance(ai_text), max(remaining, 0))
                    painter.drawText(draw_x, 17, aw, 13, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ai_text)

        # === 右侧元素（正常模式，顺序：分类 → 时间(垂直) → 箭头 → 复制按钮）===
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

            # 时间（垂直排列：创建在上，修改在下）
            if self._column_visible.get('time', True):
                create_line, update_line = self._get_time_lines()
                if create_line or update_line:
                    time_fm = QFontMetrics(QFont("Microsoft YaHei", 9))
                    time_w = 0
                    if create_line:
                        time_w = max(time_w, time_fm.horizontalAdvance(create_line))
                    if update_line:
                        time_w = max(time_w, time_fm.horizontalAdvance(update_line))
                    if time_w > 0:
                        rx -= time_w + 6
                        painter.setPen(QColor(colors.text_disabled))
                        painter.setFont(QFont("Microsoft YaHei", 9))
                        line_h = 11
                        gap = 2
                        total_h = line_h * 2 + gap
                        time_y = (h - total_h) // 2
                        if create_line:
                            painter.drawText(rx, time_y, time_w, line_h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, create_line)
                            time_y += line_h + gap
                        if update_line:
                            painter.drawText(rx, time_y, time_w, line_h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, update_line)

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

        # 紧凑模式也显示分类
        if is_compact and self._column_visible.get('category', True):
            cat_text = self.account.category or '其他'
            cat_fm = QFontMetrics(QFont("Microsoft YaHei", 10))
            cw = cat_fm.horizontalAdvance(cat_text) + 12
            ch = 14
            rx = w - 10 - cw
            painter.setBrush(QBrush(QColor(colors.bg_secondary)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rx, (h - ch) // 2, cw, ch, 8, 8)
            painter.setPen(QColor(colors.text_secondary))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(rx, (h - ch) // 2, cw, ch, Qt.AlignmentFlag.AlignCenter, cat_text)

        # === 呼吸灯闪烁效果 ===
        if self._flash_active:
            elapsed = time.time() - self._flash_start_time
            if elapsed > self._flash_duration:
                self._flash_active = False
            else:
                # 正弦波呼吸：2秒内柔和闪烁2次，alpha 0-40
                alpha = int(abs(math.sin(elapsed * 2 * math.pi)) * 40)
                flash_color = QColor(colors.accent_blue)
                flash_color.setAlpha(alpha)
                painter.fillRect(self.rect(), flash_color)


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
        if self._press_handled:
            self._press_handled = False
            return  # consume release so QListWidget.itemClicked is NOT emitted
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
                self._press_handled = True
                getattr(self, handler)()
                return
        self._press_handled = False
        super().mousePressEvent(event)

    def set_selection_mode(self, enabled: bool):
        self._selection_mode = enabled
        self._update_checkbox_geometry()
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

from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication
from PyQt6.QtCore import Qt, QRect, QSize, QModelIndex, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QColor, QPainter

from core.theme_manager import ThemeManager


class AccountItemDelegate(QStyledItemDelegate):
    """账号/网址列表项绘制委托"""

    copy_url_requested = pyqtSignal(object)
    copy_username_requested = pyqtSignal(object)
    copy_password_requested = pyqtSignal(object)
    checkbox_toggled = pyqtSignal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._compact_mode = False
        self._selection_mode = False
        self._column_config: dict = {}
        self._selected_ids: set = set()
        # 缓存最近一次绘制的交互元素位置，用于 hit_test
        self._hit_rects: dict = {}

    def set_compact_mode(self, enabled: bool):
        if self._compact_mode != enabled:
            self._compact_mode = enabled
            self._hit_rects.clear()

    def set_selection_mode(self, enabled: bool):
        if self._selection_mode != enabled:
            self._selection_mode = enabled
            self._hit_rects.clear()

    def set_column_visible(self, key: str, visible: bool):
        if self._column_config.get(key) != visible:
            self._column_config[key] = visible
            self._hit_rects.clear()

    def set_selected_ids(self, ids: set):
        self._selected_ids = set(ids)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        height = 32 if self._compact_mode else 56
        return QSize(option.rect.width(), height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        if isinstance(data, dict) and data.get("item_type") == "header":
            self._paint_header(painter, option, data)
            return

        self._paint_item(painter, option, index, data)

    def _paint_header(self, painter: QPainter, option: QStyleOptionViewItem, data: dict):
        colors = ThemeManager.instance().colors
        rect = option.rect

        bg_color = QColor(data.get("background", colors.bg_secondary))
        fg_color = QColor(data.get("foreground", colors.text_primary))

        painter.fillRect(rect, bg_color)

        text = data.get("text", "")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)
        painter.setPen(fg_color)
        painter.drawText(
            rect.adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _paint_item(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, data: dict):
        colors = ThemeManager.instance().colors
        rect = option.rect
        is_compact = self._compact_mode
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # 背景色
        highlight = data.get("highlight")
        if highlight == "matched":
            bg_color = QColor("#BBDEFB") if not ThemeManager.instance().is_dark else QColor("#2A3D55")
        elif highlight == "unmatched":
            bg_color = QColor(colors.bg_primary)
        elif is_selected:
            bg_color = QColor(colors.accent_blue_bg)
        else:
            bg_color = QColor(colors.bg_primary)

        painter.fillRect(rect, bg_color)

        # 底部分隔线
        painter.setPen(QColor(colors.border_light))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        obj = data.get("data")
        if not obj:
            return

        item_type = data.get("item_type", "account")
        is_fav = getattr(obj, "is_favorite", False) or (
            obj.get("is_favorite", False) if isinstance(obj, dict) else False
        )
        title = getattr(obj, "app_name", "") or (
            obj.get("title", "") if isinstance(obj, dict) else ""
        )

        # 布局计算
        left = rect.left() + (6 if is_compact else 10)
        right = rect.right() - (6 if is_compact else 10)
        center_y = rect.top() + rect.height() // 2

        hit_rects = {}

        # 复选框
        checkbox_rect = None
        if self._selection_mode:
            cb_size = 20
            checkbox_rect = QRect(left, center_y - cb_size // 2, cb_size, cb_size)
            self._draw_checkbox(painter, checkbox_rect, self._is_item_checked(obj))
            hit_rects["checkbox"] = checkbox_rect
            left += cb_size + 8

        # 收藏星标
        if is_fav:
            star_rect = QRect(left, center_y - 8, 16, 16)
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "⭐")
            left += 20

        # 圆形图标
        icon_rect = None
        if not is_compact and self._is_column_visible("icon"):
            icon_size = 36
            icon_rect = QRect(left, center_y - icon_size // 2, icon_size, icon_size)
            color = self._generate_icon_color(title)
            self._draw_icon(painter, icon_rect, title, color)
            left += icon_size + 10

        # 右侧元素占位计算
        copy_rects = {}
        if not self._selection_mode:
            if item_type == "account" and self._is_column_visible("copy", True):
                btn_size = 26
                btn_spacing = 4
                total_width = 3 * btn_size + 2 * btn_spacing
                btn_x = right - total_width
                copy_rects["url"] = QRect(
                    btn_x, center_y - btn_size // 2, btn_size, btn_size
                )
                copy_rects["username"] = QRect(
                    btn_x + btn_size + btn_spacing,
                    center_y - btn_size // 2,
                    btn_size,
                    btn_size,
                )
                copy_rects["password"] = QRect(
                    btn_x + 2 * (btn_size + btn_spacing),
                    center_y - btn_size // 2,
                    btn_size,
                    btn_size,
                )
                right = btn_x - 8
            elif item_type == "url" and self._is_column_visible("copy", True):
                btn_size = 26
                btn_x = right - btn_size
                copy_rects["url"] = QRect(
                    btn_x, center_y - btn_size // 2, btn_size, btn_size
                )
                right = btn_x - 8

        # 右箭头
        arrow_rect = None
        if self._is_column_visible("arrow") and not is_compact:
            arrow_rect = QRect(right - 12, center_y - 10, 12, 20)
            right -= 16

        # 分类标签
        category_rect = None
        category = None
        if self._is_column_visible("category") and not is_compact:
            category = (
                getattr(obj, "category", "")
                or (obj.get("category", "") if isinstance(obj, dict) else "")
                or "其他"
            )
            cat_font = QFont()
            cat_font.setPixelSize(11)
            cat_fm = QFontMetrics(cat_font)
            cat_width = cat_fm.horizontalAdvance(category) + 16
            category_rect = QRect(right - cat_width, center_y - 10, cat_width, 20)
            right -= cat_width + 8

        # 标题区域
        title_font = QFont()
        title_font.setPixelSize(13 if is_compact else 15)
        title_font.setWeight(QFont.Weight.Medium if is_compact else QFont.Weight.DemiBold)

        title_y = center_y - 2 if is_compact else rect.top() + 10
        available_width = right - left - 8

        # 徽章
        badges = data.get("badges", [])
        badge_data = []
        badge_total_width = 0
        if not is_compact:
            badge_font = QFont()
            badge_font.setPixelSize(9)
            badge_font.setWeight(QFont.Weight.Bold)
            badge_fm = QFontMetrics(badge_font)
            badge_x = left
            for badge_text, badge_color in badges:
                bw = badge_fm.horizontalAdvance(badge_text) + 12
                badge_data.append(
                    (badge_text, badge_color, QRect(badge_x, title_y + 2, bw, 16))
                )
                badge_x += bw + 4
                badge_total_width += bw + 4

        # 密码强度徽章
        strength_data = None
        if item_type == "account" and self._is_column_visible("strength") and not is_compact:
            password = getattr(obj, "password", "") or ""
            if password:
                try:
                    from core.password_strength import evaluate_password_strength

                    result = evaluate_password_strength(password)
                    level = result["label"]
                    level_colors = {
                        "弱": colors.accent_red,
                        "中": colors.accent_orange,
                        "强": colors.accent_green,
                        "极强": colors.accent_blue,
                    }
                    level_color = level_colors.get(level, colors.text_tertiary)
                    badge_font = QFont()
                    badge_font.setPixelSize(9)
                    badge_font.setWeight(QFont.Weight.Bold)
                    badge_fm = QFontMetrics(badge_font)
                    bw = badge_fm.horizontalAdvance(level) + 12
                    strength_data = (
                        level,
                        level_color,
                        QRect(badge_x, title_y + 2, bw, 16),
                    )
                    badge_total_width += bw + 4
                except Exception:
                    pass

        # 绘制标题
        title_width = max(available_width - badge_total_width - 4, 0)
        title_rect = QRect(left, title_y, title_width, 20)
        painter.setFont(title_font)
        painter.setPen(QColor(colors.text_primary))
        elided = painter.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, title_width
        )
        painter.drawText(
            title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided
        )

        # 绘制徽章
        for badge_text, badge_color, badge_rect in badge_data:
            painter.fillRect(badge_rect, QColor(badge_color + "20"))
            painter.setPen(QColor(badge_color))
            painter.drawRoundedRect(badge_rect, 4, 4)
            painter.setFont(badge_font)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # 绘制强度徽章
        if strength_data:
            level, level_color, strength_rect = strength_data
            painter.fillRect(strength_rect, QColor(level_color + "20"))
            painter.setPen(QColor(level_color))
            painter.drawRoundedRect(strength_rect, 4, 4)
            painter.drawText(strength_rect, Qt.AlignmentFlag.AlignCenter, level)

        # 副标题
        if not is_compact:
            sub_y = title_y + 22
            sub_parts = []

            if item_type == "account" and self._is_column_visible("username"):
                username = getattr(obj, "username", "") or ""
                if username:
                    if hasattr(obj, "mask_username"):
                        masked = obj.mask_username()
                    else:
                        masked = (
                            username[:3] + "****" + username[-3:]
                            if len(username) > 6
                            else username
                        )
                    sub_parts.append(masked)
            elif item_type == "url" and self._is_column_visible("url"):
                url = getattr(obj, "url", "") or (
                    obj.get("url", "") if isinstance(obj, dict) else ""
                )
                display_url = url[:40] if len(url) <= 40 else url[:40] + "..."
                sub_parts.append(display_url)

            if self._is_column_visible("time"):
                created = getattr(obj, "created_at", None) or (
                    obj.get("created_at") if isinstance(obj, dict) else None
                )
                updated = getattr(obj, "updated_at", None) or (
                    obj.get("updated_at") if isinstance(obj, dict) else None
                )
                time_parts = []
                if created:
                    created_str = (
                        created.strftime("%Y-%m-%d")
                        if hasattr(created, "strftime")
                        else str(created)[:10]
                    )
                    time_parts.append(f"创建:{created_str}")
                if updated:
                    updated_str = (
                        updated.strftime("%Y-%m-%d")
                        if hasattr(updated, "strftime")
                        else str(updated)[:10]
                    )
                    time_parts.append(f"修改:{updated_str}")
                if time_parts:
                    sub_parts.append("  ".join(time_parts))

            if sub_parts:
                sub_font = QFont()
                sub_font.setPixelSize(12)
                painter.setFont(sub_font)
                painter.setPen(QColor(colors.text_tertiary))
                sub_text = "  |  ".join(sub_parts)
                sub_rect = QRect(left, sub_y, available_width, 16)
                painter.drawText(
                    sub_rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    sub_text,
                )

        # 绘制分类标签
        if category_rect and category:
            painter.fillRect(category_rect, QColor(colors.bg_secondary))
            painter.setPen(QColor(colors.text_secondary))
            painter.drawRoundedRect(category_rect, 10, 10)
            painter.setFont(cat_font)
            painter.drawText(category_rect, Qt.AlignmentFlag.AlignCenter, category)

        # 绘制右箭头
        if arrow_rect:
            painter.setPen(QColor(colors.text_disabled))
            arrow_font = QFont()
            arrow_font.setPixelSize(18)
            painter.setFont(arrow_font)
            painter.drawText(arrow_rect, Qt.AlignmentFlag.AlignCenter, "›")

        # 绘制复制按钮
        btn_font = QFont()
        btn_font.setPixelSize(9)
        btn_font.setWeight(QFont.Weight.Bold)
        for action, btn_rect in copy_rects.items():
            painter.fillRect(btn_rect, QColor(colors.bg_primary))
            painter.setPen(QColor(colors.text_tertiary))
            painter.drawRoundedRect(btn_rect, 13, 13)
            painter.setFont(btn_font)
            label = {"url": "URL", "username": "ID", "password": "PW"}[action]
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, label)

        hit_rects.update(copy_rects)
        self._hit_rects[(index.row(), index.column())] = hit_rects

    def _draw_checkbox(self, painter: QPainter, rect: QRect, checked: bool):
        opt = QStyleOptionViewItem()
        opt.rect = rect
        opt.state = QStyle.StateFlag.State_Enabled
        if checked:
            opt.state |= QStyle.StateFlag.State_On
        else:
            opt.state |= QStyle.StateFlag.State_Off
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorCheckBox, opt, painter
        )

    def _draw_icon(self, painter: QPainter, rect: QRect, text: str, color: str):
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)
        painter.setPen(QColor(ThemeManager.instance().colors.text_on_accent))
        font = QFont()
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        initial = self._get_initial(text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initial)

    def _is_item_checked(self, obj) -> bool:
        item_id = getattr(obj, "id", None) or (
            obj.get("id") if isinstance(obj, dict) else None
        )
        return item_id in self._selected_ids

    def _is_column_visible(self, key: str, default: bool = True) -> bool:
        return self._column_config.get(key, default)

    @staticmethod
    def _generate_icon_color(text: str) -> str:
        colors = [
            "#E57373",
            "#F06292",
            "#BA68C8",
            "#9575CD",
            "#7986CB",
            "#64B5F6",
            "#4FC3F7",
            "#4DD0E1",
            "#4DB6AC",
            "#81C784",
            "#AED581",
            "#FFD54F",
            "#FFB74D",
            "#FF8A65",
            "#A1887F",
        ]
        hash_val = sum(ord(c) for c in text) if text else 0
        return colors[hash_val % len(colors)]

    @staticmethod
    def _get_initial(text: str) -> str:
        if not text:
            return "?"
        return text[0].upper()

    def hit_test(self, index: QModelIndex, pos) -> str:
        """测试点击位置对应的区域，pos 为 viewport 坐标"""
        rects = self._hit_rects.get((index.row(), index.column()), {})
        for name, rect in rects.items():
            if rect and rect.contains(pos):
                return name
        return "body"

    def editorEvent(self, event, model, option, index):
        if event.type() == event.Type.MouseButtonRelease:
            data = index.data(Qt.ItemDataRole.UserRole)
            if not data or data.get("item_type") == "header":
                return False
            pos = event.pos()
            region = self.hit_test(index, pos)
            obj = data.get("data")
            if not obj:
                return False
            if region == "checkbox":
                checked = not self._is_item_checked(obj)
                self.checkbox_toggled.emit(obj, checked)
                return True
            elif region == "copy_url":
                self.copy_url_requested.emit(obj)
                return True
            elif region == "copy_username":
                self.copy_username_requested.emit(obj)
                return True
            elif region == "copy_password":
                self.copy_password_requested.emit(obj)
                return True
        return False

"""CategoryTreeWidget and DropZoneWidget - 支持拖拽排序的分类树"""
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QLabel, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from core.theme_manager import ThemeManager

class DropZoneWidget(QLabel):
    """重组模式下的固定顶部拖放区域"""
    
    dropped = pyqtSignal(str)  # (source_path)
    
    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__("📌 将类别拖至此处成为一级类别", parent)
        self.setFixedHeight(40)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"""
            DropZoneWidget {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
                border: 2px dashed {colors.border_medium};
                border-radius: 6px;
                font-size: 12px;
                margin: 4px 6px;
            }}
        """)
        self.setAcceptDrops(True)
    
    def dragEnterEvent(self, event):
        colors = ThemeManager.instance().colors
        source = event.source()
        if isinstance(source, CategoryTreeWidget) and source._dragging_item:
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                DropZoneWidget {{
                    background-color: {colors.accent_blue_bg};
                    color: {colors.accent_blue};
                    border: 2px dashed {colors.accent_blue_light};
                    border-radius: 6px;
                    font-size: 12px;
                    margin: 4px 6px;
                }}
            """)
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        colors = ThemeManager.instance().colors
        self.setStyleSheet(f"""
            DropZoneWidget {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
                border: 2px dashed {colors.border_medium};
                border-radius: 6px;
                font-size: 12px;
                margin: 4px 6px;
            }}
        """)
    
    def dropEvent(self, event):
        colors = ThemeManager.instance().colors
        self.setStyleSheet(f"""
            DropZoneWidget {{
                background-color: {colors.bg_tertiary};
                color: {colors.text_tertiary};
                border: 2px dashed {colors.border_medium};
                border-radius: 6px;
                font-size: 12px;
                margin: 4px 6px;
            }}
        """)
        source = event.source()
        if isinstance(source, CategoryTreeWidget) and source._dragging_item:
            category = source._dragging_item.data(0, Qt.ItemDataRole.UserRole)
            if category and category not in ('全部', '__DROP_TO_ROOT__'):
                self.dropped.emit(category)
            event.acceptProposedAction()
        else:
            event.ignore()


class CategoryTreeWidget(QTreeWidget):
    """支持受限制拖拽排序和重组的分类树
    
    - 一级分类：只能在顶层之间移动
    - 二级分类：只能在同一父节点下移动，禁止跨父节点
    - 重组模式：支持跨层级拖拽重组
    """
    
    reorganize_requested = pyqtSignal(str, str)  # (source_path, target_parent)
    
    def __init__(self, parent=None):
        colors = ThemeManager.instance().colors
        super().__init__(parent)
        self._dragging_item = None
        self._edit_mode = False
        self._reorganize_mode = False
        self._normal_style = ""
        self._auto_scroll_direction = 0
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(50)
        self._auto_scroll_timer.timeout.connect(self._perform_auto_scroll)
    
    def _perform_auto_scroll(self):
        scrollbar = self.verticalScrollBar()
        if self._auto_scroll_direction == -1:
            new_value = scrollbar.value() - 18
            scrollbar.setValue(max(scrollbar.minimum(), new_value))
        elif self._auto_scroll_direction == 1:
            new_value = scrollbar.value() + 18
            scrollbar.setValue(min(scrollbar.maximum(), new_value))
    
    def set_normal_style(self, style: str):
        """保存正常模式下的样式表，用于退出编辑模式时恢复"""
        self._normal_style = style
        if not self._edit_mode and not self._reorganize_mode:
            self.setStyleSheet(style)
    
    def set_edit_mode(self, enabled: bool):
        colors = ThemeManager.instance().colors
        self._edit_mode = enabled
        if enabled:
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)
            self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
            # 编辑模式样式：拖拽指示器更明显
            self.setStyleSheet(f"""
                QTreeWidget {{
                    background-color: {colors.bg_secondary};
                    border: none;
                    outline: none;
                }}
                QTreeWidget::item {{
                    height: 38px;
                    padding-left: 12px;
                    border-radius: 6px;
                    margin: 2px 6px;
                    border: 1px dashed transparent;
                }}
                QTreeWidget::item:selected {{
                    background-color: {colors.accent_blue_bg};
                    color: {colors.accent_blue};
                    border: 1px dashed {colors.accent_blue_light};
                }}
                QTreeWidget::item:hover {{
                    background-color: {colors.bg_hover};
                }}
            """)
        else:
            self.setDragEnabled(False)
            self.setAcceptDrops(False)
            self.viewport().setAcceptDrops(False)
            self.setDragDropMode(QTreeWidget.DragDropMode.NoDragDrop)
            self.setDefaultDropAction(Qt.DropAction.IgnoreAction)
            # 恢复正常样式
            self.setStyleSheet(self._normal_style)
    
    def set_reorganize_mode(self, enabled: bool):
        colors = ThemeManager.instance().colors
        self._reorganize_mode = enabled
        if enabled:
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)
            self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.setStyleSheet(f"""
                QTreeWidget {{
                    background-color: {colors.bg_secondary};
                    border: none;
                    outline: none;
                }}
                QTreeWidget::item {{
                    height: 38px;
                    padding-left: 12px;
                    border-radius: 6px;
                    margin: 2px 6px;
                    border: 1px dashed transparent;
                }}
                QTreeWidget::item:selected {{
                    background-color: {colors.accent_blue_bg};
                    color: {colors.accent_blue};
                    border: 1px dashed {colors.accent_blue_light};
                }}
                QTreeWidget::item:hover {{
                    background-color: {colors.bg_hover};
                }}
            """)
        else:
            self.setDragEnabled(False)
            self.setAcceptDrops(False)
            self.viewport().setAcceptDrops(False)
            self.setDragDropMode(QTreeWidget.DragDropMode.NoDragDrop)
            self.setDefaultDropAction(Qt.DropAction.IgnoreAction)
            self.setStyleSheet(self._normal_style)
    
    def startDrag(self, supportedActions):
        # 开始拖拽前清理可能残留的状态
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        
        self._dragging_item = self.currentItem()
        super().startDrag(supportedActions)
        
        # drag 结束后（无论成功、取消或异常）强制清理
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        self._dragging_item = None
    
    def dragMoveEvent(self, event):
        if not self._dragging_item:
            event.ignore()
            return
        
        if not self._edit_mode and not self._reorganize_mode:
            event.ignore()
            return

        # 自动滚动检测
        y = event.position().toPoint().y()
        height = self.viewport().height()
        if y < height * 0.2:
            self._auto_scroll_direction = -1
            if not self._auto_scroll_timer.isActive():
                self._auto_scroll_timer.start()
        elif y > height * 0.8:
            self._auto_scroll_direction = 1
            if not self._auto_scroll_timer.isActive():
                self._auto_scroll_timer.start()
        else:
            self._auto_scroll_direction = 0
            self._auto_scroll_timer.stop()

        source_item = self._dragging_item
        source_parent = source_item.parent()
        source_data = source_item.data(0, Qt.ItemDataRole.UserRole)

        pos = event.position().toPoint()
        target_item = self.itemAt(pos)
        drop_indicator = self.dropIndicatorPosition()

        if self._reorganize_mode:
            # 重组模式规则
            # 1. 源是"全部"或"成为一级"特殊条目 → 拒绝
            if source_data in ('全部', '__DROP_TO_ROOT__', '__favorites__', '__recent__'):
                event.ignore()
                return
            
            # 2. Above/Below → 接受（同级排序）
            if drop_indicator in (QTreeWidget.DropIndicatorPosition.AboveItem,
                                  QTreeWidget.DropIndicatorPosition.BelowItem):
                # 一级只能在顶层之间排序
                if source_parent is None:
                    if target_item and target_item.parent() is not None:
                        event.ignore()
                        return
                else:
                    # 源是二级，目标必须在同一父节点下
                    if target_item and target_item.parent() != source_parent:
                        event.ignore()
                        return
                event.acceptProposedAction()
                return
            
            # 3. OnItem 情况
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem:
                if target_item is None:
                    event.ignore()
                    return
                
                target_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                
                # 目标是二级节点 → 拒绝（避免三级）
                if target_item.parent() is not None:
                    event.ignore()
                    return
                
                # 目标是一级节点
                # 源是一级（有子类）→ 拒绝（避免产生三级）
                if source_parent is None and source_item.childCount() > 0:
                    event.ignore()
                    return
                
                # 其他情况：源是一级（无子类）或二级，目标是一级 → 接受
                event.acceptProposedAction()
                return
            
            event.ignore()
            return

        # 原有排序逻辑
        # 先计算原始 target_parent
        if target_item:
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem:
                target_parent = target_item
            elif drop_indicator in (QTreeWidget.DropIndicatorPosition.AboveItem,
                                    QTreeWidget.DropIndicatorPosition.BelowItem):
                target_parent = target_item.parent() or self.invisibleRootItem()
            else:
                target_parent = self.invisibleRootItem()
        else:
            target_parent = self.invisibleRootItem()

        # 修正 OnItem：同级排序时 target_parent 应视为父容器
        if source_parent is None:                       # 一级分类
            if (target_item and target_item.parent() is None and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = self.invisibleRootItem()
        else:                                           # 二级分类
            if (target_item and target_item.parent() == source_parent and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = source_parent

        # 规则检查
        if source_parent is None:
            if target_parent != self.invisibleRootItem():
                event.ignore()
                return
        else:
            if target_parent != source_parent:
                event.ignore()
                return

        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        colors = ThemeManager.instance().colors
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        colors = ThemeManager.instance().colors
        self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        if not self._dragging_item:
            event.ignore()
            return
        
        if not self._edit_mode and not self._reorganize_mode:
            event.ignore()
            return

        source_item = self._dragging_item
        source_parent = source_item.parent()
        source_data = source_item.data(0, Qt.ItemDataRole.UserRole)

        # 计算目标位置
        pos = event.position().toPoint()
        target_item = self.itemAt(pos)
        drop_indicator = self.dropIndicatorPosition()

        if self._reorganize_mode:
            # 先处理 OnItem 跨层级重组
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem and target_item:
                target_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                
                # 目标是一级节点（二级节点已在 dragMoveEvent 中拒绝）
                if target_item.parent() is None:
                    if source_parent is None and source_item.childCount() > 0:
                        event.ignore()
                        self._dragging_item = None
                        return
                    
                    event.ignore()
                    self.reorganize_requested.emit(source_data, target_data)
                    self._dragging_item = None
                    return
            
            # 以下是 Above/Below 同级排序逻辑，和排序模式相同
            if target_item:
                if drop_indicator == QTreeWidget.DropIndicatorPosition.AboveItem:
                    target_parent = target_item.parent() or self.invisibleRootItem()
                    target_row = target_parent.indexOfChild(target_item)
                elif drop_indicator == QTreeWidget.DropIndicatorPosition.BelowItem:
                    target_parent = target_item.parent() or self.invisibleRootItem()
                    target_row = target_parent.indexOfChild(target_item) + 1
                else:
                    target_parent = self.invisibleRootItem()
                    target_row = self.topLevelItemCount()
            else:
                target_parent = self.invisibleRootItem()
                target_row = self.topLevelItemCount()
            
            # 修正 OnItem：同级排序时按 BelowItem 处理
            if source_parent is None:                       # 一级分类
                if (target_item and target_item.parent() is None and
                        drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                    target_parent = self.invisibleRootItem()
                    target_row = self.invisibleRootItem().indexOfChild(target_item) + 1
            else:                                           # 二级分类
                if (target_item and target_item.parent() == source_parent and
                        drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                    target_parent = source_parent
                    target_row = source_parent.indexOfChild(target_item) + 1
            
            # 规则限制
            if source_parent is None:
                if target_parent != self.invisibleRootItem():
                    event.ignore()
                    self._dragging_item = None
                    return
            else:
                if target_parent != source_parent:
                    event.ignore()
                    self._dragging_item = None
                    return
            
            # 手动移动
            event.ignore()
            _source_item = source_item
            _source_parent = source_parent
            _target_parent = target_parent
            _target_row = target_row

            def do_move():
                if _source_parent is None:
                    old_row = self.indexOfTopLevelItem(_source_item)
                    if old_row < 0:
                        return
                    taken = self.takeTopLevelItem(old_row)
                    if taken is None:
                        return
                    tr = _target_row
                    if old_row < tr:
                        tr -= 1
                    self.insertTopLevelItem(tr, taken)
                    self.setCurrentItem(taken)
                else:
                    old_row = _source_parent.indexOfChild(_source_item)
                    if old_row < 0:
                        return
                    taken = _source_parent.takeChild(old_row)
                    if taken is None:
                        return
                    tr = _target_row
                    if old_row < tr:
                        tr -= 1
                    _target_parent.insertChild(tr, taken)
                    self.setCurrentItem(taken)
                self.viewport().update()

            QTimer.singleShot(0, do_move)
            self._dragging_item = None
            return

        # 原有排序模式逻辑
        if target_item:
            if drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem:
                target_parent = target_item
                target_row = 0
            elif drop_indicator == QTreeWidget.DropIndicatorPosition.AboveItem:
                target_parent = target_item.parent() or self.invisibleRootItem()
                target_row = target_parent.indexOfChild(target_item)
            elif drop_indicator == QTreeWidget.DropIndicatorPosition.BelowItem:
                target_parent = target_item.parent() or self.invisibleRootItem()
                target_row = target_parent.indexOfChild(target_item) + 1
            else:
                target_parent = self.invisibleRootItem()
                target_row = self.topLevelItemCount()
        else:
            target_parent = self.invisibleRootItem()
            target_row = self.topLevelItemCount()

        # 修正 OnItem：同级排序时按 BelowItem 处理
        if source_parent is None:                       # 一级分类
            if (target_item and target_item.parent() is None and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = self.invisibleRootItem()
                target_row = self.invisibleRootItem().indexOfChild(target_item) + 1
        else:                                           # 二级分类
            if (target_item and target_item.parent() == source_parent and
                    drop_indicator == QTreeWidget.DropIndicatorPosition.OnItem):
                target_parent = source_parent
                target_row = source_parent.indexOfChild(target_item) + 1

        # 规则限制
        if source_parent is None:
            if target_parent != self.invisibleRootItem():
                event.ignore()
                self._dragging_item = None
                return
        else:
            if target_parent != source_parent:
                event.ignore()
                self._dragging_item = None
                return

        # 拒绝 Qt 默认 drop 处理，避免其内部 drag 清理逻辑与手动移动冲突
        event.ignore()

        # 延迟到下一帧再执行移动，等 Qt drag 状态完全结束
        _source_item = source_item
        _source_parent = source_parent
        _target_parent = target_parent
        _target_row = target_row

        def do_move():
            if _source_parent is None:
                old_row = self.indexOfTopLevelItem(_source_item)
                if old_row < 0:
                    return
                taken = self.takeTopLevelItem(old_row)
                if taken is None:
                    return
                tr = _target_row
                if old_row < tr:
                    tr -= 1
                self.insertTopLevelItem(tr, taken)
                self.setCurrentItem(taken)
            else:
                old_row = _source_parent.indexOfChild(_source_item)
                if old_row < 0:
                    return
                taken = _source_parent.takeChild(old_row)
                if taken is None:
                    return
                tr = _target_row
                if old_row < tr:
                    tr -= 1
                _target_parent.insertChild(tr, taken)
                self.setCurrentItem(taken)
            self.viewport().update()

        QTimer.singleShot(0, do_move)
        self._dragging_item = None


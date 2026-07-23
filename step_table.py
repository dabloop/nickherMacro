"""
The macro step editor — a sortable, reorderable table over a MacroModel.

Replaces the old chip flow, which stopped being usable past a few dozen steps:
no reordering, no insertion, and nowhere to show playback position.
"""

from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QStyledItemDelegate, QSpinBox, QMenu, QInputDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush

from core.macro import MacroModel

COL_NUM, COL_STEP, COL_HOLD, COL_DELAY = range(4)

MAX_MS = 600000

#: Row tint per step kind, so the table reads at a glance.
_KIND_COLOUR = {
    "key":   QColor("#aaaaff"),
    "mouse": QColor("#8fd6ff"),
    "wait":  QColor("#c8a8ff"),
    "text":  QColor("#8affa0"),
}

_PLAYING_BG = QColor("#252550")
_PLAYING_FG = QColor("#ffffff")


class _MsDelegate(QStyledItemDelegate):
    """Spin-box editor for the millisecond columns."""

    def createEditor(self, parent, option, index):
        box = QSpinBox(parent)
        box.setRange(0, MAX_MS)
        box.setSingleStep(10)
        box.setSuffix(" ms")
        box.setAccelerated(True)
        return box

    def setEditorData(self, editor, index):
        editor.setValue(index.data(Qt.UserRole) or 0)

    def setModelData(self, editor, model, index):
        editor.interpretText()
        model.setData(index, editor.value(), Qt.UserRole)


class StepTable(QTableWidget):
    changed = Signal()          # the macro was edited

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.macro = MacroModel()
        self._playing_row = None
        self._suppress = False

        self.setHorizontalHeaderLabels(["#", "Step", "Hold", "Delay after"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.MoveAction)

        delegate = _MsDelegate(self)
        self.setItemDelegateForColumn(COL_HOLD, delegate)
        self.setItemDelegateForColumn(COL_DELAY, delegate)

        head = self.horizontalHeader()
        head.setSectionResizeMode(COL_NUM, QHeaderView.Fixed)
        head.setSectionResizeMode(COL_STEP, QHeaderView.Stretch)
        head.setSectionResizeMode(COL_HOLD, QHeaderView.Fixed)
        head.setSectionResizeMode(COL_DELAY, QHeaderView.Fixed)
        self.setColumnWidth(COL_NUM, 46)
        self.setColumnWidth(COL_HOLD, 92)
        self.setColumnWidth(COL_DELAY, 104)

        self.itemChanged.connect(self._on_item_changed)

    # ── data ─────────────────────────────────────────────────────────────────
    def set_events(self, events):
        self.macro.set_events(events)
        self.refresh()

    def get_events(self):
        return self.macro.events

    def clear_all(self):
        self.macro.clear()
        self.refresh()

    def append_event(self, event):
        """Live append while recording."""
        self.macro.set_events(self.macro.events + [event])
        self.refresh()
        self.scrollToBottom()

    def step_count(self):
        return self.macro.step_count()

    def current_row_or_none(self):
        row = self.currentRow()
        return row if row >= 0 else None

    # ── rendering ────────────────────────────────────────────────────────────
    def refresh(self):
        self._suppress = True
        keep = self.currentRow()
        self.setRowCount(0)

        rows = self.macro.rows()
        self.setRowCount(len(rows))
        for n in range(len(rows)):
            self._fill_row(n)

        if 0 <= keep < self.rowCount():
            self.selectRow(keep)
        self._paint_rows()
        self._suppress = False

    def _fill_row(self, n: int):
        num = QTableWidgetItem(str(n + 1))
        num.setFlags(Qt.ItemIsEnabled)
        num.setForeground(QBrush(QColor("#44445f")))
        num.setTextAlignment(Qt.AlignCenter)
        self.setItem(n, COL_NUM, num)

        step = QTableWidgetItem(self.macro.label(n))
        step.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        step.setForeground(QBrush(_KIND_COLOUR.get(self.macro.kind(n), QColor("#c8c8e8"))))
        self.setItem(n, COL_STEP, step)

        hold = self.macro.hold_ms(n)
        hold_item = QTableWidgetItem("—" if hold is None else f"{hold} ms")
        if hold is None:
            hold_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            hold_item.setForeground(QBrush(QColor("#33334a")))
        else:
            hold_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            hold_item.setData(Qt.UserRole, hold)
            hold_item.setForeground(QBrush(QColor("#7f7fa8")))
        hold_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(n, COL_HOLD, hold_item)

        delay = self.macro.delay_ms(n)
        delay_item = QTableWidgetItem(f"{delay} ms")
        delay_item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        delay_item.setData(Qt.UserRole, delay)
        delay_item.setForeground(
            QBrush(QColor("#c8a8ff") if delay else QColor("#4a4a66")))
        delay_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(n, COL_DELAY, delay_item)

    def _on_item_changed(self, item):
        if self._suppress:
            return
        n, col = item.row(), item.column()
        value = item.data(Qt.UserRole)
        if value is None:
            return
        if col == COL_HOLD:
            self.macro.set_hold_ms(n, int(value))
        elif col == COL_DELAY:
            self.macro.set_delay_ms(n, int(value))
        else:
            return
        self.refresh()
        self.changed.emit()

    # ── playback highlight ───────────────────────────────────────────────────
    def highlight_event(self, event_index: int):
        """Called during playback with the index of the event being dispatched."""
        row = self.macro.row_for_event(event_index)
        if row == self._playing_row:
            return
        self._playing_row = row
        self._repaint_playing()
        if row is not None:
            self.scrollTo(self.indexFromItem(self.item(row, COL_STEP)))

    def clear_highlight(self):
        self._playing_row = None
        self._repaint_playing()

    def _repaint_playing(self):
        # setBackground/setForeground emit itemChanged; without this guard the
        # ms columns would be re-committed and re-refreshed forever.
        was, self._suppress = self._suppress, True
        try:
            self._paint_rows()
        finally:
            self._suppress = was

    def _paint_rows(self):
        for n in range(self.rowCount()):
            playing = (n == self._playing_row)
            for col in range(self.columnCount()):
                item = self.item(n, col)
                if item is None:
                    continue
                item.setBackground(QBrush(_PLAYING_BG) if playing else QBrush(Qt.NoBrush))
                if playing and col == COL_STEP:
                    item.setForeground(QBrush(_PLAYING_FG))
                elif col == COL_STEP:
                    item.setForeground(
                        QBrush(_KIND_COLOUR.get(self.macro.kind(n), QColor("#c8c8e8"))))

    # ── reordering ───────────────────────────────────────────────────────────
    def dropEvent(self, event):
        source = self.currentRow()
        target = self.rowAt(event.position().toPoint().y())
        if target < 0:
            target = self.rowCount() - 1
        event.setDropAction(Qt.IgnoreAction)   # we move it ourselves
        event.accept()
        if source < 0 or source == target:
            return
        new_row = self.macro.move(source, target)
        self.refresh()
        self.selectRow(new_row)
        self.changed.emit()

    def move_selected(self, delta: int):
        n = self.current_row_or_none()
        if n is None:
            return
        new_row = self.macro.move_up(n) if delta < 0 else self.macro.move_down(n)
        self.refresh()
        self.selectRow(new_row)
        self.changed.emit()

    # ── editing ──────────────────────────────────────────────────────────────
    def delete_selected(self):
        n = self.current_row_or_none()
        if n is None:
            return
        self.macro.delete(n)
        self.refresh()
        if self.rowCount():
            self.selectRow(min(n, self.rowCount() - 1))
        self.changed.emit()

    def duplicate_selected(self):
        n = self.current_row_or_none()
        if n is None:
            return
        self.macro.duplicate(n)
        self.refresh()
        self.changed.emit()

    def insert_wait(self, at_row=None):
        ms, ok = QInputDialog.getInt(self, "Insert wait", "Wait for (ms):",
                                     500, 0, MAX_MS, 50)
        if not ok:
            return
        row = self.macro.insert_wait(at_row, ms)
        self.refresh()
        self.selectRow(row)
        self.changed.emit()

    def insert_text(self, at_row=None):
        text, ok = QInputDialog.getText(self, "Insert typed text", "Text to type:")
        if not (ok and text):
            return
        row = self.macro.insert_text(at_row, text)
        self.refresh()
        self.selectRow(row)
        self.changed.emit()

    def has_moves(self) -> bool:
        return self.macro.has_moves()

    def remove_moves(self) -> int:
        removed = self.macro.remove_moves()
        if removed:
            self.refresh()
            self.changed.emit()
        return removed

    def fill_delays(self):
        ms, ok = QInputDialog.getInt(self, "Fill delays",
                                     "Delay after each step (ms):", 100, 0, MAX_MS, 10)
        if not ok:
            return ok
        self.macro.set_all_delays(ms)
        self.refresh()
        self.changed.emit()
        return ms

    # ── context menu ─────────────────────────────────────────────────────────
    def _show_menu(self, pos):
        row = self.rowAt(pos.y())
        menu = QMenu(self)

        if row >= 0:
            self.selectRow(row)
            menu.addAction("Move up",    lambda: self.move_selected(-1))
            menu.addAction("Move down",  lambda: self.move_selected(1))
            menu.addSeparator()
            menu.addAction("Duplicate",  self.duplicate_selected)
            menu.addAction("Delete",     self.delete_selected)
            menu.addSeparator()

        target = row if row >= 0 else None
        menu.addAction("Insert wait above…", lambda: self.insert_wait(target))
        menu.addAction("Insert text above…", lambda: self.insert_text(target))
        menu.exec(self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.delete_selected()
            return
        super().keyPressEvent(event)

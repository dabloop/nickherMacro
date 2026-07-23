"""
Nickher Macro – main window
"""

import sys
import os
import json
import threading

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QRadioButton, QCheckBox,
    QButtonGroup, QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QSystemTrayIcon, QMenu, QApplication,
    QInputDialog, QMessageBox, QFileDialog, QDialog, QDialogButtonBox,
    QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QComboBox,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QCursor, QAction

import pynput.keyboard as pynput_keyboard
from core.recorder import Recorder
from core.player import Player
from core import events as ev
from core import hotkeys
from core import presets as preset_store
from core import paths
from core.presets import PresetError
from step_table import StepTable, MAX_MS as MAX_DELAY_MS
from core import updater
from version import __version__

# ─── Hotkey defaults ──────────────────────────────────────────────────────────
DEFAULT_RECORD_KEY = "<f6>"
DEFAULT_LOOP_KEY   = "<f8>"
DEFAULT_PANIC_KEY  = "<esc>"

#: Sentinel for "the macro currently open in the Steps tab"
EDITOR = object()

def _settings_path() -> str:
    # %APPDATA%\NickherMacro when installed - a program folder is not writable
    return paths.data_file("settings.json")

def _load_settings() -> dict:
    p = _settings_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}

def _save_settings(data: dict):
    try:
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# ─── Cross-thread signal bridge ───────────────────────────────────────────────
class _Bridge(QObject):
    record_toggle = Signal()
    loop_toggle   = Signal()
    panic         = Signal()
    recorded      = Signal(dict)
    playback_done = Signal()
    cycle_update  = Signal(int, int)
    engine_error  = Signal(str)
    step_update   = Signal(int)
    preset_fired  = Signal(str)
    update_result = Signal(object, str)   # (UpdateInfo or None, error message)
    update_ready  = Signal(str, str)      # (downloaded path, error message)
    update_progress = Signal(int, int)


# ─── Stylesheet ────────────────────────────────────────────────────────────────
STYLE = """
QMainWindow, QWidget#root { background: #0e0e12; }

QFrame#card {
    background: #16161e;
    border: 1px solid #252535;
    border-radius: 10px;
}

/* Tabs */
QTabWidget::pane { border: none; background: transparent; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent; color: #55557a;
    padding: 9px 20px; margin-right: 2px;
    border: none; border-bottom: 2px solid transparent;
    font-size: 13px; font-weight: bold;
}
QTabBar::tab:hover     { color: #9f9fc8; }
QTabBar::tab:selected  { color: #e2e2f0; border-bottom: 2px solid #5b5bff; }
QTabBar::tab:disabled  { color: #303045; }

/* Persistent action bar */
QFrame#actionBar {
    background: #14141c;
    border: 1px solid #222230;
    border-radius: 10px;
}
QFrame#divider { background: #222230; max-height: 1px; border: none; }

QLabel#sectionTitle {
    color: #5a5a80; font-size: 10px;
    letter-spacing: 2px; font-weight: bold;
}
QLabel#heading { color: #e2e2f0; font-size: 19px; font-weight: bold; }
QLabel#sub     { color: #7f7fa8; font-size: 12px; }
QLabel#info    { color: #9f9fc8; font-size: 12px; }
QLabel#hint    { color: #55557a; font-size: 11px; }

QLabel#toast     { background:#252540; color:#c8c8ff; border:1px solid #3a3a60; border-radius:8px; padding:7px 16px; font-size:12px; font-weight:bold; }
QLabel#toastRec  { background:#3d1020; color:#ff8aaa; border:1px solid #6d2040; border-radius:8px; padding:7px 16px; font-size:12px; font-weight:bold; }
QLabel#toastLoop { background:#10203d; color:#8aaaff; border:1px solid #204060; border-radius:8px; padding:7px 16px; font-size:12px; font-weight:bold; }
QLabel#toastDone { background:#103d10; color:#8affa0; border:1px solid #205d20; border-radius:8px; padding:7px 16px; font-size:12px; font-weight:bold; }
QLabel#toastErr  { background:#3d1010; color:#ff9090; border:1px solid #6d2020; border-radius:8px; padding:7px 16px; font-size:12px; font-weight:bold; }

QPushButton#bindBtn {
    background:#1e1e30; color:#c8c8ff;
    border:1px solid #4a4a7a; border-radius:7px;
    padding:6px 12px; font-size:12px; font-weight:bold;
}
QPushButton#bindBtn:hover { background:#252545; border-color:#5b5bff; }
QPushButton#bindBtnActive {
    background:#2a2a50; color:#ffffff;
    border:2px solid #5b5bff; border-radius:7px;
    padding:6px 12px; font-size:12px; font-weight:bold;
}

QSpinBox, QDoubleSpinBox {
    background:#0e0e12; border:1px solid #252535; border-radius:7px;
    color:#c8c8e8; padding:5px 8px; font-size:13px; min-width:70px;
}
QSpinBox:disabled, QDoubleSpinBox:disabled { color:#4a4a60; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background:#252535; border:none; border-radius:3px; width:18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background:#353550; }

QRadioButton { color:#c8c8e8; font-size:13px; spacing:7px; }
QRadioButton::indicator {
    width:14px; height:14px; border-radius:7px;
    border:2px solid #353550; background:#0e0e12;
}
QRadioButton::indicator:checked { background:#5b5bff; border-color:#5b5bff; }

QCheckBox { color:#c8c8e8; font-size:12px; spacing:7px; }
QCheckBox::indicator {
    width:14px; height:14px; border-radius:4px;
    border:2px solid #353550; background:#0e0e12;
}
QCheckBox::indicator:checked { background:#5b5bff; border-color:#5b5bff; }

QTableWidget {
    background:#0e0e12; border:1px solid #252535;
    border-radius:8px; color:#c8c8e8; font-size:13px;
    outline:none; gridline-color:transparent;
}
QTableWidget::item { padding:5px 8px; border:none; }
QTableWidget::item:selected { background:#252550; color:#e2e2ff; }
QTableWidget::item:hover    { background:#1a1a26; }
QHeaderView::section {
    background:#14141c; color:#5a5a80; border:none;
    border-bottom:1px solid #252535;
    padding:7px 8px; font-size:10px; font-weight:bold; letter-spacing:1px;
}
QTableWidget QSpinBox {
    background:#1a1a28; border:1px solid #5b5bff; border-radius:4px;
    color:#e2e2ff; font-size:12px; padding:2px 4px; min-width:0px;
}
QScrollBar:vertical {
    background:transparent; width:10px; margin:0px; border:none;
}
QScrollBar::handle:vertical {
    background:#2a2a40; border-radius:5px; min-height:26px;
}
QScrollBar::handle:vertical:hover { background:#3a3a60; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:none; }

QMenu {
    background:#16161e; border:1px solid #2a2a3d;
    border-radius:8px; padding:5px; color:#c8c8e8; font-size:12px;
}
QMenu::item { padding:6px 20px; border-radius:5px; }
QMenu::item:selected { background:#252550; color:#e2e2ff; }
QMenu::separator { height:1px; background:#252535; margin:4px 8px; }

QPushButton {
    border-radius:8px; font-size:13px; font-weight:bold;
    padding:9px 18px; border:none; color:#fff;
}
QPushButton:disabled { color:#6a6a80; }
QPushButton#btnRecord       { background:#c0364d; }
QPushButton#btnRecord:hover { background:#d94060; }
QPushButton#btnRecordOn       { background:#ff4d7a; border:2px solid #ffaacc; }
QPushButton#btnRecordOn:hover { background:#ff6a8f; }
QPushButton#btnLoop           { background:#2d48cc; }
QPushButton#btnLoop:hover     { background:#3d5bff; }
QPushButton#btnLoopOn         { background:#3d5bff; border:2px solid #aabbff; }
QPushButton#btnLoopOn:hover   { background:#5570ff; }
QPushButton#btnGhost {
    background:#1e1e2e; color:#c8c8e8;
    border:1px solid #252535; font-weight:normal;
    padding:5px 12px; font-size:12px;
}
QPushButton#btnGhost:hover { background:#252540; }
QPushButton#btnSave        { background:#1a3a1a; color:#60ff80; border:1px solid #2a5a2a; }
QPushButton#btnSave:hover  { background:#1f4a1f; }
QPushButton#btnDanger      { background:#3a1818; color:#ff6060; border:1px solid #5a2020; font-size:12px; padding:5px 12px; }
QPushButton#btnDanger:hover { background:#4a2020; }

/* Key chips */
QFrame#chip {
    background:#1e1e38;
    border:1px solid #3a3a60;
    border-radius:7px;
}
QFrame#chip:hover { border-color:#5b5bff; }
QFrame#chipWait {
    background:#2a1e38;
    border:1px solid #55407a;
    border-radius:7px;
}
QFrame#chipWait:hover { border-color:#9b7bff; }
QLabel#chipLabel {
    color:#aaaaff; font-size:12px;
    font-family:'Courier New'; padding:0px;
}
QLabel#chipArrow {
    color:#3a3a60; font-size:12px; padding:0px 1px;
}

/* Inline per-step delay box */
QSpinBox#delayBox {
    background:#12121a; border:1px solid #2e2e45; border-radius:6px;
    color:#6a6a90; font-size:11px; font-family:'Courier New';
    padding:3px 4px; min-width:0px;
}
QSpinBox#delayBox:hover  { border-color:#5b5bff; color:#aaaaff; }
QSpinBox#delayBox:focus  { border-color:#5b5bff; color:#e2e2ff; background:#1a1a28; }
QSpinBox#delayBoxSet {
    background:#1e1838; border:1px solid #55407a; border-radius:6px;
    color:#c8a8ff; font-size:11px; font-family:'Courier New';
    padding:3px 4px; min-width:0px;
}
QSpinBox#delayBoxSet:hover { border-color:#9b7bff; }
QSpinBox#delayBoxSet:focus { border-color:#9b7bff; color:#e8d8ff; background:#251d45; }
QPushButton#chipX {
    background:transparent; color:#4a3a5a;
    border:none; font-size:11px; font-weight:bold;
    padding:0px; min-width:0px; border-radius:3px;
}
QPushButton#chipX:hover { color:#ff6060; background:#2a1020; }

QScrollArea#chipScroll { background:#0e0e12; border:1px solid #252535; border-radius:8px; }
QWidget#chipContainer  { background:#0e0e12; }

QLabel#progressLabel { color:#7f7fa8; font-size:11px; }
QLabel#statusBadge   { font-size:11px; font-weight:bold; border-radius:5px; padding:2px 10px; }

QPushButton#resetBtn {
    background: transparent; color: #3a3a60;
    border: none; font-size: 15px; padding: 0px 4px;
    min-width: 0; border-radius: 4px;
}
QPushButton#resetBtn:hover { color: #aaaaff; background: #1e1e38; }
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _card(parent=None):
    f = QFrame(parent); f.setObjectName("card"); return f

def _lbl(text, obj="sub", parent=None):
    l = QLabel(text, parent); l.setObjectName(obj); return l

def _sec(text, parent=None):
    l = QLabel(text.upper(), parent); l.setObjectName("sectionTitle"); return l

def _btn(text, obj="btnGhost", parent=None):
    b = QPushButton(text, parent)
    b.setObjectName(obj)
    b.setCursor(QCursor(Qt.PointingHandCursor))
    return b

def _restyle(widget, obj_name):
    """Swap a widget's objectName and force the stylesheet to re-apply."""
    widget.setObjectName(obj_name)
    widget.setStyleSheet("")


def _release_common_keys():
    """
    Nuclear key release: send 'up' for every key a macro is likely to have left
    held. Used by the panic path when the player object may be gone or wedged,
    so it never relies on tracked state. Releasing a key that wasn't down is
    harmless, so we can afford to be thorough.
    """
    from pynput.keyboard import Controller, Key, KeyCode
    kb = Controller()
    keys = [
        Key.shift, Key.shift_r, Key.ctrl_l, Key.ctrl_r, Key.alt_l, Key.alt_gr,
        Key.cmd, Key.cmd_r, Key.space, Key.enter, Key.tab, Key.backspace,
        Key.caps_lock,
    ]
    for k in keys:
        try:
            kb.release(k)
        except Exception:
            pass
    for code in list(range(ord("a"), ord("z") + 1)) + list(range(ord("0"), ord("9") + 1)):
        try:
            kb.release(KeyCode.from_char(chr(code)))
        except Exception:
            pass


# ─── Bind Button ──────────────────────────────────────────────────────────────
class _BindBridge(QObject):
    """Thread-safe bridge: pynput thread → Qt thread."""
    captured = Signal(str)

class BindButton(QPushButton):
    """
    Captures a key by pressing it. In `chord` mode it captures a combination —
    hold Shift and press 5 to get 'Shift + 5' — and stores a canonical hotkey
    string. Otherwise it captures a single key (used by the key-step dialog).
    """
    bound = Signal(str)

    def __init__(self, initial_raw=DEFAULT_RECORD_KEY, parent=None, chord=False):
        super().__init__(parent)
        self._raw = initial_raw
        self._chord = chord
        self._listening = False
        self._bridge = _BindBridge()
        self._bridge.captured.connect(self._finish)
        self.setObjectName("bindBtn")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._update_label()
        self.clicked.connect(self._start_listen)

    def raw(self) -> str:
        return self._raw

    def set_raw(self, raw: str):
        self._raw = raw
        self._update_label()

    def _label_for(self, raw: str) -> str:
        if not raw:
            return "Bind…"
        return hotkeys.pretty(raw) if self._chord else ev.pretty_key(raw)

    def _update_label(self):
        self.setText(f"  {self._label_for(self._raw)}  ")

    def _start_listen(self):
        if self._listening:
            return
        self._listening = True
        _restyle(self, "bindBtnActive")
        self.setText("  Press a combo…  " if self._chord else "  Press a key…  ")
        win = self.window()
        if hasattr(win, "_binding"):
            win._binding = True
        bridge = self._bridge

        if self._chord:
            tracker = hotkeys.ChordTracker()

            def _on_press(key):
                result = tracker.press(key)   # None while only modifiers are held
                if result:
                    bridge.captured.emit(result)
                    return False

            def _on_release(key):
                tracker.release(key)

            listener = pynput_keyboard.Listener(
                on_press=_on_press, on_release=_on_release)
        else:
            def _on_press(key):
                try:
                    bridge.captured.emit(ev.encode_key(key))
                except ev.EventError:
                    bridge.captured.emit("")
                return False

            listener = pynput_keyboard.Listener(on_press=_on_press)

        listener.daemon = True
        listener.start()

    def _finish(self, raw: str):
        self._listening = False
        if raw:
            self._raw = raw
        _restyle(self, "bindBtn")
        self._update_label()
        win = self.window()
        if hasattr(win, "_binding"):
            win._binding = False
        if raw:
            self.bound.emit(raw)


# ─── Add-key dialog ───────────────────────────────────────────────────────────
MODIFIER_KEYS = [
    ("Ctrl",  "<ctrl_l>"),
    ("Shift", "<shift>"),
    ("Alt",   "<alt_l>"),
    ("Win",   "<cmd>"),
]


class KeyStepDialog(QDialog):
    """
    Pick a key to insert as a step. The key is captured by pressing it, so
    there is no text field to type into and nothing to mistype.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add key step")
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.setMinimumWidth(340)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(12)

        box.addWidget(_lbl("Click the button, then press the key you want.", "info"))

        self._bind = BindButton("")
        self._bind.setFixedWidth(150)
        self._bind.bound.connect(lambda _raw: self._refresh_ok())
        row = QHBoxLayout()
        row.addWidget(self._bind)
        row.addStretch()
        box.addLayout(row)

        box.addWidget(_lbl("Hold with", "sub"))
        mods = QHBoxLayout(); mods.setSpacing(12)
        self._mod_boxes = []
        for label, encoded in MODIFIER_KEYS:
            cb = QCheckBox(label)
            cb.setProperty("encoded", encoded)
            mods.addWidget(cb)
            self._mod_boxes.append(cb)
        mods.addStretch()
        box.addLayout(mods)

        hold_row = QHBoxLayout()
        hold_row.addWidget(_lbl("Hold for", "info"))
        self._hold = QSpinBox()
        self._hold.setRange(0, MAX_DELAY_MS)
        self._hold.setValue(30)
        self._hold.setSingleStep(10)
        self._hold.setSuffix(" ms")
        hold_row.addWidget(self._hold)
        hold_row.addStretch()
        box.addLayout(hold_row)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        box.addWidget(self._buttons)
        self._refresh_ok()

    def _refresh_ok(self):
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self._bind.raw()))

    def result_key(self):
        """(encoded_key, [modifiers], hold_ms) — or None if nothing was picked."""
        raw = self._bind.raw()
        if not raw:
            return None
        mods = [cb.property("encoded") for cb in self._mod_boxes if cb.isChecked()]
        return raw, mods, self._hold.value()


# ─── Toast ────────────────────────────────────────────────────────────────────
class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self._timer = QTimer(singleShot=True)
        self._timer.timeout.connect(self.hide)

    def show_msg(self, text: str, style_obj="toast", ms=2000):
        self._timer.stop()
        _restyle(self, style_obj)
        self.setText(text)
        self.adjustSize()
        pw = self.parent().width()
        self.setFixedWidth(min(pw - 40, 360))
        self.move((pw - self.width()) // 2, 12)
        self.raise_()
        self.show()
        self._timer.start(ms)


# ─── Main Window ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nickher Macro")
        self.setMinimumSize(720, 520)
        self.resize(880, 620)
        self.setStyleSheet(STYLE)

        self._bridge = _Bridge()
        self._rec = Recorder()
        self._player: Player | None = None
        self._is_recording = False
        self._is_looping   = False
        self._binding      = False  # True while a BindButton waits for a key
        self._typing       = False  # True while a text field in our UI has focus
        self._quitting     = False

        #: What is playing right now — EDITOR for the macro in the Steps tab,
        #: or a preset name when a preset hotkey fired it. Only one at a time:
        #: two macros typing at once produces garbage input.
        self._active = None

        self._bridge.record_toggle.connect(self._toggle_record)
        self._bridge.loop_toggle.connect(self._toggle_loop)
        self._bridge.panic.connect(self._panic)
        self._bridge.recorded.connect(self._on_recorded_event)
        self._bridge.playback_done.connect(self._on_playback_done)
        self._bridge.cycle_update.connect(self._on_cycle_update)
        self._bridge.engine_error.connect(self._on_engine_error)
        self._bridge.step_update.connect(self._on_step_update)
        self._bridge.preset_fired.connect(self._trigger_preset)
        self._bridge.update_result.connect(self._on_update_result)
        self._bridge.update_ready.connect(self._on_update_ready)
        self._bridge.update_progress.connect(self._on_update_progress)

        self._rec.on_event = lambda e: self._bridge.recorded.emit(e)
        self._rec.on_error = lambda exc: self._bridge.engine_error.emit(str(exc))

        s = _load_settings()
        self._saved_record_key = hotkeys.normalize(
            s.get("record_key", DEFAULT_RECORD_KEY), DEFAULT_RECORD_KEY)
        self._saved_loop_key = hotkeys.normalize(
            s.get("loop_key", DEFAULT_LOOP_KEY), DEFAULT_LOOP_KEY)
        self._saved_panic_key = hotkeys.normalize(
            s.get("panic_key", DEFAULT_PANIC_KEY), DEFAULT_PANIC_KEY)

        raw_keys = s.get("preset_keys", {})
        self._preset_keys = {
            name: hotkeys.normalize(key)
            for name, key in (raw_keys.items() if isinstance(raw_keys, dict) else [])
            if hotkeys.normalize(key)
        }

        self._build_ui()
        self._restore_prefs(s)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        self._build_tray()
        self._start_global_listener()
        self._refresh_presets()

        updater.cleanup_old_binary()
        if self._chk_autoupdate.isChecked() and updater.GITHUB_REPO:
            QTimer.singleShot(2500, lambda: self._check_updates(quiet=True))

    # ── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(18, 16, 18, 16)
        main.setSpacing(12)

        self._toast = Toast(root)

        # ── Header ──
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("Nickher Macro", "heading"))
        hdr.addStretch()
        self._status_badge = QLabel("IDLE")
        self._status_badge.setObjectName("statusBadge")
        self._set_badge("IDLE")
        hdr.addWidget(self._status_badge)
        main.addLayout(hdr)

        # ── Tabs ──
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._build_macro_tab(),    "Macro")
        self._tabs.addTab(self._build_playback_tab(), "Playback")
        self._tabs.addTab(self._build_presets_tab(),  "Presets")
        self._tabs.addTab(self._build_settings_tab(), "Settings")
        main.addWidget(self._tabs, 1)

        # ── Action bar — always visible, whichever tab is open ──
        main.addWidget(self._build_action_bar())

    def _tab_page(self):
        """A tab page with consistent breathing room."""
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 14, 0, 0)
        box.setSpacing(12)
        return page, box

    # ── Macro tab ────────────────────────────────────────────────────────────
    def _build_macro_tab(self):
        page, box = self._tab_page()

        card = _card()
        rc = QVBoxLayout(card)
        rc.setContentsMargins(18, 16, 18, 16)
        rc.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(_sec("Steps"))
        top.addStretch()
        self._rec_count_lbl = _lbl("0 steps", "sub")
        top.addWidget(self._rec_count_lbl)
        rc.addLayout(top)

        self._steps = StepTable()
        self._steps.changed.connect(self._on_events_changed)
        rc.addWidget(self._steps, 1)

        rc.addWidget(_lbl(
            "Double-click Hold or Delay to edit · drag rows to reorder · "
            "right-click for more", "hint"))

        # Row-editing tools
        tools = QHBoxLayout(); tools.setSpacing(6)
        b_up   = _btn("↑", "btnGhost"); b_up.setToolTip("Move step up")
        b_down = _btn("↓", "btnGhost"); b_down.setToolTip("Move step down")
        b_up.setFixedWidth(34); b_down.setFixedWidth(34)
        b_up.clicked.connect(lambda: self._steps.move_selected(-1))
        b_down.clicked.connect(lambda: self._steps.move_selected(1))

        b_wait = _btn("+ Wait", "btnGhost")
        b_wait.setToolTip("Insert a wait step above the selected row")
        b_wait.clicked.connect(lambda: self._steps.insert_wait(
            self._steps.current_row_or_none()))
        b_key = _btn("+ Key", "btnGhost")
        b_key.setToolTip("Insert a key press above the selected row")
        b_key.clicked.connect(self._insert_key_step)
        b_text = _btn("+ Text", "btnGhost")
        b_text.setToolTip("Insert a step that types a line of text")
        b_text.clicked.connect(lambda: self._steps.insert_text(
            self._steps.current_row_or_none()))
        b_dup = _btn("Duplicate", "btnGhost")
        b_dup.clicked.connect(self._steps.duplicate_selected)
        b_fill = _btn("Fill delays", "btnGhost")
        b_fill.setToolTip("Set the same delay after every step")
        b_fill.clicked.connect(self._delay_all_steps)
        b_del = _btn("Delete", "btnDanger")
        b_del.clicked.connect(self._steps.delete_selected)
        b_clear = _btn("✕  Clear", "btnDanger")
        b_clear.clicked.connect(self._clear_recording)

        for b in (b_up, b_down, b_key, b_wait, b_text, b_dup, b_fill):
            tools.addWidget(b)
        tools.addStretch()
        tools.addWidget(b_del)
        tools.addWidget(b_clear)
        rc.addLayout(tools)

        # Capture options
        opts = QHBoxLayout(); opts.setSpacing(14)
        self._chk_mouse = QCheckBox("Record mouse clicks")
        self._chk_mouse.setChecked(True)
        self._chk_moves = QCheckBox("Record mouse movement")
        self._chk_moves.setToolTip("Records the pointer path. Adds a lot of steps.")
        opts.addWidget(self._chk_mouse)
        opts.addWidget(self._chk_moves)
        opts.addStretch()
        rc.addLayout(opts)

        box.addWidget(card, 1)
        return page

    # ── Playback tab ─────────────────────────────────────────────────────────
    def _build_playback_tab(self):
        page, box = self._tab_page()

        # ── Timing ──
        timing = _card()
        tl = QVBoxLayout(timing)
        tl.setContentsMargins(18, 16, 18, 16)
        tl.setSpacing(12)
        tl.addWidget(_sec("Timing"))

        modes = QHBoxLayout(); modes.setSpacing(16)
        self._radio_recorded = QRadioButton("Recorded timing")
        self._radio_recorded.setToolTip("Replay at the speed you originally recorded.")
        self._radio_fixed = QRadioButton("Fixed interval")
        self._radio_fixed.setToolTip("Ignore the recording's rhythm; use one flat gap.")
        self._radio_recorded.setChecked(True)
        self._timing_grp = QButtonGroup(self)
        self._timing_grp.addButton(self._radio_recorded, 0)
        self._timing_grp.addButton(self._radio_fixed, 1)
        self._radio_recorded.toggled.connect(self._on_timing_toggle)
        modes.addWidget(self._radio_recorded)
        modes.addWidget(self._radio_fixed)
        modes.addStretch()
        tl.addLayout(modes)

        form = self._form()
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setRange(0.1, 20.0)
        self._speed_spin.setSingleStep(0.25)
        self._speed_spin.setValue(1.0)
        self._speed_spin.setSuffix(" ×")
        self._speed_spin.setToolTip("Recorded timing only. 2× replays twice as fast.")
        form.addRow(_lbl("Speed", "info"), self._speed_spin)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(0, 60000)
        self._interval_spin.setValue(50)
        self._interval_spin.setSuffix(" ms")
        self._interval_spin.setEnabled(False)
        self._interval_spin.setToolTip("Fixed interval only. Gap between every event.")
        form.addRow(_lbl("Interval", "info"), self._interval_spin)

        self._step_delay_spin = QSpinBox()
        self._step_delay_spin.setRange(0, MAX_DELAY_MS)
        self._step_delay_spin.setSuffix(" ms")
        self._step_delay_spin.setToolTip(
            "Added after every step, on top of the per-step boxes on the Macro tab.")
        form.addRow(_lbl("Extra delay", "info"), self._step_delay_spin)

        self._jitter_spin = QSpinBox()
        self._jitter_spin.setRange(0, 90)
        self._jitter_spin.setSuffix(" %")
        self._jitter_spin.setToolTip("Randomise every wait by ±N% so timing looks human.")
        form.addRow(_lbl("Jitter", "info"), self._jitter_spin)
        tl.addLayout(form)
        box.addWidget(timing)

        # ── Repeat ──
        rep = _card()
        rl = QVBoxLayout(rep)
        rl.setContentsMargins(18, 16, 18, 16)
        rl.setSpacing(12)
        rl.addWidget(_sec("Repeat"))

        rmodes = QHBoxLayout(); rmodes.setSpacing(16)
        self._radio_inf = QRadioButton("Infinite")
        self._radio_rep = QRadioButton("Repeat")
        self._radio_inf.setChecked(True)
        self._mode_grp = QButtonGroup(self)
        self._mode_grp.addButton(self._radio_inf, 0)
        self._mode_grp.addButton(self._radio_rep, 1)
        self._radio_inf.toggled.connect(self._on_mode_toggle)
        self._repeat_spin = QSpinBox()
        self._repeat_spin.setRange(1, 99999)
        self._repeat_spin.setValue(5)
        self._repeat_spin.setSuffix(" ×")
        self._repeat_spin.setEnabled(False)
        rmodes.addWidget(self._radio_inf)
        rmodes.addWidget(self._radio_rep)
        rmodes.addWidget(self._repeat_spin)
        rmodes.addStretch()
        rl.addLayout(rmodes)

        rform = self._form()
        self._loop_gap_spin = QSpinBox()
        self._loop_gap_spin.setRange(0, MAX_DELAY_MS)
        self._loop_gap_spin.setSuffix(" ms")
        rform.addRow(_lbl("Gap between runs", "info"), self._loop_gap_spin)
        rl.addLayout(rform)
        box.addWidget(rep)

        box.addStretch()
        return page

    # ── Presets tab ──────────────────────────────────────────────────────────
    def _build_presets_tab(self):
        page, box = self._tab_page()

        card = _card()
        pc = QVBoxLayout(card)
        pc.setContentsMargins(18, 16, 18, 16)
        pc.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(_sec("Saved Macros"))
        top.addStretch()
        top.addWidget(_lbl(
            "Double-click a name to load · bind a key to run it from anywhere", "hint"))
        pc.addLayout(top)

        self._preset_list = QTableWidget(0, 3)
        self._preset_list.setHorizontalHeaderLabels(["Name", "Steps", "Hotkey"])
        self._preset_list.verticalHeader().setVisible(False)
        self._preset_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._preset_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._preset_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preset_list.setShowGrid(False)
        self._preset_list.cellDoubleClicked.connect(
            lambda row, col: self._load_preset() if col == 0 else None)
        head = self._preset_list.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        head.setSectionResizeMode(1, QHeaderView.Fixed)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        self._preset_list.setColumnWidth(1, 76)
        self._preset_list.setColumnWidth(2, 210)
        pc.addWidget(self._preset_list, 1)

        row = QHBoxLayout(); row.setSpacing(8)
        b_save = _btn("💾 Save", "btnSave")
        b_load = _btn("Load", "btnGhost")
        b_imp  = _btn("Import…", "btnGhost")
        b_exp  = _btn("Export…", "btnGhost")
        b_del  = _btn("Delete", "btnDanger")
        b_save.clicked.connect(self._save_preset)
        b_load.clicked.connect(self._load_preset)
        b_imp.clicked.connect(self._import_preset)
        b_exp.clicked.connect(self._export_preset)
        b_del.clicked.connect(self._delete_preset)
        for b in (b_save, b_load, b_imp, b_exp):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(b_del)
        pc.addLayout(row)

        box.addWidget(card, 1)
        return page

    # ── Settings tab ─────────────────────────────────────────────────────────
    def _build_settings_tab(self):
        page, box = self._tab_page()

        card = _card()
        hk = QVBoxLayout(card)
        hk.setContentsMargins(18, 16, 18, 16)
        hk.setSpacing(12)
        hk.addWidget(_sec("Hotkeys"))

        def _bind_cell(label, default, saved, hint):
            """A compact 'label above key' unit, sized to sit inline with others."""
            reset = QPushButton("↺")
            reset.setObjectName("resetBtn")
            reset.setFixedSize(22, 22)
            reset.setCursor(QCursor(Qt.PointingHandCursor))
            reset.setToolTip("Reset to default")
            b = BindButton(saved, chord=True)
            b.setFixedWidth(118)
            b.setToolTip(hint + " — you can use combos like Shift+5")
            reset.setVisible(saved != default)

            def _on_bound(raw, _rst=reset, _dflt=default):
                _rst.setVisible(raw != _dflt)
                self._save_prefs()

            def _on_reset(_b=b, _rst=reset, _dflt=default):
                _b.set_raw(_dflt)
                _rst.setVisible(False)
                self._save_prefs()

            b.bound.connect(_on_bound)
            # lambda with no args — QPushButton.clicked passes a bool we ignore
            reset.clicked.connect(lambda _checked=False, f=_on_reset: f())

            cell = QVBoxLayout()
            cell.setSpacing(5)
            cell.addWidget(_lbl(label, "info"))
            controls = QHBoxLayout()
            controls.setSpacing(4)
            controls.addWidget(b)
            controls.addWidget(reset)
            controls.addStretch()
            cell.addLayout(controls)
            return cell, b

        rec_cell, self._record_bind = _bind_cell(
            "Record", DEFAULT_RECORD_KEY, self._saved_record_key,
            "Starts and stops recording")
        loop_cell, self._loop_bind = _bind_cell(
            "Loop", DEFAULT_LOOP_KEY, self._saved_loop_key,
            "Starts and stops playback")
        panic_cell, self._panic_bind = _bind_cell(
            "Panic", DEFAULT_PANIC_KEY, self._saved_panic_key,
            "Halts recording and playback instantly")

        line = QHBoxLayout()
        line.setSpacing(22)
        for cell in (rec_cell, loop_cell, panic_cell):
            line.addLayout(cell)
        line.addStretch()
        hk.addLayout(line)

        hk.addWidget(_lbl(
            "Hotkeys work while other windows are focused. "
            "Clicks on this window are never recorded.", "hint"))
        box.addWidget(card)

        tray_card = _card()
        tc = QVBoxLayout(tray_card)
        tc.setContentsMargins(18, 16, 18, 16)
        tc.setSpacing(10)
        tc.addWidget(_sec("Window"))
        self._chk_tray = QCheckBox("Keep running in the tray when the window is closed")
        self._chk_tray.setChecked(True)
        tc.addWidget(self._chk_tray)
        tc.addWidget(_lbl(
            "Hotkeys keep working while hidden. Quit from the tray icon's menu.", "hint"))
        box.addWidget(tray_card)

        up_card = _card()
        uc = QVBoxLayout(up_card)
        uc.setContentsMargins(18, 16, 18, 16)
        uc.setSpacing(10)
        uc.addWidget(_sec("Updates"))

        row = QHBoxLayout()
        row.addWidget(_lbl(f"Version {__version__}", "info"))
        row.addStretch()
        self._btn_update = _btn("Check for updates", "btnGhost")
        self._btn_update.clicked.connect(lambda: self._check_updates(quiet=False))
        row.addWidget(self._btn_update)
        uc.addLayout(row)

        self._update_status = _lbl("", "hint")
        self._update_status.setWordWrap(True)
        uc.addWidget(self._update_status)

        self._chk_autoupdate = QCheckBox("Check for updates on startup")
        self._chk_autoupdate.setChecked(True)
        uc.addWidget(self._chk_autoupdate)
        box.addWidget(up_card)

        box.addStretch()
        return page

    # ── Action bar ───────────────────────────────────────────────────────────
    def _build_action_bar(self):
        bar = QFrame()
        bar.setObjectName("actionBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        self._btn_record = _btn("⏺  Start Recording", "btnRecord")
        self._btn_record.clicked.connect(self._toggle_record)
        self._btn_loop = _btn("▶  Start Loop", "btnLoop")
        self._btn_loop.clicked.connect(self._toggle_loop)
        row.addWidget(self._btn_record)
        row.addWidget(self._btn_loop)
        row.addStretch()

        self._progress_lbl = QLabel("")
        self._progress_lbl.setObjectName("progressLabel")
        row.addWidget(self._progress_lbl)
        return bar

    @staticmethod
    def _form():
        """A form layout with labels in a clean right-aligned column."""
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(10)
        f.setContentsMargins(0, 0, 0, 0)
        return f

    # ── settings ─────────────────────────────────────────────────────────────
    def _restore_prefs(self, s: dict):
        try:
            if s.get("timing_mode") == "fixed":
                self._radio_fixed.setChecked(True)
            self._speed_spin.setValue(float(s.get("speed", 1.0)))
            self._interval_spin.setValue(int(s.get("interval_ms", 50)))
            self._step_delay_spin.setValue(int(s.get("step_delay_ms", 0)))
            self._jitter_spin.setValue(int(s.get("jitter_pct", 0)))
            self._loop_gap_spin.setValue(int(s.get("loop_gap_ms", 0)))
            self._repeat_spin.setValue(int(s.get("repeat", 5)))
            if s.get("repeat_mode") == "repeat":
                self._radio_rep.setChecked(True)
            self._chk_mouse.setChecked(bool(s.get("record_mouse", True)))
            self._chk_moves.setChecked(bool(s.get("record_moves", False)))
            self._chk_tray.setChecked(bool(s.get("tray", True)))
            self._chk_autoupdate.setChecked(bool(s.get("auto_update_check", True)))
        except (TypeError, ValueError):
            pass  # a hand-edited settings.json shouldn't stop the app opening

        for w in (self._speed_spin, self._interval_spin, self._step_delay_spin,
                  self._jitter_spin, self._loop_gap_spin, self._repeat_spin):
            w.valueChanged.connect(self._save_prefs)
        for r in (self._radio_fixed, self._radio_rep):
            r.toggled.connect(self._save_prefs)
        for c in (self._chk_mouse, self._chk_moves, self._chk_tray,
                  self._chk_autoupdate):
            c.toggled.connect(self._save_prefs)

    def _save_prefs(self, *_):
        _save_settings({
            "record_key":    self._record_bind.raw(),
            "loop_key":      self._loop_bind.raw(),
            "panic_key":     self._panic_bind.raw(),
            "timing_mode":   "fixed" if self._radio_fixed.isChecked() else "recorded",
            "speed":         self._speed_spin.value(),
            "interval_ms":   self._interval_spin.value(),
            "step_delay_ms": self._step_delay_spin.value(),
            "jitter_pct":    self._jitter_spin.value(),
            "loop_gap_ms":   self._loop_gap_spin.value(),
            "repeat":        self._repeat_spin.value(),
            "repeat_mode":   "repeat" if self._radio_rep.isChecked() else "infinite",
            "record_mouse":  self._chk_mouse.isChecked(),
            "record_moves":  self._chk_moves.isChecked(),
            "tray":          self._chk_tray.isChecked(),
            "auto_update_check": self._chk_autoupdate.isChecked(),
            "preset_keys":   dict(self._preset_keys),
        })

    # ── chrome ───────────────────────────────────────────────────────────────
    def _update_ignore_rect(self):
        """
        Tell the recorder where our window is, so clicking Stop Recording (or
        anything else in the app) is not captured as part of the macro.
        Padded slightly to cover the drop shadow and resize border.
        """
        g = self.frameGeometry()
        pad = 8
        self._rec.ignore_rects = [
            (g.x() - pad, g.y() - pad, g.width() + pad * 2, g.height() + pad * 2)
        ]

    def moveEvent(self, event):
        super().moveEvent(event)
        if getattr(self, "_is_recording", False):
            self._update_ignore_rect()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_is_recording", False):
            self._update_ignore_rect()
        if hasattr(self, "_toast"):
            pw = self.centralWidget().width()
            self._toast.setFixedWidth(min(pw - 40, 360))
            self._toast.move((pw - self._toast.width()) // 2, 12)

    def _set_badge(self, text: str):
        colours = {
            "IDLE":      ("#1e1e30", "#6060a0"),
            "RECORDING": ("#3d1020", "#ff8aaa"),
            "LOOPING":   ("#10203d", "#8aaaff"),
            "DONE":      ("#103d10", "#8affa0"),
        }
        bg, fg = colours.get(text, colours["IDLE"])
        self._status_badge.setText(text)
        self._status_badge.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:5px; "
            f"padding:2px 10px; font-size:11px; font-weight:bold; letter-spacing:1px;"
        )

    def _on_timing_toggle(self):
        recorded = self._radio_recorded.isChecked()
        self._speed_spin.setEnabled(recorded)
        self._interval_spin.setEnabled(not recorded)

    def _on_mode_toggle(self):
        self._repeat_spin.setEnabled(self._radio_rep.isChecked())

    def _on_engine_error(self, message: str):
        self._toast.show_msg(f"⚠  {message}", "toastErr", ms=3500)

    # ── step editing ─────────────────────────────────────────────────────────
    def _clear_recording(self):
        self._steps.clear_all()
        self._on_events_changed()

    def _insert_key_step(self):
        dialog = KeyStepDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        picked = dialog.result_key()
        if not picked:
            return
        key, mods, hold = picked
        row = self._steps.macro.insert_key(
            self._steps.current_row_or_none(), key, mods, hold)
        self._steps.refresh()
        self._steps.selectRow(row)
        self._steps.changed.emit()

        combo = " + ".join([ev.pretty_key(m) for m in mods] + [ev.pretty_key(key)])
        self._toast.show_msg(f"⌨  Added {combo}", "toastDone")

    def _delay_all_steps(self):
        if not self._steps.get_events():
            QMessageBox.information(self, "No macro", "Record or load a macro first.")
            return
        ms = self._steps.fill_delays()
        if ms is not False:
            self._toast.show_msg(f"⏱  {ms} ms after every step", "toast")

    def _on_events_changed(self):
        count = self._steps.step_count()
        self._rec_count_lbl.setText(f"{count} step{'' if count == 1 else 's'}")

    # ── global hotkeys ───────────────────────────────────────────────────────
    #: Widgets that swallow keystrokes — hotkeys must not fire into them.
    _TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QComboBox)

    def _on_focus_changed(self, old, new):
        """
        Disarm global hotkeys while the user is typing into our own UI.
        Without this, typing a string containing the record key into a dialog
        starts a recording mid-sentence.
        """
        self._typing = isinstance(new, self._TEXT_INPUTS)

    def _start_global_listener(self):
        self._chord = hotkeys.ChordTracker()

        def _on_press(key):
            # Always track modifier state, even while binding/typing, so the
            # held-modifier set never gets stuck out of sync.
            chord = self._chord.press(key)
            if chord is None:
                return                       # a modifier went down; nothing to fire
            if self._binding or self._typing:
                return

            # Panic first, and unconditionally — it is the kill switch.
            if chord == self._panic_bind.raw():
                self._bridge.panic.emit()
                return
            if chord == self._record_bind.raw():
                self._bridge.record_toggle.emit()
                return
            if chord == self._loop_bind.raw():
                self._bridge.loop_toggle.emit()
                return
            for name, hk in self._preset_keys.items():
                if hk == chord:
                    self._bridge.preset_fired.emit(name)
                    return

        def _on_release(key):
            self._chord.release(key)

        self._global_listener = pynput_keyboard.Listener(
            on_press=_on_press, on_release=_on_release)
        self._global_listener.daemon = True
        self._global_listener.start()

    def _panic(self):
        """
        The kill switch. Stops everything and force-releases every key it can,
        no matter how confused the internal state is. This must never be a
        no-op — it is the last thing standing between the user and a macro that
        won't stop.
        """
        self._hard_stop()
        if self._is_recording:
            try:
                self._rec.stop()
            except Exception:
                pass
            self._is_recording = False
            self._btn_record.setText("⏺  Start Recording")
            _restyle(self._btn_record, "btnRecord")
            self._set_controls_enabled(True)
        self._set_badge("IDLE")
        self._toast.show_msg("🛑  Stopped", "toastErr")

    def _hard_stop(self):
        """Stop playback immediately and make certain no key stays held down."""
        if self._player:
            self._player.stop()
            try:
                self._player.release_all_now()   # synchronous, on this thread
            except Exception:
                pass
        _release_common_keys()                    # nuclear: unstick anything
        if self._is_looping:
            self._reset_loop_ui()
            self._progress_lbl.setText("")

    # ── recording ────────────────────────────────────────────────────────────
    def _toggle_record(self):
        if self._is_looping:
            return
        if not self._is_recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        self._is_recording = True
        self._steps.clear_all()
        self._on_events_changed()
        self._set_controls_enabled(False)

        self._rec.record_mouse = self._chk_mouse.isChecked()
        self._rec.record_moves = self._chk_moves.isChecked()
        # The recorder self-stops on a single key; use the chord's main key so a
        # plain F6 still ends recording. The global listener also stops it.
        _, main_key = hotkeys.split(self._record_bind.raw())
        self._rec.stop_key = main_key
        self._update_ignore_rect()
        self._rec.start()

        self._btn_record.setText("⏹  Stop Recording")
        _restyle(self._btn_record, "btnRecordOn")
        self._set_badge("RECORDING")
        self._toast.show_msg("🔴  Recording started", "toastRec")

    def _stop_recording(self):
        self._is_recording = False
        self._rec.stop()
        evts = self._rec.events
        self._steps.set_events(evts)
        count = ev.step_count(evts)
        self._on_events_changed()
        self._set_controls_enabled(True)

        self._btn_record.setText("⏺  Start Recording")
        _restyle(self._btn_record, "btnRecord")
        self._set_badge("IDLE")
        self._toast.show_msg(f"⏹  Stopped — {count} steps recorded", "toast")

    def _on_recorded_event(self, event: dict):
        """Live chip feedback while recording (fired on the Qt thread)."""
        if not self._is_recording:
            return
        self._steps.append_event(event)
        self._on_events_changed()

    def _set_controls_enabled(self, on: bool):
        for w in (self._speed_spin, self._interval_spin, self._step_delay_spin,
                  self._jitter_spin, self._loop_gap_spin, self._radio_inf,
                  self._radio_rep, self._radio_recorded, self._radio_fixed,
                  self._preset_list, self._chk_mouse, self._chk_moves):
            w.setEnabled(on)
        if on:
            self._on_timing_toggle()
            self._on_mode_toggle()
        else:
            self._repeat_spin.setEnabled(False)

    # ── presets ──────────────────────────────────────────────────────────────
    def _refresh_presets(self):
        try:
            all_presets = preset_store.load_all()
        except PresetError as exc:
            self._toast.show_msg(f"⚠  {exc}", "toastErr", ms=4000)
            return

        # Drop bindings whose preset no longer exists
        for gone in set(self._preset_keys) - set(all_presets):
            self._preset_keys.pop(gone, None)

        keep = self._selected_preset()
        self._preset_list.setRowCount(0)
        self._preset_list.setRowCount(len(all_presets))

        for row, (name, evts) in enumerate(all_presets.items()):
            item = QTableWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self._preset_list.setItem(row, 0, item)

            count = QTableWidgetItem(str(ev.step_count(evts)))
            count.setTextAlignment(Qt.AlignCenter)
            count.setForeground(Qt.GlobalColor.gray)
            self._preset_list.setItem(row, 1, count)

            self._preset_list.setCellWidget(row, 2, self._hotkey_cell(name))
            self._preset_list.setRowHeight(row, 42)

            if name == keep:
                self._preset_list.selectRow(row)

    def _hotkey_cell(self, name: str):
        """The bind / clear control shown in a preset row."""
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(4, 3, 4, 3)
        row.setSpacing(4)

        bind = BindButton(self._preset_keys.get(name, ""), chord=True)
        bind.setFixedWidth(120)
        bind.setToolTip(f"Press this combo anywhere to run “{name}” (e.g. Shift+5)")

        clear = QPushButton("✕")
        clear.setObjectName("resetBtn")
        clear.setFixedSize(24, 24)
        clear.setCursor(QCursor(Qt.PointingHandCursor))
        clear.setToolTip("Remove this hotkey")
        clear.setVisible(bool(self._preset_keys.get(name)))

        def _on_bound(raw, _name=name, _bind=bind, _clear=clear):
            conflict = self._hotkey_conflict(raw, _name)
            if conflict:
                QMessageBox.warning(
                    self, "Key already used",
                    f"{hotkeys.pretty(raw)} is already bound to {conflict}.")
                _bind.set_raw(self._preset_keys.get(_name, ""))
                return
            self._preset_keys[_name] = raw
            _clear.setVisible(True)
            self._save_prefs()
            self._toast.show_msg(f"⌨  {hotkeys.pretty(raw)} → {_name}", "toastDone")

        def _on_clear(_name=name, _bind=bind, _clear=clear):
            self._preset_keys.pop(_name, None)
            _bind.set_raw("")
            _clear.setVisible(False)
            self._save_prefs()

        bind.bound.connect(_on_bound)
        clear.clicked.connect(lambda _checked=False, f=_on_clear: f())
        row.addWidget(bind)
        row.addWidget(clear)
        row.addStretch()
        return cell

    def _hotkey_conflict(self, raw: str, exclude_preset=None):
        """Name of whatever already owns `raw`, or None."""
        if raw == self._record_bind.raw():
            return "Record toggle"
        if raw == self._loop_bind.raw():
            return "Loop toggle"
        if raw == self._panic_bind.raw():
            return "Panic stop"
        for name, key in self._preset_keys.items():
            if key == raw and name != exclude_preset:
                return f"the preset “{name}”"
        return None

    def _selected_preset(self):
        row = self._preset_list.currentRow()
        if row < 0:
            return None
        item = self._preset_list.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _save_preset(self):
        evts = self._steps.get_events()
        if not evts:
            QMessageBox.warning(self, "Nothing to save", "Record a macro first.")
            return
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not (ok and name.strip()):
            return
        name = name.strip()
        try:
            preset_store.save_preset(name, evts)
        except PresetError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._refresh_presets()
        self._toast.show_msg(f"💾  Saved: {name}", "toastDone")

    def _load_preset(self):
        name = self._selected_preset()
        if not name:
            return
        try:
            evts = preset_store.get_preset(name)
        except PresetError as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        self._steps.set_events(evts)
        count = ev.step_count(evts)
        self._rec_count_lbl.setText(f"{count} steps  (preset: {name})")
        self._toast.show_msg(f"📂  Loaded: {name}", "toast")

    def _delete_preset(self):
        name = self._selected_preset()
        if not name:
            return
        if QMessageBox.question(self, "Delete", f"Delete '{name}'?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            preset_store.delete_preset(name)
        except PresetError as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._refresh_presets()

    def _export_preset(self):
        name = self._selected_preset()
        if not name:
            QMessageBox.information(self, "No preset", "Select a preset to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export preset", f"{name}.nmacro", "Nickher macro (*.nmacro)")
        if not path:
            return
        try:
            preset_store.export_preset(name, path)
        except PresetError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self._toast.show_msg(f"⬆  Exported: {name}", "toastDone")

    def _import_preset(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import preset", "", "Nickher macro (*.nmacro *.json)")
        if not path:
            return
        try:
            name = preset_store.import_preset(path)
        except PresetError as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self._refresh_presets()
        self._toast.show_msg(f"⬇  Imported: {name}", "toastDone")

    # ── playback ─────────────────────────────────────────────────────────────
    def _toggle_loop(self):
        """
        Start Loop button / loop hotkey. If anything is playing — the editor
        macro OR a preset — this STOPS it. Stop must always mean stop; it must
        never quietly start a different loop, which is how it can feel like the
        macro won't quit.
        """
        if self._is_recording:
            return
        if self._is_looping:
            self._stop_loop()
            return
        evts = self._steps.get_events()
        if not evts:
            QMessageBox.information(self, "No macro", "Record or load a preset first.")
            return
        self._start_loop(evts, EDITOR)

    def _trigger_preset(self, name: str):
        """A preset hotkey fired. Same key again stops it; a different key swaps."""
        if self._is_recording:
            return
        if self._is_looping:
            was = self._active
            self._stop_loop()
            if was == name:
                return  # same key pressed twice = toggle off
        try:
            evts = preset_store.get_preset(name)
        except PresetError as exc:
            self._toast.show_msg(f"⚠  {exc}", "toastErr", ms=3500)
            return
        if not evts:
            self._toast.show_msg(f"⚠  “{name}” is empty", "toastErr")
            return
        self._start_loop(evts, name)

    def _start_loop(self, evts, source):
        self._is_looping = True
        self._active = source
        # Only mirror playback position when the running macro is the one on screen
        on_step = (lambda i: self._bridge.step_update.emit(i)) if source == EDITOR else None

        self._player = Player(
            events=evts,
            timing_mode="fixed" if self._radio_fixed.isChecked() else "recorded",
            speed=self._speed_spin.value(),
            fixed_interval_ms=self._interval_spin.value(),
            repeat=0 if self._radio_inf.isChecked() else self._repeat_spin.value(),
            loop_gap_ms=self._loop_gap_spin.value(),
            step_delay_ms=self._step_delay_spin.value(),
            jitter_pct=self._jitter_spin.value(),
            on_done=lambda: self._bridge.playback_done.emit(),
            on_cycle=lambda c, t: self._bridge.cycle_update.emit(c, t),
            on_step=on_step,
            on_error=lambda exc: self._bridge.engine_error.emit(str(exc)),
        )
        threading.Thread(target=self._player.play, daemon=True).start()

        label = "the current macro" if source == EDITOR else f"“{source}”"
        self._btn_loop.setText("⏹  Stop Loop")
        _restyle(self._btn_loop, "btnLoopOn")
        self._btn_record.setEnabled(False)
        self._set_badge("LOOPING")
        self._progress_lbl.setText(f"Running {label}…")
        self._toast.show_msg(f"▶  Playing {label}", "toastLoop")
        self._sync_tray()

    def _reset_loop_ui(self):
        self._is_looping = False
        self._active = None
        self._btn_loop.setText("▶  Start Loop")
        _restyle(self._btn_loop, "btnLoop")
        self._btn_record.setEnabled(True)
        self._steps.clear_highlight()
        self._sync_tray()

    def _stop_loop(self):
        if self._player:
            self._player.stop()
            try:
                self._player.release_all_now()
            except Exception:
                pass
        self._reset_loop_ui()
        self._set_badge("IDLE")
        self._progress_lbl.setText("")
        self._toast.show_msg("⏹  Loop stopped", "toast")

    def _on_playback_done(self):
        if not self._is_looping:
            return  # already handled by _stop_loop
        self._reset_loop_ui()
        self._set_badge("DONE")
        runs = "∞" if self._radio_inf.isChecked() else str(self._repeat_spin.value())
        self._progress_lbl.setText(f"Done — {runs} run(s) completed ✓")
        self._toast.show_msg(f"✅  Completed {runs}×", "toastDone", ms=3000)
        QTimer.singleShot(3000, lambda: self._set_badge("IDLE"))

    def _on_cycle_update(self, current: int, total: int):
        if total == 0:
            self._progress_lbl.setText(f"Loop #{current}")
        else:
            self._progress_lbl.setText(f"Run {current} / {total}")

    def _on_step_update(self, index: int):
        if self._is_looping and self._active == EDITOR:
            self._steps.highlight_event(index)

    # ── updates ──────────────────────────────────────────────────────────────
    def _check_updates(self, quiet=True):
        """
        Ask GitHub whether a newer release exists. Runs off the UI thread;
        `quiet` suppresses "you're up to date" and error popups for the
        automatic check on startup.
        """
        if getattr(self, "_update_busy", False):
            return
        self._update_busy = True
        self._btn_update.setEnabled(False)
        self._update_status.setText("Checking…")

        def work():
            try:
                info = updater.check()
                self._bridge.update_result.emit(info, "")
            except updater.UpdateError as exc:
                self._bridge.update_result.emit(None, str(exc))
            except Exception as exc:                      # never kill the thread
                self._bridge.update_result.emit(None, f"Unexpected error: {exc}")

        self._update_quiet = quiet
        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, info, error):
        self._update_busy = False
        self._btn_update.setEnabled(True)

        if error:
            self._update_status.setText(error)
            if not self._update_quiet:
                QMessageBox.warning(self, "Update check failed", error)
            return

        if info is None:
            self._update_status.setText(f"Up to date (v{__version__}).")
            if not self._update_quiet:
                self._toast.show_msg("✅  You're on the latest version", "toastDone")
            return

        self._update_status.setText(f"Version {info.version} is available.")

        if not updater.can_self_update():
            QMessageBox.information(
                self, "Running from source",
                "This copy runs from source, so it can't update itself.\n"
                "Pull the new version with git instead.")
            return

        # Prefer the installer — it is the reliable way to replace a running app.
        self._update_via_installer = info.has_installer and not paths.is_portable()
        which = "installer" if self._update_via_installer else "exe"
        dl_size = info.setup_size if self._update_via_installer else info.exe_size

        notes = f"\n\n{info.notes[:600]}" if info.notes else ""
        size = f" ({dl_size / 1e6:.0f} MB)" if dl_size else ""
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(
            f"Version {info.version} is available — you have {__version__}.{size}{notes}")
        update_btn = box.addButton("Update now", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.setDefaultButton(update_btn)
        box.exec()
        if box.clickedButton() is not update_btn:
            return

        self._start_download(info, which)

    def _start_download(self, info, which):
        self._btn_update.setEnabled(False)
        self._update_status.setText("Downloading…")

        def work():
            try:
                path = updater.download(
                    info, which=which,
                    progress=lambda done, total:
                        self._bridge.update_progress.emit(done, total))
                self._bridge.update_ready.emit(path, "")
            except updater.UpdateError as exc:
                self._bridge.update_ready.emit("", str(exc))
            except Exception as exc:
                self._bridge.update_ready.emit("", f"Unexpected error: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_update_progress(self, done, total):
        if total:
            self._update_status.setText(
                f"Downloading… {done / 1e6:.0f} / {total / 1e6:.0f} MB")
        else:
            self._update_status.setText(f"Downloading… {done / 1e6:.0f} MB")

    def _on_update_ready(self, path, error):
        self._btn_update.setEnabled(True)
        if error:
            self._update_status.setText(error)
            QMessageBox.warning(self, "Update failed", error)
            return

        try:
            if getattr(self, "_update_via_installer", False):
                self._update_status.setText("Verified. Launching installer…")
                updater.run_installer(path)
            else:
                self._update_status.setText("Verified. Restarting to install…")
                updater.apply_update(path)
        except updater.UpdateError as exc:
            self._update_status.setText(str(exc))
            QMessageBox.warning(self, "Update failed", str(exc))
            return

        # Quit so the installer (or swap helper) can replace the running exe.
        # A running loop must not survive into the relaunched copy.
        self._quitting = True
        self.close()

    # ── system tray ──────────────────────────────────────────────────────────
    def _build_tray(self):
        self._tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            # Grey it out without persisting the change — this is a missing
            # capability, not the user choosing to turn the setting off.
            self._chk_tray.blockSignals(True)
            self._chk_tray.setEnabled(False)
            self._chk_tray.setChecked(False)
            self._chk_tray.blockSignals(False)
            self._chk_tray.setToolTip("No system tray on this desktop")
            return

        self._tray = QSystemTrayIcon(self.windowIcon(), self)
        self._tray.setToolTip("Nickher Macro")

        menu = QMenu()
        self._act_show = QAction("Show window", self)
        self._act_show.triggered.connect(self._restore_window)
        self._act_loop = QAction("Start loop", self)
        self._act_loop.triggered.connect(self._toggle_loop)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(self._act_show)
        menu.addAction(self._act_loop)
        menu.addSeparator()
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._restore_window()

    def _sync_tray(self):
        if self._tray:
            self._act_loop.setText("Stop loop" if self._is_looping else "Start loop")

    def _restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def surface_from_anywhere(self):
        """Called when a second copy was launched — bring this one to the front."""
        self._restore_window()

    def _quit(self):
        self._quitting = True
        self.close()

    def closeEvent(self, event):
        # Closing the window always stops any playback first. Leaving a loop
        # running behind a closed window is exactly the "it kept typing after
        # I closed it" trap — the window is the only place to stop it.
        if self._is_looping:
            self._hard_stop()
        if self._is_recording:
            self._rec.stop()
            self._is_recording = False

        # Hiding to tray keeps only the hotkeys alive, never a running macro.
        if not self._quitting and self._tray and self._chk_tray.isChecked():
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "Nickher Macro",
                "Hotkeys stay active in the tray. Quit from the tray icon.",
                QSystemTrayIcon.Information, 4000)
            return

        try:
            self._global_listener.stop()
        except Exception:
            pass
        if self._tray:
            self._tray.hide()
        event.accept()
        QApplication.quit()

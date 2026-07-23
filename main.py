import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from main_window import MainWindow

#: One running copy only. A macro tool that hooks the keyboard must never run in
#: duplicate — each copy adds its own global hotkeys and its own playback thread,
#: so pressing the loop key would start several loops at once and stopping one
#: window would leave the others typing with no way to reach them.
SINGLE_INSTANCE_KEY = "NickherMacro-single-instance-v1"


def resource_path(relative: str) -> str:
    """Return correct path whether running from source or PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _already_running() -> bool:
    """True if another copy answered on the single-instance channel."""
    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return True
    return False


def _listen(window) -> QLocalServer:
    """Own the single-instance channel; surface the window when pinged."""
    # A prior crash can leave a stale socket that blocks listen(); clear it.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)

    def _on_connection():
        conn = server.nextPendingConnection()
        if conn:
            conn.readAll()
            window.surface_from_anywhere()
            conn.disconnectFromServer()

    server.newConnection.connect(_on_connection)
    return server


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Nickher Macro")
    # Closing the window must not quit the app while it lives in the tray; we
    # decide when to actually exit.
    app.setQuitOnLastWindowClosed(False)

    if _already_running():
        # Another copy is up and has been told to show itself. Leave quietly.
        sys.exit(0)

    icon_path = resource_path("ncicon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()
    if os.path.exists(icon_path):
        win.setWindowIcon(QIcon(icon_path))

    server = _listen(win)          # kept alive for the process lifetime
    win.show()
    sys.exit(app.exec())

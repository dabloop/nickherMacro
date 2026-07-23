import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from main_window import MainWindow


def resource_path(relative: str) -> str:
    """Return correct path whether running from source or PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Nickher Macro")

    icon_path = resource_path("ncicon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()

    if os.path.exists(icon_path):
        win.setWindowIcon(QIcon(icon_path))

    win.show()
    sys.exit(app.exec())

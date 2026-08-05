from __future__ import annotations

import ctypes
import logging
import os
import sys
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

from src.ui.main_window import APP_STYLESHEET, MainWindow, create_dark_palette
from src.utils.logger import setup_logger

def show_fatal_error(summary: str, details: str) -> None:
    """Report startup failures even when the Qt window could not be constructed."""
    message = f"{summary}\n\n상세 정보는 로그 파일을 확인해 주세요.\n{details}"
    try:
        QMessageBox.critical(None, "FileOps Hub 시작 오류", message)
    except Exception:
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, "FileOps Hub 시작 오류", 0x10)

def handle_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.getLogger(__name__).critical("Unhandled application exception:\n%s", details)
    show_fatal_error("예기치 않은 오류로 프로그램을 계속 실행할 수 없습니다.", str(exc_value))

def main() -> int:
    setup_logger()
    sys.excepthook = handle_unhandled_exception

    if sys.platform == "win32":
        try:
            myappid = "fileops.hub.desktop.v1"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    try:
        app = QApplication(sys.argv)

        icon_path = os.path.join(SRC_PATH, "assets", "icon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))

        app.setStyle("Fusion")
        app.setPalette(create_dark_palette())
        app.setStyleSheet(APP_STYLESHEET)
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as exc:
        details = traceback.format_exc()
        logging.getLogger(__name__).critical("Application startup failed:\n%s", details)
        show_fatal_error("프로그램을 시작하지 못했습니다.", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

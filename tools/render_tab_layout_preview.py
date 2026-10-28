"""Render the actual nested-tab UI using in-memory settings, no real application data."""
import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", choices=("ko", "en", "pl"), default="ko")
    parser.add_argument("--subtab", choices=("eml", "pdf", "ocr"), default="eml")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fileops-tabs-render-") as folder:
        os.environ.update(LOCALAPPDATA=folder, APPDATA=folder, QT_QPA_PLATFORM="offscreen")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from PyQt6.QtGui import QFontDatabase
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        for name in ("segoeui.ttf", "malgun.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
        from src.ui.main_window import MainWindow, create_dark_palette
        from src.ui.task_tab import TaskTab
        from tools.test_tab_layout import FakeConfig

        app.setPalette(create_dark_palette())
        config = FakeConfig()
        config.values["ui_language"] = args.language
        try:
            with (patch("src.ui.main_window.ConfigManager", return_value=config),
                  patch.object(MainWindow, "setup_system_tray"),
                  patch.object(MainWindow, "trigger_update_check"),
                  patch.object(TaskTab, "refresh_readiness")):
                window = MainWindow()
            window.task_tab.schedule_timer.stop()
            window.task_tab.run_health_timer.stop()
            window.select_feature_tab(getattr(window, f"{args.subtab}_tab"))
            window.show()
            app.processEvents()
            if not window.grab().save(str(output)):
                raise RuntimeError("Could not save the rendered tab layout.")
            window.hide()
            window.deleteLater()
            app.processEvents()
            print(output)
        finally:
            logging.shutdown()


if __name__ == "__main__":
    main()

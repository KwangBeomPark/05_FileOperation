"""Render FileOps screens using in-memory settings, not real application data."""
import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", choices=("ko", "en", "pl"), default="ko")
    parser.add_argument("--subtab", choices=("eml", "pdf", "ocr"), default="eml")
    parser.add_argument("--tab", choices=("sa", "task", "sync", "collect_sync", "cleanup"), default="sa")
    parser.add_argument("--compact", action="store_true", help="Render at the main window's minimum size.")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fileops-tabs-render-") as folder:
        os.environ.update(LOCALAPPDATA=folder, APPDATA=folder, QT_QPA_PLATFORM="offscreen")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFont, QFontDatabase
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        for name in ("segoeui.ttf", "malgun.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont("Malgun Gothic" if args.language == "ko" else "Segoe UI", 10))
        from src.ui.main_window import MainWindow, create_dark_palette
        from src.ui.task_tab import TaskTab
        from src.ui.version_cleanup_dialog import VersionCleanupDialog
        from tools.test_tab_layout import FakeConfig

        app.setPalette(create_dark_palette())
        config = FakeConfig()
        config.values["ui_language"] = args.language
        config.values["sync_groups"] = [
            {"id": "reports", "name": "Reports", "folders": [r"C:\Example\Reports", r"C:\Example\Archive"]},
            {"id": "draft", "name": "Draft", "folders": [r"C:\Example\Draft"]},
        ]
        if args.tab == "collect_sync":
            from src.core.collect_sync_config import new_collect_group

            group = new_collect_group("Reports")
            group.update(sources=[r"C:\Example\Reports"], keywords=["report"], target=r"C:\Example\Collected")
            config.values["collect_sync_groups"] = [group]
        try:
            with (patch("src.ui.main_window.ConfigManager", return_value=config),
                  patch.object(MainWindow, "setup_system_tray"),
                  patch.object(MainWindow, "trigger_update_check"),
                  patch.object(TaskTab, "refresh_readiness")):
                window = MainWindow()
            window.task_tab.schedule_timer.stop()
            window.task_tab.run_health_timer.stop()
            feature = args.subtab if args.tab == "sa" else ("sync" if args.tab == "cleanup" else args.tab)
            window.select_feature_tab(getattr(window, f"{feature}_tab"))
            if args.compact:
                window.resize(window.minimumSize())
            window.show()
            capture = window
            if args.tab == "cleanup":
                capture = VersionCleanupDialog([r"C:\Example\Reports"], args.language, window)
                capture.worker = SimpleNamespace(wait=lambda: None, cancelled=False)
                capture.scan_finished([
                    {"folder": r"C:\Example\Reports", "filename": f"report_v0.{i}.xlsx",
                     "date": f"0.{i}", "latest_date": "1.0"}
                    for i in range(1, 4)
                ], None)
                capture.worker = None
                capture.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
                capture.show()
            app.processEvents()
            if not capture.grab().save(str(output)):
                raise RuntimeError("Could not save the rendered screen.")
            if capture is not window:
                capture.hide()
                capture.deleteLater()
            window.hide()
            window.deleteLater()
            app.processEvents()
            print(output)
        finally:
            logging.shutdown()


if __name__ == "__main__":
    main()

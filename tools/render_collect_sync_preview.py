"""Render the real MainWindow with synthetic collection results, without filesystem jobs."""

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("ko", "en", "pl"), default="ko")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--results", type=int, default=5)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--unverified-recovery", action="store_true")
    parser.add_argument(
        "--recovery",
        action="store_true",
        help="Show the real recovery dialog with temporary example files",
    )
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory() as temporary:
        os.environ["LOCALAPPDATA"] = str(Path(temporary) / "local")
        os.environ["APPDATA"] = str(Path(temporary) / "roaming")
        from PyQt6.QtGui import QFont, QFontDatabase
        from PyQt6.QtWidgets import QApplication

        from src.core.collect_sync import CollectAction, CollectReport, CollectState
        from src.core.collect_sync_config import new_collect_group
        from src.ui.collect_recovery_dialog import CollectRecoveryDialog
        from src.ui.main_window import APP_STYLESHEET, MainWindow
        from src.ui.task_tab import TaskTab
        from tools.test_collect_sync_ui import MemoryConfig, wait_until

        app = QApplication.instance() or QApplication([])
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("segoeui.ttf", "malgun.ttf"):
            QFontDatabase.addApplicationFont(str(fonts / name))
        app.setFont(QFont("Malgun Gothic" if args.language == "ko" else "Segoe UI", 10))
        group = new_collect_group("Daily reports")
        group.update(
            sources=[r"C:\Example\Reports", r"C:\Example\Finance"],
            keywords=["report", "invoice"],
            target=r"C:\Example\Collected",
            schedule_enabled=True,
            schedule_time="00:00",
        )
        config = MemoryConfig([group], args.language)
        with (
            patch("src.ui.main_window.ConfigManager", return_value=config),
            patch.object(MainWindow, "setup_system_tray"),
            patch.object(MainWindow, "trigger_update_check"),
            patch.object(TaskTab, "refresh_readiness"),
        ):
            window = MainWindow()
        window.task_tab.schedule_timer.stop()
        tab = window.collect_sync_tab
        tab.schedule_timer.stop()
        tab._last_report = CollectReport(
            [
                CollectAction("copy", r"C:\Example\Reports\report.xlsx", "report.xlsx"),
                CollectAction(
                    "replace",
                    r"C:\Example\Finance\invoice.xlsx",
                    "invoice.xlsx",
                    "invoice (01).xlsx",
                ),
                CollectAction(
                    "unchanged",
                    r"C:\Example\Reports\report-final.pdf",
                    "report-final.pdf",
                ),
                CollectAction(
                    "target_newer",
                    r"C:\Example\Reports\report-edited.xlsx",
                    "report-edited.xlsx",
                ),
                CollectAction(
                    "error",
                    r"C:\Example\Finance\invoice-locked.xlsx",
                    "invoice-locked.xlsx",
                ),
            ]
        )
        tab._result_group_id = group["id"]
        tab._result_group_name = group["name"]
        if args.results > len(tab._last_report.actions):
            tab._last_report.actions.extend(
                CollectAction(
                    "copy",
                    f"C:/Example/report-{index:04d}.txt",
                    f"report-{index:04d}.txt",
                )
                for index in range(len(tab._last_report.actions), args.results)
            )
        tab._report_dry_run = True
        tab._result_page = args.page - 1
        tab._status_key = "collect_preview_note"
        tab.refresh_language()
        window.tab_widget.setCurrentWidget(tab)
        window.setStyleSheet(APP_STYLESHEET)
        window.resize(1600, 1050)
        window.show()
        app.processEvents()
        capture = window
        dialog = None
        if args.recovery or args.unverified_recovery:
            example = Path(temporary) / "example"
            example.mkdir()
            source = example / "report.xlsx"
            target = example / "collected" / "report.xlsx"
            target.parent.mkdir()
            source.write_text("preview fixture", encoding="utf-8")
            target.write_text("preview fixture", encoding="utf-8")
            state = CollectState(example / "collect_sync_state.json")
            state.pending = {
                "target": str(target.parent),
                "source": str(source),
                "name": target.name,
            }
            state.save()
            if args.unverified_recovery:
                target.parent.rename(example / "renamed-collected")
            dialog = CollectRecoveryDialog(state.path, args.language, window)
            dialog.show()
            wait_until(lambda: dialog.preview is not None)
            app.processEvents()
            capture = dialog
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not capture.grab().save(str(args.output.resolve())):
            raise RuntimeError("Cannot save widget preview")
        print(args.output.resolve())
        if dialog:
            dialog.reject()
            dialog.deleteLater()
        window.hide()
        window.deleteLater()
        app.processEvents()
        logging.shutdown()


if __name__ == "__main__":
    main()

"""Render the real summary widget with fictional data; never start the application."""
import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", choices=("en", "ko", "pl"), default="ko")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fileops-summary-render-") as folder:
        os.environ["LOCALAPPDATA"] = folder
        os.environ["APPDATA"] = folder
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QFontDatabase
        from src.core.run_summary import ChangeEntry, RunChangeSummary
        from src.ui.main_window import APP_STYLESHEET
        from src.ui.run_summary_dialog import RunSummaryDialog

        app = QApplication.instance() or QApplication([])
        # Offscreen Qt may not enumerate Windows fonts; explicitly load installed
        # font files for the render only. No fonts/settings are installed or changed.
        for name in ("segoeui.ttf", "malgun.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
        app.setStyleSheet(APP_STYLESHEET)
        summary = RunChangeSummary(
            entries=[
                ChangeEntry("sync", "Daily documents", "copy", r"C:\Example\Source\Report.xlsx", r"C:\Example\Team\Report.xlsx"),
                ChangeEntry("sync", "Daily documents", "archive", r"C:\Example\Team\Old.xlsx", r"C:\Example\Team\to be deleted\Old.xlsx"),
                ChangeEntry("sync", "Archive cleanup", "delete", r"C:\Example\Old\Draft.xlsx", ""),
                ChangeEntry("bypass", "", "convert", r"C:\Example\Source\Invoice.pdf", r"C:\Example\Output\Invoice.html"),
                ChangeEntry("ocr", "", "overwrite", r"C:\Example\Images\Scan.png", r"C:\Example\Images\Scan.txt"),
            ],
            counts={"copy": 1, "archive": 1, "delete": 1, "convert": 1, "overwrite": 1},
            risks=["delete_policy", "move_sources", "overwrite_text"],
            notes=["sync_estimate", "ocr_names"], total_entries=5,
        )
        dialog = RunSummaryDialog(summary, args.language)
        dialog.show()
        app.processEvents()
        if not dialog.grab().save(str(output)):
            raise RuntimeError("Could not save the rendered preview.")
        dialog.close()
        app.processEvents()
        print(output)
        logging.shutdown()


if __name__ == "__main__":
    main()

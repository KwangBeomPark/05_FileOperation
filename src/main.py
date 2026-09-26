from __future__ import annotations

import ctypes
import logging
import multiprocessing
import os
import sys
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# In a frozen build, child probe processes must be diverted before importing
# Qt and constructing any desktop objects.
if __name__ == "__main__":
    multiprocessing.freeze_support()

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

from src.ui.main_window import APP_STYLESHEET, MainWindow, create_dark_palette
from src.ui.single_instance import SingleInstanceController
from src.utils.logger import setup_logger


SINGLE_INSTANCE_NAME = "fileops.hub.desktop.v1"


def parse_startup_arguments(argv):
    """Remove FileOps-specific switches before passing arguments to Qt."""
    start_in_tray = "--tray" in argv[1:]
    qt_argv = [argv[0], *(arg for arg in argv[1:] if arg not in ("--tray", "--headless-run"))]
    return qt_argv, start_in_tray

def run_headless(config_path: str | None = None) -> int:
    """Execute configured integrated tasks headlessly without displaying GUI."""
    from src.utils.config_manager import ConfigManager
    from src.core.task_runner import TaskRunner, RunnerCallbacks
    from src.core.task_contracts import (
        RunPlan,
        TaskStep,
        SyncGroupConfig,
        SyncRunConfig,
        OcrRunConfig,
    )
    from src.utils.logger import get_logger

    logger = get_logger()
    logger.info("Starting FileOps Hub in Headless CLI mode.")
    config = ConfigManager(config_path) if config_path else ConfigManager()

    configs = {}
    sync_groups_data = config.get("sync_groups", [])
    valid_groups = [g for g in sync_groups_data if len(g.get("folders", [])) >= 2]
    if valid_groups:
        configs[TaskStep.SYNC] = SyncRunConfig(
            sync_groups=[
                SyncGroupConfig(
                    name=g.get("name", "Group"),
                    folders=g.get("folders", []),
                    move_to_deleted=bool(g.get("move_to_deleted", True)),
                    archive_folder_name=str(g.get("archive_folder_name", "to be deleted")),
                    exclude_patterns=list(g.get("exclude_patterns", [])),
                    include_subfolders=bool(g.get("include_subfolders", False)),
                    sync_mode=str(g.get("sync_mode", "two_way")),
                )
                for g in valid_groups
            ]
        )

    ocr_rule_mode = str(config.get("ocr_rule_mode", "promotion") or "promotion")
    custom_pattern = str(config.get("ocr_custom_pattern", "") or "")
    rename_template = str(config.get("ocr_rename_template", "{match}") or "{match}")
    export_txt = bool(config.get("ocr_export_txt", False))
    ocr_images = list(config.get("ocr_image_paths", []))
    chain_outputs = bool(config.get("task_chain_outputs", False))
    if ocr_images or chain_outputs:
        configs[TaskStep.OCR] = OcrRunConfig(
            image_paths=ocr_images,
            rule_mode=ocr_rule_mode,
            custom_pattern=custom_pattern,
            rename_template=rename_template,
            export_txt=export_txt,
        )

    enabled_steps_values = config.get("task_enabled_steps", [TaskStep.SYNC.value])
    enabled_steps = []
    for val in enabled_steps_values:
        try:
            step = TaskStep(val)
            if step in configs:
                enabled_steps.append(step)
        except ValueError:
            pass

    if not enabled_steps:
        enabled_steps = list(configs.keys())

    plan = RunPlan(
        configs=configs,
        step_order=enabled_steps,
        chain_outputs=chain_outputs,
    )

    runner = TaskRunner(config, plan)
    callbacks = RunnerCallbacks(
        log=lambda msg: print(msg, flush=True),
        step_progress=lambda cur, tot, msg: print(f"[{cur}/{tot}] {msg}", flush=True),
    )
    report = runner.run(callbacks)
    print("\n" + report.report_body)
    return 0 if report.overall_success else 1

def show_fatal_error(summary: str, details: str) -> None:
    """Report startup failures even when the Qt window could not be constructed."""
    message = f"{summary}\n\nCheck the log file for details.\n{details}"
    try:
        QMessageBox.critical(None, "FileOps Hub Startup Error", message)
    except Exception:
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, "FileOps Hub Startup Error", 0x10)

def handle_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.getLogger(__name__).critical("Unhandled application exception:\n%s", details)
    show_fatal_error("The application cannot continue because of an unexpected error.", str(exc_value))

def main() -> int:
    setup_logger()
    sys.excepthook = handle_unhandled_exception

    if "--headless-run" in sys.argv:
        return run_headless()

    if sys.platform == "win32":
        try:
            myappid = "fileops.hub.desktop.v1"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    try:
        qt_argv, start_in_tray = parse_startup_arguments(sys.argv)
        app = QApplication(qt_argv)
        instance_controller = SingleInstanceController.acquire(
            SINGLE_INSTANCE_NAME,
            show_existing=not start_in_tray,
        )
        if instance_controller is None:
            return 0

        runtime_root = getattr(sys, "_MEIPASS", PROJECT_ROOT)
        icon_path = os.path.join(runtime_root, "src", "assets", "icon.ico")
        app_icon = QIcon()
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            app.setWindowIcon(app_icon)

        app.setStyle("Fusion")
        app.setPalette(create_dark_palette())
        app.setStyleSheet(APP_STYLESHEET)
        window = MainWindow()
        instance_controller.activation_requested.connect(window.show_from_tray)
        if not app_icon.isNull():
            # QApplication 상속에만 의존하지 않고 각 Windows 표면에 명시적으로 적용합니다.
            window.setWindowIcon(app_icon)
            if window.tray_icon:
                window.tray_icon.setIcon(app_icon)
        if start_in_tray and window.tray_icon and window.tray_icon.isVisible():
            window.hide()
        else:
            window.show()
        exit_code = app.exec()
        instance_controller.close()
        return exit_code
    except Exception as exc:
        details = traceback.format_exc()
        logging.getLogger(__name__).critical("Application startup failed:\n%s", details)
        show_fatal_error("The application could not be started.", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

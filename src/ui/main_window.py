from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QAction, QColor, QPalette
from PyQt6.QtCore import QThread, pyqtSignal, Qt
import os
import tempfile

from src.ui.pdf_tab import PDFTab
from src.ui.ocr_tab import OCRTab
from src.ui.eml_tab import EMLTab
from src.ui.sync_tab import SyncTab
from src.ui.bypass_tab import BypassTab
from src.ui.task_tab import TaskTab
from src.ui.settings_dialog import SettingsDialog
from src.ui.i18n import get_app_language, localize_widget_tree, tr
from src.core.updater import AutoUpdater
from src.version import APP_VERSION_TAG
from src.utils.config_manager import ConfigManager
from src.utils.logger import get_logger

logger = get_logger()

APP_STYLESHEET = """
QMainWindow, QDialog, QMessageBox, QInputDialog {
    background-color: #1e1e1e;
}
QTabWidget::pane {
    border: 1px solid #3e3e3e;
    background-color: #2d2d2d;
    top: -1px;
}
QTabBar::tab {
    background-color: #1e1e1e;
    color: #a0a0a0;
    padding: 10px 18px;
    border: 1px solid #3e3e3e;
    border-bottom: none;
    min-width: 130px;
}
QTabBar::tab:selected {
    background-color: #2d2d2d;
    color: #38bdf8;
    font-weight: bold;
}
QTabBar::tab:hover {
    background-color: #252526;
    color: #e2e8f0;
}
QGroupBox {
    border: 1px solid #3e3e3e;
    border-radius: 6px;
    margin-top: 15px;
    padding: 16px 10px 10px 10px;
    background-color: #252526;
    font-size: 10.5pt;
    font-weight: bold;
    color: #f1f5f9;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #38bdf8;
}
QLineEdit, QListWidget, QTextEdit, QTableWidget, QTimeEdit, QDateEdit, QDateTimeEdit, QSpinBox, QDoubleSpinBox {
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    background-color: #1e1e1e;
    color: #e2e8f0;
    padding: 5px;
    gridline-color: #2d2d2d;
}
QLineEdit:read-only {
    background-color: #252526;
    color: #8a949e;
}
QPushButton {
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    background-color: #2d2d2d;
    color: #e2e8f0;
    padding: 7px 12px;
    min-height: 28px;
}
QPushButton:hover {
    background-color: #3e3e3e;
}
QPushButton:disabled {
    color: #64748b;
    background-color: #1e1e1e;
    border-color: #2d2d2d;
}
QPushButton[variant="primary"] {
    background-color: #0e639c;
    color: #ffffff;
    border-color: #1177bb;
    font-weight: bold;
}
QPushButton[variant="primary"]:hover {
    background-color: #1177bb;
}
QPushButton[variant="success"] {
    background-color: #16a34a;
    color: #ffffff;
    border-color: #15803d;
    font-weight: bold;
}
QPushButton[variant="success"]:hover {
    background-color: #15803d;
}
QPushButton[variant="danger"] {
    background-color: #b91c1c;
    color: #ffffff;
    border-color: #991b1b;
    font-weight: bold;
}
QPushButton[variant="danger"]:hover {
    background-color: #991b1b;
}
QProgressBar {
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    background-color: #252526;
    height: 18px;
    text-align: center;
    color: #ffffff;
}
QProgressBar::chunk {
    border-radius: 3px;
    background-color: #0e639c;
}
QHeaderView::section {
    background-color: #252526;
    color: #e2e8f0;
    border: 1px solid #3e3e3e;
    padding: 6px;
    font-weight: bold;
}
QComboBox {
    background-color: #1e1e1e;
    color: #e2e8f0;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 5px 10px;
}
QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    color: #e2e8f0;
    selection-background-color: #0e639c;
    selection-color: #ffffff;
    border: 1px solid #3e3e3e;
}
QLabel {
    color: #e2e8f0;
    font-size: 9.5pt;
}
QGroupBox QLabel {
    font-weight: bold;
    color: #cbd5e1;
}
QMenuBar {
    background-color: #1e1e1e;
    color: #e2e8f0;
    border-bottom: 1px solid #3e3e3e;
}
QMenuBar::item {
    background-color: transparent;
    padding: 5px 10px;
}
QMenuBar::item:selected {
    background-color: #2d2d2d;
}
QMenu {
    background-color: #1e1e1e;
    color: #e2e8f0;
    border: 1px solid #3e3e3e;
}
QMenu::item {
    padding: 5px 20px;
}
QMenu::item:selected {
    background-color: #0e639c;
    color: #ffffff;
}
QStatusBar {
    background-color: #1e1e1e;
    color: #a0a0a0;
    border-top: 1px solid #3e3e3e;
}
QScrollBar:vertical {
    background: #1e1e1e;
    width: 12px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #424242;
    min-height: 20px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #4f4f4f;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    background: none;
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background: #1e1e1e;
    height: 12px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #424242;
    min-width: 20px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: #4f4f4f;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    background: none;
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
QCheckBox {
    color: #cbd5e1;
}
QToolTip {
    background-color: #252526;
    color: #e2e8f0;
    border: 1px solid #3e3e3e;
}
QFrame#UpdateBanner {
    background-color: #17324d;
    border-bottom: 1px solid #25638f;
}
QLabel#UpdateBannerTitle {
    color: #ffffff;
    font-weight: bold;
    font-size: 10.5pt;
}
QLabel#UpdateBannerBody {
    color: #dbeafe;
}
QPushButton#UpdateBannerPrimary {
    background-color: #38bdf8;
    color: #0f172a;
    border: 1px solid #7dd3fc;
    font-weight: bold;
    min-height: 26px;
    padding: 5px 10px;
}
QPushButton#UpdateBannerSecondary {
    background-color: #214760;
    color: #e0f2fe;
    border: 1px solid #3b7190;
    min-height: 26px;
    padding: 5px 10px;
}
QPushButton#UpdateBannerClose {
    background-color: transparent;
    color: #dbeafe;
    border: none;
    font-size: 12pt;
    font-weight: bold;
    min-width: 28px;
    padding: 4px;
}
QPushButton#UpdateBannerClose:hover {
    background-color: #2b5874;
}
"""


def create_dark_palette():
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#252526"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#252526"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2d2d2d"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0e639c"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return palette


class UpdateWorker(QThread):
    finished = pyqtSignal(bool, str, str, str, str) # has_update, latest_version, download_url, release_notes, error
    
    def __init__(self, current_version=APP_VERSION_TAG):
        super().__init__()
        self.updater = AutoUpdater(current_version=current_version)

    def run(self):
        has_update, latest, url, notes = self.updater.check_for_updates()
        self.finished.emit(has_update, latest, url or "", notes, self.updater.last_error)


class DownloadWorker(QThread):
    progress = pyqtSignal(int, int) # downloaded_bytes, total_bytes
    finished = pyqtSignal(bool, str) # success, error_message or saved_path
    
    def __init__(self, updater, download_url, dest_path):
        super().__init__()
        self.updater = updater
        self.download_url = download_url
        self.dest_path = dest_path
        self._is_cancelled = False
        
    def run(self):
        def progress_cb(downloaded, total):
            if self._is_cancelled:
                raise InterruptedError("Download cancelled by user.")
            self.progress.emit(downloaded, total)
            
        try:
            if not self.updater.latest_asset:
                raise RuntimeError("검증된 업데이트 설치 파일 정보가 없습니다.")
            self.updater.download_file(
                self.download_url,
                self.dest_path,
                self.updater.latest_asset.sha256,
                progress_cb,
            )
            if self._is_cancelled:
                self.finished.emit(False, "Cancelled")
            else:
                self.finished.emit(True, self.dest_path)
        except Exception as e:
            self.finished.emit(False, str(e))
            
    def cancel(self):
        self._is_cancelled = True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.language = get_app_language(self.config_manager)
        self.current_version = APP_VERSION_TAG
        self.update_worker = None
        self.update_download_url = ""
        self.update_release_url = ""
        self._is_exiting = False
        self._tray_notice_shown = False
        self.tray_icon = None
        self.tray_menu = None
        self.tray_open_action = None
        self.tray_exit_action = None
        self.init_ui()
        self.setup_system_tray()
        
        # 시작 시 백그라운드 업데이트 확인. 저장소 설정이 비어 있으면 AutoUpdater 기본 저장소를 사용합니다.
        if self.config_manager.get("auto_check_update", "on_start") == "on_start":
            self.trigger_update_check(silent=True)
        
    def init_ui(self):
        self.setWindowTitle(tr("app_title", self.language, version=self.current_version))
        self.setStyleSheet(APP_STYLESHEET)
        self.setMinimumSize(1000, 700)
        saved_size = self.config_manager.get("window_size", [1200, 800])
        if isinstance(saved_size, list) and len(saved_size) == 2:
            self.resize(int(saved_size[0]), int(saved_size[1]))
        else:
            self.resize(1200, 800)
        self.move(100, 100)
        
        # 중앙 레이아웃: 업데이트 배너 + 탭 위젯
        central_widget = QWidget()
        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)

        self.update_banner = self.create_update_banner()
        central_layout.addWidget(self.update_banner)

        # 탭 위젯 생성
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        central_layout.addWidget(self.tab_widget)
        
        # 각 탭 초기화 및 추가
        self.task_tab = TaskTab(self.config_manager)
        self.pdf_tab = PDFTab(self.config_manager)
        self.ocr_tab = OCRTab(self.config_manager)
        self.eml_tab = EMLTab(self.config_manager)
        self.sync_tab = SyncTab(self.config_manager)
        self.bypass_tab = BypassTab(self.config_manager)
        
        import qtawesome as qta

        self.tab_widget.addTab(self.task_tab, qta.icon('fa5s.rocket', color='white'), tr("tab_tasks", self.language))
        self.tab_widget.addTab(self.sync_tab, qta.icon('fa5s.sync-alt', color='white'), tr("tab_sync", self.language))
        self.tab_widget.addTab(self.eml_tab, qta.icon('fa5s.envelope', color='white'), tr("tab_eml", self.language))
        self.tab_widget.addTab(self.pdf_tab, qta.icon('fa5s.file-pdf', color='white'), tr("tab_pdf", self.language))
        self.tab_widget.addTab(self.ocr_tab, qta.icon('fa5s.search', color='white'), tr("tab_ocr", self.language))
        self.tab_widget.addTab(self.bypass_tab, qta.icon('fa5s.tools', color='white'), tr("tab_bypass", self.language))
        
        # 메뉴바 생성
        self.create_menu_bar()
        
        # 상태 표시줄
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        localize_widget_tree(self.centralWidget(), self.language)
        self.task_tab.refresh_language()
        self._set_tab_labels()
        self.status_bar.showMessage(tr("ready", self.language))

    def _set_tab_labels(self):
        tab_labels = ("tab_tasks", "tab_sync", "tab_eml", "tab_pdf", "tab_ocr", "tab_bypass")
        for index, key in enumerate(tab_labels):
            self.tab_widget.setTabText(index, tr(key, self.language))

    def setup_system_tray(self):
        """Keep scheduled work alive after the main window is closed."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is unavailable; closing the window will exit the application.")
            return

        app = QApplication.instance()
        if app:
            app.setQuitOnLastWindowClosed(False)

        tray_icon = self.windowIcon()
        if tray_icon.isNull() and app:
            tray_icon = app.windowIcon()
        if tray_icon.isNull():
            tray_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

        self.tray_icon = QSystemTrayIcon(tray_icon, self)
        self.tray_menu = QMenu(self)
        self.tray_open_action = QAction(self)
        self.tray_open_action.triggered.connect(self.show_from_tray)
        self.tray_menu.addAction(self.tray_open_action)
        self.tray_menu.addSeparator()
        self.tray_exit_action = QAction(self)
        self.tray_exit_action.triggered.connect(self.request_exit)
        self.tray_menu.addAction(self.tray_exit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.update_tray_translations()
        self.tray_icon.show()
        if app:
            app.aboutToQuit.connect(self.tray_icon.hide)

    def update_tray_translations(self):
        if not self.tray_icon:
            return
        self.tray_icon.setToolTip(tr("tray_tooltip", self.language))
        self.tray_open_action.setText(tr("tray_open", self.language))
        self.tray_exit_action.setText(tr("tray_exit", self.language))

    def on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_from_tray()

    def show_from_tray(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        self.save_window_state()
        self.hide()
        if self.tray_icon and not self._tray_notice_shown:
            self.tray_icon.showMessage(
                tr("tray_running_title", self.language),
                tr("tray_running_message", self.language),
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            self._tray_notice_shown = True

    def request_exit(self):
        """Exit only from an explicit menu action; a normal window close hides to tray."""
        if self._is_exiting:
            return
        self._is_exiting = True
        if not self.close():
            self._is_exiting = False
            return
        if self.tray_icon:
            self.tray_icon.hide()
        app = QApplication.instance()
        if app:
            app.quit()

    def create_update_banner(self):
        banner = QFrame()
        banner.setObjectName("UpdateBanner")
        banner.setVisible(False)
        banner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout()
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(10)
        banner.setLayout(layout)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.update_banner_title = QLabel(tr("update_available", self.language))
        self.update_banner_title.setObjectName("UpdateBannerTitle")
        self.update_banner_body = QLabel("")
        self.update_banner_body.setObjectName("UpdateBannerBody")
        self.update_banner_body.setWordWrap(True)
        text_layout.addWidget(self.update_banner_title)
        text_layout.addWidget(self.update_banner_body)

        layout.addLayout(text_layout, 1)

        self.update_download_btn = QPushButton(tr("download", self.language))
        self.update_download_btn.setObjectName("UpdateBannerPrimary")
        self.update_download_btn.clicked.connect(self.download_update_from_banner)
        layout.addWidget(self.update_download_btn)

        self.update_release_btn = QPushButton(tr("view_release", self.language))
        self.update_release_btn.setObjectName("UpdateBannerSecondary")
        self.update_release_btn.clicked.connect(self.open_update_release_page)
        layout.addWidget(self.update_release_btn)

        self.update_close_btn = QPushButton("×")
        self.update_close_btn.setObjectName("UpdateBannerClose")
        self.update_close_btn.setToolTip(tr("close_update_notice", self.language))
        self.update_close_btn.clicked.connect(banner.hide)
        layout.addWidget(self.update_close_btn)
        return banner
        
    def create_menu_bar(self):
        menu_bar = self.menuBar()
        
        menu_bar.clear()
        self.file_menu = menu_bar.addMenu(tr("file_menu", self.language))
        
        settings_action = QAction(tr("settings", self.language), self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.open_settings)
        self.file_menu.addAction(settings_action)
        
        self.file_menu.addSeparator()
        
        exit_action = QAction(tr("exit", self.language), self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.request_exit)
        self.file_menu.addAction(exit_action)
        
        self.help_menu = menu_bar.addMenu(tr("help_menu", self.language))
        
        check_update_action = QAction(tr("check_updates", self.language), self)
        check_update_action.triggered.connect(lambda: self.trigger_update_check(silent=False))
        self.help_menu.addAction(check_update_action)
        
    def trigger_update_check(self, silent=True):
        if self.update_worker and self.update_worker.isRunning():
            return

        if not silent:
            self.status_bar.showMessage(tr("checking_updates", self.language))
            
        self.update_worker = UpdateWorker(current_version=self.current_version)
        self.update_worker.finished.connect(
            lambda has_up, lat, url, notes, err: self.on_update_checked(has_up, lat, url, notes, err, silent)
        )
        self.update_worker.start()
        
    def on_update_checked(self, has_update, latest_version, download_url, release_notes, error_message, silent):
        if not silent:
            self.status_bar.showMessage(tr("update_check_finished", self.language), 3000)

        if error_message:
            if not silent:
                QMessageBox.warning(
                    self,
                    tr("update_check_failed", self.language),
                    tr("update_check_failed_body", self.language, detail=error_message),
                )
            return
            
        if has_update:
            self.show_update_banner(latest_version, download_url, release_notes)
            if not silent:
                self.status_bar.showMessage(tr("update_available_status", self.language, version=latest_version), 5000)
        else:
            if not silent:
                QMessageBox.information(
                    self,
                    tr("update_information", self.language),
                    tr("up_to_date", self.language, version=self.current_version),
                )

    def show_update_banner(self, latest_version, download_url, release_notes=""):
        self.update_download_url = download_url or ""
        repo_owner = self.update_worker.updater.repo_owner if self.update_worker else "KwangBeomPark"
        repo_name = self.update_worker.updater.repo_name if self.update_worker else "FileOps-Hub"
        self.update_release_url = f"https://github.com/{repo_owner}/{repo_name}/releases/tag/{latest_version}"

        self.update_banner_title.setText(f"{tr('update_available', self.language)}: {latest_version}")
        body = tr("update_banner_body", self.language, current_version=self.current_version)
        if release_notes:
            one_line_notes = " ".join(release_notes.split())
            if one_line_notes:
                body += f"  {one_line_notes[:120]}"
                if len(one_line_notes) > 120:
                    body += "..."
        self.update_banner_body.setText(body)
        self.update_banner_body.setToolTip(release_notes or body)
        self.update_download_btn.setEnabled(bool(self.update_download_url))
        self.update_download_btn.setToolTip(
            tr("download_installer", self.language)
            if self.update_download_url
            else tr("view_installer", self.language)
        )
        self.update_banner.setVisible(True)

    def download_update_from_banner(self):
        if self.update_download_url:
            self.start_update_download(self.update_download_url)
        else:
            self.open_update_release_page()

    def open_update_release_page(self):
        import webbrowser

        target_url = self.update_release_url
        if not target_url:
            repo_owner = self.update_worker.updater.repo_owner if self.update_worker else "KwangBeomPark"
            repo_name = self.update_worker.updater.repo_name if self.update_worker else "FileOps-Hub"
            target_url = f"https://github.com/{repo_owner}/{repo_name}/releases"
        webbrowser.open(target_url)

    def start_update_download(self, download_url):
        # 다운로드 경로 설정 (시스템 임시 폴더)
        temp_dir = tempfile.gettempdir()
        updater = self.update_worker.updater if self.update_worker else None
        if not updater or not updater.latest_asset or download_url != updater.latest_asset.url:
            QMessageBox.critical(
                self,
                tr("update_verification_failed", self.language),
                tr("update_verification_failed_body", self.language),
            )
            return
        filename = updater.latest_asset.name
        dest_path = os.path.join(temp_dir, filename)
        
        # 진행 상태 다이얼로그 생성
        progress_dialog = QProgressDialog(tr("downloading_update", self.language), tr("cancel", self.language), 0, 100, self)
        progress_dialog.setWindowTitle(tr("update_download", self.language))
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setAutoClose(True)
        progress_dialog.setAutoReset(True)
        progress_dialog.show()
        
        # 백그라운드 다운로드 워커 기동
        download_worker = DownloadWorker(self.update_worker.updater, download_url, dest_path)
        self._active_download_worker = download_worker  # GC 방지 및 취소용
        
        def update_progress(downloaded, total):
            if total > 0:
                val = int(downloaded * 100 / total)
                progress_dialog.setValue(val)
                downloaded_mb = downloaded / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                progress_dialog.setLabelText(tr("downloading_progress", self.language, downloaded=downloaded_mb, total=total_mb))
            else:
                progress_dialog.setLabelText(tr("downloading_update", self.language))
                
        download_worker.progress.connect(update_progress)
        
        def cancel_download():
            download_worker.cancel()
            self.status_bar.showMessage(tr("download_cancelled", self.language), 3000)
            
        progress_dialog.canceled.connect(cancel_download)
        
        def on_download_finished(success, result):
            progress_dialog.close()
            if success:
                # 다운로드 성공 -> 설치 실행 의사 확인
                reply = QMessageBox.question(
                    self,
                    tr("download_complete", self.language),
                    tr("download_complete_body", self.language),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        # 방어 검증: 파일 존재 여부 및 확장자 검증
                        if not os.path.exists(result):
                            raise FileNotFoundError("다운로드된 설치 파일을 찾을 수 없습니다.")
                        if not result.lower().endswith('.exe'):
                            raise PermissionError("실행 가능한 설치 파일(.exe)만 바로 실행할 수 있습니다.")
                            
                        # 설치 파일 실행
                        os.startfile(result)
                        
                        # 모든 작업 강제 중단 후 즉시 종료 (인스톨러가 바로 덮어쓸 수 있도록)
                        self.task_tab.stop_all()
                        self.pdf_tab.stop_all()
                        self.ocr_tab.stop_all()
                        self.eml_tab.stop_all()
                        self.sync_tab.stop_all()
                        self.bypass_tab.stop_all()
                        os._exit(0)
                    except Exception as err:
                        QMessageBox.critical(self, tr("run_error", self.language), str(err))
            else:
                if result != "Cancelled":
                    QMessageBox.critical(self, tr("download_failed", self.language), str(result))
                    
        download_worker.finished.connect(on_download_finished)
        download_worker.start()
                
    def open_settings(self):
        dialog = SettingsDialog(self.config_manager, self)
        if dialog.exec():
            self.ocr_tab.ocr_processor.setup_tesseract()
            logger.info("Settings updated and saved.")
            self.refresh_language()
            self.status_bar.showMessage(tr("settings_saved", self.language), 3000)

    def refresh_language(self):
        """Apply a saved display-language choice without disturbing task configuration."""
        self.language = get_app_language(self.config_manager)
        self.setWindowTitle(tr("app_title", self.language, version=self.current_version))
        self.create_menu_bar()
        localize_widget_tree(self.centralWidget(), self.language)
        self.task_tab.refresh_language()
        self._set_tab_labels()
        self.update_banner_title.setText(tr("update_available", self.language))
        self.update_download_btn.setText(tr("download", self.language))
        self.update_release_btn.setText(tr("view_release", self.language))
        self.update_close_btn.setToolTip(tr("close_update_notice", self.language))
        self.update_tray_translations()

    def set_all_tabs_locked(self, locked):
        """통합 태스크 실행 중 모든 탭 바 및 개별 탭 UI를 비활성화"""
        self.tab_widget.tabBar().setEnabled(not locked)
        self.sync_tab.set_ui_locked(locked)
        self.eml_tab.set_ui_locked(locked)
        self.pdf_tab.set_ui_locked(locked)
        self.ocr_tab.set_ui_locked(locked)
        self.bypass_tab.set_ui_locked(locked)

    def save_window_state(self):
        size = self.size()
        self.config_manager.set("window_size", [size.width(), size.height()])
            
    def closeEvent(self, event):
        if self.tray_icon and self.tray_icon.isVisible() and not self._is_exiting:
            event.ignore()
            self.hide_to_tray()
            return

        active_tasks = []
        if self.task_tab.is_running:
            active_tasks.append("통합 일괄 실행")
        if self.pdf_tab.is_converting:
            active_tasks.append("PDF 이미지 변환")
        if self.ocr_tab.is_converting:
            active_tasks.append("이미지 OCR 이름 변경")
        if self.eml_tab.is_converting:
            active_tasks.append("EML 변환")
        if self.sync_tab.is_running:
            active_tasks.append("폴더 동기화")
        if self.bypass_tab.is_running:
            active_tasks.append("포맷 우회 변환")
            
        if active_tasks:
            task_list = ", ".join(active_tasks)
            reply = QMessageBox.question(
                self, 
                "작업 진행 중", 
                f"현재 [{task_list}] 작업이 실행 중입니다. 프로그램을 강제 종료하시겠습니까?\n(강제 종료 시 데이터 손상이 발생할 수 있습니다.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.task_tab.stop_all()
                self.pdf_tab.stop_all()
                self.ocr_tab.stop_all()
                self.eml_tab.stop_all()
                self.sync_tab.stop_all()
                self.bypass_tab.stop_all()
                self.save_window_state()
                if self.tray_icon:
                    self.tray_icon.hide()
                event.accept()
            else:
                self._is_exiting = False
                event.ignore()
        else:
            self.save_window_state()
            if self.tray_icon:
                self.tray_icon.hide()
            event.accept()

"""Explicit, manual cleanup of dated file versions."""
import copy
import os

from PyQt6.QtCore import QSignalBlocker, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.app_identity import asset_path
from src.ui.i18n import choose


def cleanup_checkbox_style():
    """Keep unchecked boxes visible against both normal and selected rows."""
    widgets = ("QTableWidget#VersionCleanupCandidates", "QCheckBox#VersionCleanupSubfolders")
    indicator = ", ".join(f"{widget}::indicator" for widget in widgets)
    checked = ", ".join(f"{widget}::indicator:checked" for widget in widgets)
    hover = ", ".join(f"{widget}::indicator:hover" for widget in widgets)
    disabled = ", ".join(f"{widget}::indicator:disabled" for widget in widgets)
    checkmark = asset_path("checkmark.svg").as_posix()
    return f"""
        {indicator} {{ width: 20px; height: 20px; border: 3px solid #dbeafe;
                       border-radius: 4px; background-color: #18212b; }}
        {checked} {{ border-color: #7dd3fc; background-color: #0369a1;
                     image: url(\"{checkmark}\"); }}
        {hover} {{ border-color: #ffffff; }}
        {disabled} {{ border-color: #64748b; background-color: #334155; }}
    """


class CleanupWorker(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object, object)

    def __init__(self, operation, kwargs):
        super().__init__()
        self.operation, self.kwargs = operation, kwargs
        self.cancelled = False

    def stop(self):
        self.cancelled = True

    def run(self):
        try:
            def progress(*args):
                if len(args) == 1:
                    self.progress.emit(0, 0, str(args[0]))
                elif len(args) == 3:
                    self.progress.emit(int(args[0]), int(args[1]), str(args[2]))
            result = self.operation(**self.kwargs, cancel_callback=lambda: self.cancelled,
                                    progress_callback=progress)
            self.completed.emit(result, None)
        except Exception as exc:  # noqa: BLE001 - report unexpected worker failures to the UI
            self.completed.emit(None, str(exc))


class VersionCleanupDialog(QDialog):
    def __init__(self, folders, language, parent=None, scan=None, execute=None, archive_folder_name="to be deleted"):
        super().__init__(parent)
        if scan is None:
            from src.core.version_cleanup import scan_version_cleanup
            scan = scan_version_cleanup
        if execute is None:
            from src.core.version_cleanup import execute_version_cleanup
            execute = execute_version_cleanup
        self.execution_available = True
        self.scan, self.execute = scan, execute
        self.folders, self.language = list(folders), language
        self.archive_folder_name = archive_folder_name
        self.worker = None
        self.candidates = []
        self.setWindowTitle(self.t("Clean up old versions", "구버전 정리", "Usuwanie starych wersji"))
        self.resize(950, 550)
        layout = QVBoxLayout(self)
        info = QLabel(self.t("Current group folders; each is analyzed independently and its latest version is kept (manual operation only):", "현재 그룹 폴더별로 독립 분석하고 각 최신 버전을 유지합니다 (수동 실행만 가능):", "Każdy folder jest analizowany niezależnie, a jego najnowsza wersja pozostaje (tylko ręcznie):") + "\n" + "\n".join(self.folders))
        info.setTextFormat(Qt.TextFormat.PlainText)
        info.setWordWrap(True)
        layout.addWidget(info)
        self.subfolders = QCheckBox(self.t("Include subfolders", "하위 폴더 포함", "Uwzględnij podfoldery"))
        self.subfolders.setObjectName("VersionCleanupSubfolders")
        self.subfolders.toggled.connect(self.invalidate)
        layout.addWidget(self.subfolders)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("VersionCleanupCandidates")
        self.table.verticalHeader().setMinimumSectionSize(34)
        self.setStyleSheet(cleanup_checkbox_style())
        self.table.itemChanged.connect(self.update_execute_state)
        self.table.setHorizontalHeaderLabels([self.t("Select", "선택", "Wybierz"), self.t("Original location", "원본 위치", "Lokalizacja"), self.t("Filename", "파일명", "Nazwa pliku"), self.t("Version", "버전", "Wersja"), self.t("Latest version", "최신 버전", "Najnowsza wersja")])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        self.analyze_button = QPushButton(self.t("Analyze", "분석", "Analizuj"))
        self.analyze_button.clicked.connect(self.start_scan)
        controls.addWidget(self.analyze_button)
        self.selection_count = QLabel()
        controls.addWidget(self.selection_count)
        controls.addStretch(1)
        self.method = QComboBox()
        method_label = QLabel(self.t("Move to:", "이동 위치:", "Przenieś do:"))
        method_label.setBuddy(self.method)
        controls.addWidget(method_label)
        self.method.addItem(self.t("Recycle Bin", "휴지통", "Kosz"), "trash")
        self.method.addItem(self.t(f"Folder: {self.archive_folder_name}", f"폴더: {self.archive_folder_name}", f"Folder: {self.archive_folder_name}"), "folder")
        controls.addWidget(self.method)
        self.execute_button = QPushButton(self.t("Execute selected", "선택 항목 실행", "Wykonaj wybrane"))
        self.execute_button.clicked.connect(self.start_execution)
        self.execute_button.setEnabled(False)
        if not self.execution_available:
            self.execute_button.setToolTip(self.t("Execution is unavailable while safety verification is incomplete.", "안전 검증이 완료되지 않아 실행할 수 없습니다.", "Wykonanie jest niedostępne do czasu zakończenia weryfikacji bezpieczeństwa."))
        controls.addWidget(self.execute_button)
        self.cancel_button = QPushButton(self.t("Cancel operation", "작업 취소", "Anuluj operację"))
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel(self.t("Execution is unavailable until safety verification is complete.", "안전 검증이 완료될 때까지 실행할 수 없습니다.", "Wykonanie jest niedostępne do zakończenia weryfikacji bezpieczeństwa.") if not self.execution_available else "")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.update_execute_state()

    def t(self, en, ko, pl):
        return choose(self.language, en, ko, pl)

    def scan_error_message(self, error):
        if any(token in error for token in ("Invalid or mixed version formats", "Equivalent version names require review", "Conflicting same-date files")):
            message = self.t(
                "The list could not be created because version formats are mixed, a date is invalid, or equivalent versions conflict. Check the filenames.",
                "숫자·날짜 버전이 섞였거나 날짜가 잘못되었거나 같은 버전이 충돌해 목록을 만들 수 없습니다. 파일명을 확인해 주세요.",
                "Nie można utworzyć listy: formaty wersji są mieszane, data jest nieprawidłowa lub równoważne wersje są sprzeczne. Sprawdź nazwy plików.",
            )
            return message + "\n" + self.t("Details:", "상세:", "Szczegóły:") + " " + error
        return error

    def invalidate(self):
        self.candidates = []
        self.table.setRowCount(0)
        self.update_execute_state()

    def busy(self, busy):
        self._busy = busy
        self.analyze_button.setEnabled(not busy)
        self.subfolders.setEnabled(not busy)
        self.method.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.update_execute_state()

    def _checked_rows(self):
        """Selection means a checkbox is checked, not a highlighted row."""
        return [row for row in range(len(self.candidates))
                if (item := self.table.item(row, 0)) and item.checkState() == Qt.CheckState.Checked]

    def update_execute_state(self, *_args):
        count = len(self._checked_rows())
        self.selection_count.setText(self.t(
            f"Files checked: {count}", f"체크한 파일: {count}개", f"Zaznaczone pliki: {count}",
        ))
        self.execute_button.setEnabled(not getattr(self, "_busy", False) and self.execution_available and count > 0)

    def launch(self, operation, kwargs, handler):
        if self.worker and self.worker.isRunning():
            return
        self.busy(True)
        self.worker = CleanupWorker(operation, kwargs)
        self.worker.progress.connect(self.on_progress)
        self.worker.completed.connect(handler)
        self.worker.start()

    def on_progress(self, current, total, path):
        self.progress.setRange(0, total if total else 0)
        self.progress.setValue(current)
        self.status.setText(path)

    def start_scan(self):
        if not self.folders:
            QMessageBox.warning(self, self.windowTitle(), self.t("Add a folder to the current group first.", "현재 그룹에 폴더를 먼저 추가하세요.", "Najpierw dodaj folder do bieżącej grupy."))
            return
        self.invalidate()
        self.launch(self.scan, {"folders": self.folders, "include_subfolders": self.subfolders.isChecked(), "archive_folder_name": self.archive_folder_name}, self.scan_finished)

    def scan_finished(self, result, error):
        self.worker.wait()
        cancelled = self.worker.cancelled
        self.busy(False)
        if error or cancelled:
            self.status.setText(self.scan_error_message(error) if error else self.t("Analysis cancelled.", "분석이 취소되었습니다.", "Analiza anulowana."))
            return
        self.candidates = result
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(result))
            for row, candidate in enumerate(result):
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                check.setCheckState(Qt.CheckState.Unchecked)
                self.table.setItem(row, 0, check)
                for col, key in enumerate(("folder", "filename", "date", "latest_date"), 1):
                    value = candidate.get(key, "")
                    if key == "folder":
                        value = os.path.dirname(candidate.get("path", "")) or value
                    item = QTableWidgetItem(str(value))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self.update_execute_state()
        message = self.t(f"{len(result)} candidates. Select files to process.", f"후보 {len(result)}개. 처리할 파일을 선택하세요.", f"Kandydaci: {len(result)}. Wybierz pliki.")
        if not self.execution_available:
            message += "\n" + self.t("Execution is unavailable until safety verification is complete.", "안전 검증이 완료될 때까지 실행할 수 없습니다.", "Wykonanie jest niedostępne do zakończenia weryfikacji bezpieczeństwa.")
        self.status.setText(message)

    def start_execution(self):
        if not self.execution_available or getattr(self, "_busy", False):
            return
        selected = [copy.deepcopy(self.candidates[row]) for row in self._checked_rows()]
        if not selected:
            QMessageBox.information(self, self.windowTitle(), self.t("Select at least one file.", "파일을 하나 이상 선택하세요.", "Wybierz co najmniej jeden plik."))
            return
        method = self.method.currentData()
        label = self.method.currentText()
        if not self.confirm_move(len(selected), label):
            return
        self.launch(self.execute, {"candidates": selected, "method": method, "archive_folder_name": self.archive_folder_name}, self.execution_finished)

    def confirm_move(self, count, destination):
        prompt = self.t(
            f"Move the checked files ({count})?\n\nDestination: {destination}",
            f"체크한 파일 {count}개를 이동할까요?\n\n이동 위치: {destination}",
            f"Przenieść zaznaczone pliki ({count})?\n\nMiejsce docelowe: {destination}",
        )
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(self.windowTitle())
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(prompt)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        try:
            return dialog.exec() == QMessageBox.StandardButton.Yes
        finally:
            dialog.deleteLater()

    def execution_finished(self, result, error):
        self.worker.wait()
        self.busy(False)
        self.invalidate()
        if error:
            self.status.setText(error)
            return
        details = []
        for entry in result.get("error_details", []):
            phase = {
                "preflight": self.t("Before processing", "처리 전 확인", "Kontrola przed przetwarzaniem"),
                "execution": self.t("During processing", "처리 중", "Podczas przetwarzania"),
            }.get(entry.get("phase"), entry.get("phase", ""))
            uncertain = entry.get("uncertain", False)
            outcome = self.t("The result is uncertain; check the file and destination before trying again.", "처리 결과가 불확실합니다. 다시 시도하기 전에 파일과 대상 위치를 확인하세요.", "Wynik jest niepewny; przed ponowną próbą sprawdź plik i lokalizację docelową.") if uncertain else self.t("The result is known.", "처리 결과가 확인되었습니다.", "Wynik jest znany.")
            details.append(f"{phase}. {outcome}\n{entry.get('path', '')}\n{entry.get('reason', '')}")
        if not details:
            details = list(map(str, result.get("errors", [])))
        cancelled = self.t("yes", "예", "tak") if result.get("cancelled", False) else self.t("no", "아니요", "nie")
        self.status.setText(self.t(f"Completed: {result.get('success', 0)}, failed: {result.get('fail', 0)}, not processed: {result.get('not_processed', 0)}, cancelled: {cancelled}", f"완료: {result.get('success', 0)}, 실패: {result.get('fail', 0)}, 미처리: {result.get('not_processed', 0)}, 취소: {cancelled}", f"Gotowe: {result.get('success', 0)}, błędy: {result.get('fail', 0)}, nieprzetworzone: {result.get('not_processed', 0)}, anulowano: {cancelled}") + "\n" + "\n".join(details))

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.cancel_button.setEnabled(False)

    def stop_and_wait(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()

    def reject(self):
        self.stop_and_wait()
        super().reject()

    def closeEvent(self, event):
        self.stop_and_wait()
        super().closeEvent(event)

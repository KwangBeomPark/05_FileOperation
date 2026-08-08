from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.backup_recovery import backup_directory, list_backup_entries, restore_backup_files
from src.ui.i18n import choose, get_app_language


class BackupRecoveryDialog(QDialog):
    def __init__(self, config_manager, source_folder: str = "", parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.language = get_app_language(config_manager)
        self.source_folder = source_folder if os.path.isdir(source_folder) else ""
        self.entries = []
        self.restored_any = False

        self.setWindowTitle(self._t("Original Backup Recovery", "Original Backup 복구", "Odzyskiwanie Original Backup"))
        self.resize(920, 560)
        self.setMinimumSize(720, 440)
        self._build_ui()
        self.refresh_entries()

    def _t(self, english: str, korean: str, polish: str | None = None) -> str:
        return choose(self.language, english, korean, polish)

    @staticmethod
    def _format_size(byte_count: int) -> str:
        size = float(byte_count)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            self._t(
                "Review files moved to Original Backup and restore only the selected items. Existing source files are never overwritten.",
                "Original Backup으로 이동된 파일을 확인하고 선택한 항목만 복구합니다. 기존 원본 파일은 절대 덮어쓰지 않습니다.",
                "Przejrzyj pliki przeniesione do Original Backup i przywróć tylko wybrane. Istniejące pliki nigdy nie są nadpisywane.",
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(self._t("Source folder:", "원본 폴더:", "Folder źródłowy:")))
        self.folder_label = QLabel()
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setStyleSheet(
            "background-color: #1e1e1e; color: #cbd5e1; border: 1px solid #334155; "
            "padding: 7px; border-radius: 4px;"
        )
        folder_row.addWidget(self.folder_label, 1)
        self.choose_button = QPushButton(self._t("Choose Folder", "폴더 선택", "Wybierz folder"))
        self.choose_button.clicked.connect(self.choose_source_folder)
        folder_row.addWidget(self.choose_button)
        layout.addLayout(folder_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                self._t("Backup File", "백업 파일", "Plik kopii"),
                self._t("Size", "크기", "Rozmiar"),
                self._t("Modified", "수정 시각", "Zmodyfikowano"),
                self._t("Restore To", "복구 위치", "Przywróć do"),
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_restore_button)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.refresh_button = QPushButton(self._t("Refresh", "새로 고침", "Odśwież"))
        self.refresh_button.clicked.connect(self.refresh_entries)
        self.open_button = QPushButton(self._t("Open Backup Folder", "백업 폴더 열기", "Otwórz folder kopii"))
        self.open_button.clicked.connect(self.open_backup_folder)
        self.restore_button = QPushButton(self._t("Restore Selected", "선택 항목 복구", "Przywróć wybrane"))
        self.restore_button.setProperty("variant", "success")
        self.restore_button.clicked.connect(self.restore_selected)
        close_button = QPushButton(self._t("Close", "닫기", "Zamknij"))
        close_button.clicked.connect(self.accept)

        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.open_button)
        button_row.addStretch()
        button_row.addWidget(self.restore_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def choose_source_folder(self) -> None:
        initial = self.source_folder or self.config_manager.get("last_bypass_source_directory", "")
        folder = QFileDialog.getExistingDirectory(
            self,
            self._t("Select Source Folder", "원본 폴더 선택", "Wybierz folder źródłowy"),
            initial,
        )
        if folder:
            self.source_folder = os.path.normpath(folder)
            self.refresh_entries()

    def refresh_entries(self) -> None:
        self.folder_label.setText(self.source_folder or self._t("No source folder selected", "선택된 원본 폴더가 없습니다", "Nie wybrano folderu źródłowego"))
        self.table.setRowCount(0)
        self.entries = []

        try:
            self.entries = list_backup_entries(self.source_folder)
        except Exception as exc:
            self.status_label.setText(
                self._t(
                    f"Could not read the backup folder: {exc}",
                    f"백업 폴더를 읽지 못했습니다: {exc}",
                    f"Nie można odczytać folderu kopii: {exc}",
                )
            )
        else:
            for row, entry in enumerate(self.entries):
                self.table.insertRow(row)
                name_item = QTableWidgetItem(entry.file_name)
                name_item.setData(Qt.ItemDataRole.UserRole, entry.backup_path)
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, QTableWidgetItem(self._format_size(entry.size)))
                self.table.setItem(row, 2, QTableWidgetItem(datetime.fromtimestamp(entry.modified_time).strftime("%Y-%m-%d %H:%M")))
                self.table.setItem(row, 3, QTableWidgetItem(entry.restore_target))

            if not self.source_folder:
                message = self._t("Choose a source folder to find its backups.", "원본 폴더를 선택하면 백업을 찾을 수 있습니다.", "Wybierz folder źródłowy, aby znaleźć kopie.")
            elif self.entries:
                total_size = sum(entry.size for entry in self.entries)
                message = self._t(
                    f"{len(self.entries)} backup file(s), {self._format_size(total_size)} total. Select rows to restore.",
                    f"백업 파일 {len(self.entries)}개, 총 {self._format_size(total_size)}입니다. 복구할 행을 선택하세요.",
                    f"Pliki kopii: {len(self.entries)}, razem {self._format_size(total_size)}. Wybierz wiersze do przywrócenia.",
                )
            else:
                message = self._t("No backup files were found.", "백업 파일이 없습니다.", "Nie znaleziono plików kopii.")
            self.status_label.setText(message)

        self.open_button.setEnabled(bool(self.source_folder) and os.path.isdir(backup_directory(self.source_folder)))
        self._update_restore_button()

    def _selected_backup_paths(self) -> list[str]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in rows]

    def _update_restore_button(self) -> None:
        self.restore_button.setEnabled(bool(self._selected_backup_paths()))

    def restore_selected(self) -> None:
        selected_paths = self._selected_backup_paths()
        if not selected_paths:
            return

        names = [os.path.basename(path) for path in selected_paths]
        preview = "\n".join(f"- {name}" for name in names[:8])
        if len(names) > 8:
            preview += self._t(f"\n- ... and {len(names) - 8} more", f"\n- ... 외 {len(names) - 8}개", f"\n- ... i jeszcze {len(names) - 8}")
        question = self._t(
            f"Restore {len(names)} selected file(s) to the source folder?\n\n{preview}\n\nExisting files will not be overwritten.",
            f"선택한 파일 {len(names)}개를 원본 폴더로 복구할까요?\n\n{preview}\n\n기존 파일은 덮어쓰지 않습니다.",
            f"Przywrócić wybrane pliki ({len(names)}) do folderu źródłowego?\n\n{preview}\n\nIstniejące pliki nie zostaną nadpisane.",
        )
        answer = QMessageBox.question(
            self,
            self._t("Confirm Restore", "복구 확인", "Potwierdź przywracanie"),
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        results = restore_backup_files(self.source_folder, selected_paths)
        succeeded = [result for result in results if result.success]
        failed = [result for result in results if not result.success]
        self.restored_any = self.restored_any or bool(succeeded)
        self.refresh_entries()

        if failed:
            failures = "\n".join(f"- {os.path.basename(result.backup_path)}: {result.error}" for result in failed)
            QMessageBox.warning(
                self,
                self._t("Restore Incomplete", "일부 복구 실패", "Niepełne przywracanie"),
                self._t(
                    f"Restored {len(succeeded)} of {len(results)} file(s). Failed files remain in Original Backup.\n\n{failures}",
                    f"{len(results)}개 중 {len(succeeded)}개를 복구했습니다. 실패한 파일은 Original Backup에 그대로 남아 있습니다.\n\n{failures}",
                    f"Przywrócono {len(succeeded)} z {len(results)} plików. Nieudane pliki pozostają w Original Backup.\n\n{failures}",
                ),
            )
        else:
            QMessageBox.information(
                self,
                self._t("Restore Complete", "복구 완료", "Przywracanie zakończone"),
                self._t(
                    f"Restored {len(succeeded)} file(s).",
                    f"파일 {len(succeeded)}개를 복구했습니다.",
                    f"Przywrócono pliki: {len(succeeded)}.",
                ),
            )

    def open_backup_folder(self) -> None:
        folder = backup_directory(self.source_folder)
        if not os.path.isdir(folder):
            QMessageBox.information(
                self,
                self._t("Backup Folder", "백업 폴더", "Folder kopii"),
                self._t("The backup folder does not exist yet.", "아직 백업 폴더가 없습니다.", "Folder kopii jeszcze nie istnieje."),
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            QMessageBox.warning(
                self,
                self._t("Open Failed", "열기 실패", "Nie udało się otworzyć"),
                self._t(f"Could not open: {folder}", f"폴더를 열지 못했습니다: {folder}", f"Nie można otworzyć: {folder}"),
            )

"""Shared manual confirmation and bounded, non-mutating file-change analysis."""
from __future__ import annotations

from threading import Event

from PyQt6.QtCore import QEventLoop, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
)

from src.core.probe_runner import run_probe
from src.core.run_summary import RunChangeSummary, SUMMARY_TIMEOUT_SECONDS
from src.ui.i18n import choose, get_app_language, tr
from src.ui.preflight_dialog import PreflightProgressDialog
from src.utils.logger import get_logger


logger = get_logger()

# UI-only strings: no localization/Qt dependency is added to the analyzer.
TEXT = {
    "title": ("Review changes before running", "실행 전 변경 요약", "Sprawdź zmiany przed uruchomieniem"),
    "intro": ("Task files have not been changed. Review the estimated operations and locations below.", "작업 대상 파일은 아직 변경되지 않았습니다. 아래 예상 작업과 저장·이동 위치를 확인해 주세요.", "Nie zmieniono jeszcze plików zadania. Sprawdź przewidywane operacje i lokalizacje."),
    "units": ("Counts refer to operations or input files, not final output files. Backup names and rendered output names may be decided during execution.", "건수는 작업 또는 입력 파일 기준이며 최종 결과물 개수가 아닙니다. 백업 이름과 변환 결과 이름은 실행 중 정해질 수 있습니다.", "Liczby dotyczą operacji lub plików wejściowych, nie końcowych wyników. Nazwy kopii i wyników mogą zostać ustalone podczas wykonania."),
    "copy": ("Copy", "복사", "Kopiowanie"),
    "convert": ("Convert input", "변환 대상", "Plik do konwersji"),
    "rename": ("OCR / possible rename", "OCR·이름 변경 대상", "OCR / możliwa zmiana nazwy"),
    "ocr": ("Read image (no rename)", "이미지 읽기(이름 유지)", "Odczytaj obraz (bez zmiany nazwy)"),
    "text_output": ("Save extracted text", "추출 텍스트 저장", "Zapisz rozpoznany tekst"),
    "overwrite": ("Overwrite existing TXT", "기존 TXT 덮어쓰기", "Nadpisz istniejący TXT"),
    "overwrite_text": ("DANGER: existing TXT files will be overwritten by extracted OCR text. Back up any text you need to keep before continuing.", "주의: 기존 TXT 파일을 OCR 추출 내용으로 덮어씁니다. 필요한 텍스트는 먼저 백업해 주세요.", "UWAGA: istniejące pliki TXT zostaną nadpisane tekstem OCR. Najpierw wykonaj kopie potrzebnych plików."),
    "ocr_text_policy": ("OCR will save TXT files beside generated images and may overwrite existing TXT files. Exact paths depend on earlier steps.", "OCR이 생성 이미지 옆에 TXT를 저장하며 기존 TXT가 있으면 덮어쓸 수 있습니다. 정확한 경로는 앞 단계 결과에 따라 정해집니다.", "OCR zapisze TXT obok wygenerowanych obrazów i może nadpisać istniejące TXT. Dokładne ścieżki zależą od wcześniejszych etapów."),
    "archive": ("Move to backup", "백업 폴더로 이동", "Przenieś do kopii"),
    "delete": ("Permanent delete", "영구 삭제", "Trwałe usunięcie"),
    "replace": ("Recycle / delete source after conversion", "변환 후 원본 휴지통 이동·삭제", "Kosz / usuń źródło po konwersji"),
    "extra_output": ("Additional HTML output", "추가 HTML 결과", "Dodatkowy wynik HTML"),
    "conflict_backup": ("Preserve conflicting copy", "충돌본 백업", "Zachowaj kopię konfliktową"),
    "delete_policy": ("DANGER: synchronization is configured to permanently delete old files without using the Recycle Bin. Later groups may discover additional deletions.", "주의: 동기화가 구버전 파일을 휴지통 없이 영구 삭제하도록 설정되어 있습니다. 앞선 그룹 실행 후 삭제 대상이 더 생길 수도 있습니다.", "UWAGA: synchronizacja może trwale usuwać stare pliki bez Kosza. Kolejne grupy mogą wykryć dodatkowe pliki do usunięcia."),
    "replace_policy": ("DANGER: after successful output verification, sources are sent to the Recycle Bin; if unavailable, they are permanently deleted.", "주의: 결과 검증에 성공하면 원본을 휴지통으로 이동하며, 휴지통을 사용할 수 없으면 영구 삭제합니다.", "UWAGA: po weryfikacji wyniku źródła trafiają do Kosza; jeśli jest niedostępny, są trwale usuwane."),
    "move_sources": ("Original files will be moved to backup folders after successful processing. They will no longer be at their original paths.", "처리에 성공한 원본은 백업 폴더로 이동하므로 기존 위치에는 남지 않습니다.", "Po pomyślnym przetworzeniu źródła zostaną przeniesione do kopii i znikną z pierwotnych ścieżek."),
    "conflicts": ("Potential synchronization conflicts were found. Conflicting copies will be preserved before copying the latest file.", "동기화 충돌 후보가 있습니다. 기존 충돌본을 백업한 뒤 최신 파일을 복사합니다.", "Wykryto możliwe konflikty synchronizacji. Kopie konfliktowe zostaną zachowane przed skopiowaniem najnowszego pliku."),
    "target_exists": ("A conversion target already exists. The converter must not overwrite it; affected files may fail. Cancel and choose a different destination.", "이미 존재하는 변환 결과 경로가 있습니다. 덮어쓰지 않으므로 해당 파일은 실패할 수 있습니다. 취소하고 다른 저장 위치를 지정해 주세요.", "Docelowy plik konwersji już istnieje. Nie zostanie nadpisany; konwersja może się nie udać. Anuluj i wybierz inną lokalizację."),
    "dynamic_outputs": ("Image counts and exact output names are determined when EML/PDF rendering runs.", "EML·PDF의 실제 생성 이미지 수와 이름은 변환할 때 정해집니다.", "Liczba obrazów i dokładne nazwy wyników EML/PDF są ustalane podczas renderowania."),
    "ocr_names": ("OCR may rename selected images. Final names depend on the extracted text; this preview does not run OCR.", "OCR 결과에 따라 이미지 이름이 바뀔 수 있습니다. 이 미리보기는 OCR을 실행하지 않으므로 최종 이름은 아직 알 수 없습니다.", "OCR może zmienić nazwy obrazów na podstawie tekstu. Ten podgląd nie uruchamia OCR i nie zna końcowych nazw."),
    "chained_ocr": ("OCR uses generated upstream images when available; otherwise it uses the selected fallback images. Its final input count is not known yet.", "OCR은 앞 단계의 생성 이미지가 있으면 우선 사용하고, 없으면 선택한 이미지를 사용합니다. 최종 대상 수는 아직 확정되지 않았습니다.", "OCR użyje obrazów z poprzednich etapów, jeśli będą dostępne; w przeciwnym razie użyje wybranych obrazów. Końcowa liczba nie jest jeszcze znana."),
    "sync_estimate": ("Synchronization groups run in order. Earlier groups may change what later groups need to do; counts are estimates, not a locked execution plan.", "동기화 그룹은 순서대로 실행됩니다. 앞 그룹의 결과에 따라 후속 그룹의 작업 수가 달라질 수 있으며, 이 요약은 고정된 실행 계획이 아닌 예상입니다.", "Grupy synchronizacji działają kolejno. Wcześniejsze grupy mogą zmienić pracę kolejnych; liczby są szacunkowe, nie stanowią zablokowanego planu."),
    "step_estimates": ("Earlier steps may create or move inputs for later steps. This is a current-state estimate; later input counts can change during the pipeline.", "앞 단계에서 파일이 생성·이동되면 후속 단계의 대상 수가 달라질 수 있습니다. 이 요약은 현재 상태를 기준으로 한 예상입니다.", "Wcześniejsze etapy mogą tworzyć lub przenosić dane dla kolejnych. To szacunek bieżącego stanu; liczba późniejszych plików może się zmienić."),
    "ack": ("I have reviewed the risks and locations above.", "위의 위험 사항과 저장·이동 위치를 확인했습니다.", "Sprawdzono powyższe ryzyka i lokalizacje."),
    "run": ("Run reviewed tasks", "확인한 작업 실행", "Uruchom sprawdzone zadania"),
    "cancel": ("Cancel", "취소", "Anuluj"),
    "step": ("Task", "작업", "Zadanie"),
    "action": ("Operation", "처리 내용", "Operacja"),
    "source": ("Source", "원본", "Źródło"),
    "target": ("Output / backup location", "저장·이동 위치", "Lokalizacja wyniku / kopii"),
    "count": ("Count", "건수", "Liczba"),
    "unknown": ("Determined during execution", "실행 중 결정", "Ustalane podczas wykonania"),
    "limit": ("Showing {shown} of {total} entries. Totals above include all entries.", "전체 {total}개 중 {shown}개를 표시합니다. 위 집계는 전체 항목을 포함합니다.", "Pokazano {shown} z {total} pozycji. Podsumowanie obejmuje wszystkie pozycje."),
    "analyzing": ("Analyzing changes in a read-only process (up to 30 seconds). You can cancel without changing files.", "파일을 변경하지 않고 예상 작업을 분석합니다(최대 30초). 취소해도 파일은 바뀌지 않습니다.", "Analiza zmian tylko do odczytu (do 30 sekund). Anulowanie nie zmieni plików."),
    "rechecking": ("Rechecking inputs and destinations after your review (up to 30 seconds)...", "확인하는 동안 원본·저장 위치가 바뀌지 않았는지 다시 점검합니다(최대 30초)...", "Ponowne sprawdzanie źródeł i celów po przeglądzie (do 30 sekund)..."),
    "failed": ("Changes could not be analyzed. No task was started. Check access to the selected files/folders or reduce the selected scope and try again.", "변경 내용을 분석하지 못해 작업을 시작하지 않았습니다. 선택한 파일·폴더의 접근 상태를 확인하거나 대상 범위를 줄여 다시 실행해 주세요.", "Nie udało się przeanalizować zmian. Nie uruchomiono zadań. Sprawdź dostęp do plików i folderów lub zmniejsz zakres i spróbuj ponownie."),
    "stale": ("Files, folders or the selected plan changed while you reviewed the summary. No task was started. Run again to review a fresh summary.", "확인하는 동안 파일·폴더 또는 선택한 계획이 바뀌어 실행하지 않았습니다. 다시 실행하여 새 요약을 확인해 주세요.", "Podczas przeglądu zmieniły się pliki, foldery lub plan. Nic nie uruchomiono. Uruchom ponownie, aby sprawdzić nowy podgląd."),
}


def summary_text(language, key, **values):
    return choose(language, *TEXT[key]).format(**values)


class RunSummaryDialog(QDialog):
    def __init__(self, summary: RunChangeSummary, language: str, parent=None, warnings=""):
        super().__init__(parent)
        self.summary = summary
        self.language = language
        self.setWindowTitle(self._t("title"))
        self.resize(980, 650)
        self.setMinimumSize(600, 380)
        layout = QVBoxLayout(self)
        for key in ("intro", "units"):
            label = QLabel(self._t(key))
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
        totals = []
        for key in ("copy", "convert", "rename", "ocr", "text_output", "overwrite", "archive", "conflict_backup", "delete", "replace", "extra_output"):
            count = summary.counts.get(key, 0)
            if key in summary.pending_counts:
                count = self._t("unknown") if not count else f"{count} + {self._t('unknown')}"
            if count or key in ("copy", "convert", "delete", "replace"):
                totals.append(f"{self._t(key)}: {count}")
        self.totals_label = QLabel("  |  ".join(totals))
        self.totals_label.setWordWrap(True)
        self.totals_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.totals_label)
        if summary.risks:
            self.risk_label = QLabel("\n".join(self._t(key) for key in summary.risks))
            self.risk_label.setTextFormat(Qt.TextFormat.PlainText)
            self.risk_label.setWordWrap(True)
            self.risk_label.setStyleSheet("background: #7f1d1d; color: #ffffff; padding: 10px; border-radius: 4px;")
            layout.addWidget(self.risk_label)
        self.table = QTableWidget(len(summary.entries), 5)
        self.table.setHorizontalHeaderLabels([self._t(key) for key in ("step", "action", "source", "target", "count")])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 135)
        self.table.setColumnWidth(1, 165)
        self.table.setColumnWidth(4, 80)
        for row, entry in enumerate(summary.entries):
            feature = tr(f"tab_{entry.step}", language)
            if entry.group:
                feature += f" / {entry.group}"
            target = entry.target or ("—" if entry.action in ("delete", "replace") else self._t("unknown"))
            values = (feature, self._t(entry.action), entry.source or self._t("unknown"), target,
                      str(entry.count) if entry.count is not None else self._t("unknown"))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if entry.action in ("delete", "replace", "overwrite"):
                    item.setBackground(QColor("#7f1d1d"))
                    item.setForeground(QColor("#ffffff"))
                self.table.setItem(row, column, item)
        layout.addWidget(self.table, 1)
        if summary.total_entries > len(summary.entries):
            layout.addWidget(QLabel(self._t("limit", shown=len(summary.entries), total=summary.total_entries)))
        notes = [self._t(key) for key in summary.notes]
        if warnings:
            notes.append(warnings)
        if notes:
            details = QTextEdit()
            details.setReadOnly(True)
            details.setPlainText("\n\n".join(notes))
            details.setMaximumHeight(110)
            layout.addWidget(details)
        self.acknowledgement = QCheckBox(self._t("ack"))
        self.acknowledgement.setVisible(summary.requires_acknowledgement)
        layout.addWidget(self.acknowledgement)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton(self._t("cancel"))
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.run_button = QPushButton(self._t("run"))
        self.run_button.setAutoDefault(False)
        self.run_button.setEnabled(not summary.requires_acknowledgement)
        self.acknowledgement.toggled.connect(self.run_button.setEnabled)
        self.run_button.clicked.connect(self.accept)
        buttons.addWidget(self.run_button)
        layout.addLayout(buttons)

    def _t(self, key, **values):
        return summary_text(self.language, key, **values)

    def accept(self):
        if self.summary.requires_acknowledgement and not self.acknowledgement.isChecked():
            return
        super().accept()


class SummaryWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, plan):
        super().__init__()
        self.plan = plan
        self.cancel_event = Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        if self.cancel_event.is_set():
            self.cancelled.emit()
            return
        try:
            result = run_probe("run_summary", {"plan": self.plan}, timeout_seconds=SUMMARY_TIMEOUT_SECONDS,
                               cancel_event=self.cancel_event)
            if result.cancelled or self.cancel_event.is_set():
                self.cancelled.emit()
            elif result.ok and isinstance(result.value, RunChangeSummary):
                self.completed.emit(result.value)
            else:
                self.failed.emit(result.error or "No valid summary was returned.")
        except Exception as exc:
            logger.exception("Run summary analysis failed")
            self.failed.emit(str(exc))


class SummaryProgressDialog(PreflightProgressDialog):
    def __init__(self, worker, config_manager, parent=None, recheck=False):
        self._outcome_finished = False
        self.recheck = recheck
        super().__init__(worker, config_manager, parent)

    def _build_ui(self):
        super()._build_ui()
        self.setWindowTitle(summary_text(self.language, "title"))
        self.message.setText(summary_text(self.language, "rechecking" if self.recheck else "analyzing"))

    def cancel(self):
        self.worker.cancel()
        self.cancel_button.setEnabled(False)

    def reject(self):
        # Escape/close must not dispose a worker still preparing or scanning.
        if not self._outcome_finished:
            self.cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if not self._outcome_finished:
            self.cancel()
            event.ignore()
            return
        super().closeEvent(event)

    def _completed(self, report):
        self._outcome_finished = True
        super()._completed(report)

    def _failed(self, error):
        self._outcome_finished = True
        super()._failed(error)

    def _cancelled(self):
        self._outcome_finished = True
        super()._cancelled()


def analyze_run_summary(parent, plan, config_manager, *, visible=True, recheck=False):
    """Analyze in a disposable process with a responsive Qt event loop."""
    worker = SummaryWorker(plan)
    if visible:
        dialog = SummaryProgressDialog(worker, config_manager, parent, recheck)
        dialog.exec()
        worker.wait()
        return dialog.report, dialog.error, dialog.was_cancelled
    outcome = {"summary": None, "error": "", "cancelled": False}
    loop = QEventLoop(parent)

    def finish(summary=None, error="", cancelled=False):
        outcome.update(summary=summary, error=error, cancelled=cancelled)
        loop.quit()

    worker.completed.connect(lambda summary: finish(summary=summary))
    worker.failed.connect(lambda error: finish(error=error))
    worker.cancelled.connect(lambda: finish(cancelled=True))
    worker.start()
    loop.exec()
    worker.wait()
    return outcome["summary"], outcome["error"], outcome["cancelled"]


def confirm_run_summary(parent, plan, config_manager, *, scheduled=False, warnings="") -> bool:
    """Confirm manual runs; scheduled runs log estimates without asking a question."""
    language = get_app_language(config_manager)
    window = parent.window()
    if getattr(window, "_run_confirmation_active", False):
        return False
    window._run_confirmation_active = True
    try:
        summary, error, cancelled = analyze_run_summary(parent, plan, config_manager, visible=not scheduled)
        if summary is None:
            if error:
                logger.warning("Run summary failed: %s", error)
            if scheduled:
                # Keep the pre-existing unattended dependency/consent policy.
                # An unavailable preview must never be reported as zero changes.
                logger.warning("Scheduled change summary unavailable; continuing under the existing preflight and consent policy.")
                return True
            if not cancelled:
                QMessageBox.warning(parent, summary_text(language, "title"), summary_text(language, "failed"))
            return False
        if scheduled:
            logger.info("Scheduled change summary (estimates): %s; policies: %s; notes: %s",
                        summary.counts, summary.risks, summary.notes)
            return True
        if RunSummaryDialog(summary, language, parent, warnings).exec() != QDialog.DialogCode.Accepted:
            return False
        refreshed, error, cancelled = analyze_run_summary(parent, plan, config_manager, recheck=True)
        if refreshed is None:
            if not cancelled:
                QMessageBox.warning(parent, summary_text(language, "title"), summary_text(language, "failed"))
            return False
        if refreshed.fingerprint != summary.fingerprint:
            QMessageBox.warning(parent, summary_text(language, "title"), summary_text(language, "stale"))
            return False
        return True
    finally:
        window._run_confirmation_active = False

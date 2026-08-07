from __future__ import annotations

import logging
import os
import time
import traceback
from dataclasses import dataclass
from typing import Callable

from src.core.bypass_converter import BypassConverter
from src.core.eml_converter import EMLConverter
from src.core.ocr_processor import OCRProcessor
from src.core.pdf_converter import PDFConverter
from src.core.sync_manager import SyncManager
from src.core.task_contracts import (
    BypassRunConfig,
    EmlRunConfig,
    OcrRunConfig,
    PdfRunConfig,
    RunPlan,
    RunReport,
    StepResult,
    StepStatus,
    SyncRunConfig,
    TaskStep,
)
from src.ui.i18n import get_app_language, tr

logger = logging.getLogger(__name__)


@dataclass
class RunnerCallbacks:
    log: Callable[[str], None] = lambda _message: None
    step_progress: Callable[[int, int, str], None] = lambda _current, _total, _message: None
    total_progress: Callable[[int], None] = lambda _percent: None
    status_changed: Callable[[TaskStep, StepStatus], None] = lambda _step, _status: None


class TaskRunner:
    """Runs a RunPlan without depending on PyQt widgets or signals."""

    STEP_NAMES = {
        TaskStep.SYNC: "Folder Sync",
        TaskStep.EML: "EML Image",
        TaskStep.PDF: "PDF Image",
        TaskStep.OCR: "Image OCR",
        TaskStep.BYPASS: "Bypass Convert",
    }

    def __init__(self, config_manager, run_plan: RunPlan):
        self.config_manager = config_manager
        self.run_plan = run_plan
        self.language = get_app_language(config_manager)
        self.is_running = True
        self.eml_converter = EMLConverter(self.config_manager)
        self.pdf_converter = PDFConverter(self.config_manager)
        self.ocr_processor = OCRProcessor(self.config_manager)
        self.bypass_converter = BypassConverter()

    def _text(self, english: str, korean: str, polish: str) -> str:
        return {"ko": korean, "pl": polish}.get(self.language, english)

    def _step_name(self, step: TaskStep) -> str:
        return tr(f"task_step_{step.value}", self.language)

    def _status_name(self, status: StepStatus) -> str:
        status_keys = {
            StepStatus.PENDING: "pending",
            StepStatus.RUNNING: "running",
            StepStatus.COMPLETED: "completed",
            StepStatus.PARTIAL: "partial",
            StepStatus.FAILED: "failed",
            StepStatus.CANCELLED: "cancelled",
            StepStatus.SKIPPED: "skipped",
        }
        return tr(f"task_status_{status_keys[status]}", self.language)

    def cancel(self) -> None:
        self.is_running = False
        try:
            self.eml_converter.cancel()
        except Exception:
            pass

    def run(self, callbacks: RunnerCallbacks | None = None) -> RunReport:
        callbacks = callbacks or RunnerCallbacks()
        active_steps = self.run_plan.active_steps
        if not active_steps:
            return RunReport({}, "", tr("task_no_selection_body", self.language), False)

        results = {
            step: StepResult(step=step, status=StepStatus.PENDING)
            for step in active_steps
        }

        callbacks.total_progress(0)
        callbacks.log("=" * 60)
        callbacks.log(self._text(
            "▶ Starting the selected tasks.",
            "▶ 선택한 작업을 시작합니다.",
            "▶ Uruchamianie wybranych zadań.",
        ))
        callbacks.log(
            self._text("Selected features", "선택한 기능", "Wybrane funkcje")
            + f" ({len(active_steps)}): "
            + ", ".join(self._step_name(step) for step in active_steps)
        )
        callbacks.log("=" * 60)

        for index, step in enumerate(active_steps, start=1):
            if not self.is_running:
                result = results[step]
                result.status = StepStatus.CANCELLED
                callbacks.status_changed(step, StepStatus.CANCELLED)
                return RunReport(
                    results,
                    "",
                    self._text("The tasks were stopped by the user.", "사용자가 작업을 중지했습니다.", "Zadania zostały zatrzymane przez użytkownika."),
                    False,
                    cancelled=True,
                )

            callbacks.status_changed(step, StepStatus.RUNNING)
            results[step].status = StepStatus.RUNNING

            try:
                if step == TaskStep.SYNC:
                    self._run_sync(self.run_plan.get(step), results[step], callbacks)
                elif step == TaskStep.EML:
                    self._run_eml(self.run_plan.get(step), results[step], callbacks)
                elif step == TaskStep.PDF:
                    self._run_pdf(self.run_plan.get(step), results[step], callbacks)
                elif step == TaskStep.OCR:
                    self._run_ocr(self.run_plan.get(step), results[step], callbacks)
                elif step == TaskStep.BYPASS:
                    self._run_bypass(self.run_plan.get(step), results[step], callbacks)
            except Exception as exc:
                err_trace = traceback.format_exc()
                logger.error("Error in %s step: %s\n%s", step.value, exc, err_trace)
                results[step].status = StepStatus.FAILED
                results[step].error_message = str(exc)
                results[step].details.append(
                    self._text("Fatal error", "치명적 오류", "Błąd krytyczny") + f": {exc}"
                )

            callbacks.status_changed(step, results[step].status)
            callbacks.total_progress(int(index / len(active_steps) * 100))

        if not self.is_running:
            return RunReport(
                results,
                "",
                self._text("The tasks were stopped by the user.", "사용자가 작업을 중지했습니다.", "Zadania zostały zatrzymane przez użytkownika."),
                False,
                cancelled=True,
            )

        report_body = self._build_report(results, active_steps)
        callbacks.total_progress(100)
        callbacks.log("\n" + "=" * 60)
        callbacks.log(self._text(
            "🎉 All selected tasks have finished!",
            "🎉 선택한 모든 작업이 끝났습니다!",
            "🎉 Wszystkie wybrane zadania zostały zakończone!",
        ))
        callbacks.log("=" * 60)

        overall_success = all(results[step].status == StepStatus.COMPLETED for step in active_steps)
        message = (
            self._text("The selected tasks completed successfully.", "선택한 작업이 완료되었습니다.", "Wybrane zadania zakończyły się pomyślnie.")
            if overall_success
            else self._text("The tasks finished, but some items failed. Check the result report.", "작업은 끝났지만 일부 항목이 실패했습니다. 결과 보고서를 확인해 주세요.", "Zadania zakończono, ale niektóre elementy nie powiodły się. Sprawdź raport.")
        )
        return RunReport(results, report_body, message, overall_success)

    def _run_sync(self, config: SyncRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[1] " + self._step_name(TaskStep.SYNC))
        total_groups = len(config.sync_groups)
        success_count = 0

        for idx, group in enumerate(config.sync_groups):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return

            callbacks.log(self._text(
                f" -> Analyzing and synchronizing group [{group.name}]...",
                f" -> 그룹 [{group.name}] 분석 및 동기화 중...",
                f" -> Analizowanie i synchronizowanie grupy [{group.name}]...",
            ))
            callbacks.step_progress(idx, total_groups, self._text(
                f"Synchronizing group: {group.name}",
                f"그룹 동기화 중: {group.name}",
                f"Synchronizowanie grupy: {group.name}",
            ))
            manager = SyncManager(folders=group.folders, move_to_deleted=group.move_to_deleted)
            actions = manager.analyze_sync()
            success_files, fail_files, errors = manager.execute_sync(actions)

            if not errors:
                success_count += 1
                msg = self._text(
                    f"✓ Group [{group.name}] completed (successful: {success_files}, failed: {fail_files})",
                    f"✓ 그룹 [{group.name}] 완료 (성공: {success_files}건, 실패: {fail_files}건)",
                    f"✓ Grupa [{group.name}] zakończona (powodzenie: {success_files}, błędy: {fail_files})",
                )
            else:
                msg = self._text(
                    f"⚠ Group [{group.name}] completed with errors (successful: {success_files}, failed: {fail_files})",
                    f"⚠ 그룹 [{group.name}] 일부 오류 발생 (성공: {success_files}건, 실패: {fail_files}건)",
                    f"⚠ Grupa [{group.name}] zakończona z błędami (powodzenie: {success_files}, błędy: {fail_files})",
                )
                for err in errors[:5]:
                    callbacks.log(f"     - {self._text('Error', '오류', 'Błąd')}: {err}")
            callbacks.log(f"   {msg}")
            result.details.append(msg)
            result.details.extend(f"{self._text('Error', '오류', 'Błąd')}: {err}" for err in errors[:5])

        result.success_count = success_count
        result.total_count = total_groups
        result.status = StepStatus.COMPLETED if success_count == total_groups else StepStatus.PARTIAL
        callbacks.step_progress(
            total_groups,
            total_groups,
            self._text("Folder synchronization completed", "폴더 동기화 완료", "Synchronizacja folderów zakończona"),
        )

    def _run_eml(self, config: EmlRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[2단계: EML Image 파일 변환 진행]")
        total_tasks = len(config.tasks)
        success_tasks = 0

        for idx, task in enumerate(config.tasks):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return

            callbacks.log(f" -> 태스크 [{task.name}] EML 파일 변환 시작...")
            callbacks.step_progress(idx, total_tasks, f"EML 태스크 진행 중: {task.name}")
            os.makedirs(task.target_folder, exist_ok=True)
            eml_files = [
                os.path.join(task.source_folder, name)
                for name in os.listdir(task.source_folder)
                if name.lower().endswith(".eml")
            ]

            if not eml_files:
                msg = f"태스크 [{task.name}] EML 파일 없음 (건너뜀)"
                callbacks.log(f"   ✗ 경고: '{task.name}' 폴더 내에 EML 파일이 없습니다.")
                result.details.append(msg)
                continue

            task_success_count = 0
            for file_idx, eml_path in enumerate(eml_files):
                if not self.is_running:
                    result.status = StepStatus.CANCELLED
                    return
                filename = os.path.basename(eml_path)
                callbacks.step_progress(file_idx, len(eml_files), f"EML 변환 중: {filename}")
                out_png = os.path.join(task.target_folder, os.path.splitext(filename)[0] + ".png")
                try:
                    if self.eml_converter.convert_eml_to_image(eml_path, out_png, width=config.width):
                        task_success_count += 1
                    else:
                        callbacks.log(f"      ✗ 변환 실패: {filename}")
                except Exception as file_err:
                    callbacks.log(f"      ✗ 오류 발생 ({filename}): {file_err}")

            if task_success_count == len(eml_files):
                success_tasks += 1
                msg = f"✓ 태스크 [{task.name}] 완료 (성공: {task_success_count}/{len(eml_files)})"
            else:
                msg = f"⚠ 태스크 [{task.name}] 일부 완료 (성공: {task_success_count}/{len(eml_files)})"
            callbacks.log(f"   {msg}")
            result.details.append(msg)

        result.success_count = success_tasks
        result.total_count = total_tasks
        result.status = StepStatus.COMPLETED if success_tasks == total_tasks else StepStatus.PARTIAL
        callbacks.step_progress(total_tasks, total_tasks, "EML Image 변환 완료")

    def _run_pdf(self, config: PdfRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[3단계: PDF Image 변환 진행]")
        os.makedirs(config.output_folder, exist_ok=True)
        success_count = 0

        for idx, pdf_path in enumerate(config.pdf_paths):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return
            filename = os.path.basename(pdf_path)
            callbacks.log(f" -> PDF 변환 중: {filename}...")
            callbacks.step_progress(idx, len(config.pdf_paths), f"PDF 변환 진행 중: {filename}")
            try:
                image_paths = self.pdf_converter.convert(pdf_path, config.output_folder)
                success_count += 1
                msg = f"✓ PDF [{filename}] 완료 -> 이미지 {len(image_paths)}개 생성"
            except Exception as file_err:
                msg = f"✗ PDF [{filename}] 변환 실패: {file_err}"
            callbacks.log(f"   {msg}")
            result.details.append(msg)

        result.success_count = success_count
        result.total_count = len(config.pdf_paths)
        result.status = StepStatus.COMPLETED if success_count == len(config.pdf_paths) else StepStatus.PARTIAL
        callbacks.step_progress(len(config.pdf_paths), len(config.pdf_paths), "PDF Image 변환 완료")

    def _run_ocr(self, config: OcrRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[4단계: Image OCR 리네임 진행]")
        success_count = 0

        for idx, img_path in enumerate(config.image_paths):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return
            filename = os.path.basename(img_path)
            callbacks.log(f" -> OCR 분석 중: {filename}...")
            callbacks.step_progress(idx, len(config.image_paths), f"OCR 진행 중: {filename}")
            try:
                success, promo_num, _ocr_text, error_msg = self.ocr_processor.process_image(img_path)
                if success and promo_num:
                    final_filename = self._rename_ocr_file(img_path, promo_num)
                    success_count += 1
                    msg = f"✓ OCR 성공: {filename} -> {final_filename} (프로모션: {promo_num})"
                else:
                    msg = f"✗ OCR 분석 실패 (프로모션 미발견): {filename} ({error_msg or '미인식'})"
            except Exception as file_err:
                msg = f"✗ OCR 파일 분석 오류 ({filename}): {file_err}"
            callbacks.log(f"   {msg}")
            result.details.append(msg)

        result.success_count = success_count
        result.total_count = len(config.image_paths)
        result.status = StepStatus.COMPLETED if success_count == len(config.image_paths) else StepStatus.PARTIAL
        callbacks.step_progress(len(config.image_paths), len(config.image_paths), "Image OCR 완료")

    def _run_bypass(self, config: BypassRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[5단계: Bypass Convert 우회 변환 진행]")
        success_count = 0

        for idx, task in enumerate(config.tasks):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return
            filename = os.path.basename(task.src)
            callbacks.log(f" -> 우회 변환 중: {filename} -> {task.ext}...")
            callbacks.step_progress(idx, len(config.tasks), f"우회 변환 진행 중: {filename}")
            try:
                success, msg = self.bypass_converter.convert_file(
                    src_path=task.src,
                    tgt_path=task.tgt,
                    target_ext=task.ext,
                    preserve_meta=task.preserve_meta,
                    delete_original=task.delete_original,
                )
                if success:
                    success_count += 1
                    rep_msg = f"✓ 우회 완료: {filename} -> {os.path.basename(task.tgt)}"
                else:
                    rep_msg = f"✗ 우회 실패 ({filename}): {msg}"
            except Exception as file_err:
                rep_msg = f"✗ 우회 파일 변환 오류 ({filename}): {file_err}"
            callbacks.log(f"   {rep_msg}")
            result.details.append(rep_msg)

        result.success_count = success_count
        result.total_count = len(config.tasks)
        result.status = StepStatus.COMPLETED if success_count == len(config.tasks) else StepStatus.PARTIAL
        callbacks.step_progress(len(config.tasks), len(config.tasks), "Bypass Convert 완료")

    def _rename_ocr_file(self, image_path: str, promo_num: str) -> str:
        filename = os.path.basename(image_path)
        ext = os.path.splitext(filename)[1]
        dir_path = os.path.dirname(image_path)
        target_path = os.path.join(dir_path, f"{promo_num}{ext}")

        if os.path.exists(target_path) and target_path != image_path:
            counter = 1
            while True:
                target_path = os.path.join(dir_path, f"{promo_num}_{counter}{ext}")
                if not os.path.exists(target_path):
                    break
                counter += 1

        if target_path != image_path:
            if os.path.exists(target_path):
                os.chmod(target_path, 0o777)
                os.remove(target_path)
            os.chmod(image_path, 0o777)
            os.rename(image_path, target_path)
        return os.path.basename(target_path)

    def _build_report(self, results: dict[TaskStep, StepResult], active_steps: list[TaskStep]) -> str:
        report_lines = [
            self._text("# Task Result Report", "# 작업 실행 결과 보고서", "# Raport wyników zadań"),
            self._text("- **Run time**", "- **실행 일시**", "- **Czas uruchomienia**") + f": {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            self._text("## [1] Status summary", "## [1] 기능별 상태 요약", "## [1] Podsumowanie stanu"),
            self._text("| Feature | Status | Successful / Total |", "| 기능 | 상태 | 성공 / 전체 |", "| Funkcja | Stan | Powodzenie / Razem |"),
            "| :--- | :--- | :--- |",
        ]
        for step in active_steps:
            result = results[step]
            report_lines.append(
                f"| {self._step_name(step)} | {self._status_name(result.status)} | "
                f"{result.success_count} / {result.total_count} |"
            )

        report_lines.extend(["", self._text("## [2] Details", "## [2] 상세 내역", "## [2] Szczegóły")])
        for step in active_steps:
            result = results[step]
            report_lines.append(f"### 📍 {self._step_name(step)}")
            if result.details:
                report_lines.extend(f"- {line}" for line in result.details)
            else:
                report_lines.append(self._text("- No detail entries.", "- 상세 내역이 없습니다.", "- Brak szczegółów."))
            report_lines.append("")
        return "\n".join(report_lines)

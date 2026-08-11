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
    SourceDisposition,
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

    def _runtime_text(self, value: object) -> str:
        text = str(value)
        if self.language == "ko":
            return text
        replacements = {
            "프로모션 번호를 찾을 수 없습니다": "Promotion number not found",
            "원본 파일을 찾을 수 없습니다": "Source file not found",
            "파일이 이미 다른 프로그램에서 사용 중입니다": "The file is open in another application",
            "지원하지 않는 원본 파일 형식입니다": "Unsupported source file type",
            "변환 실패": "Conversion failed",
            "변환 중 오류": "Conversion error",
            "압축 중 오류": "Compression error",
            "복제 오류": "Copy error",
            "PDF 파일을 찾을 수 없습니다": "PDF file not found",
            "PDF 변환 중 오류 발생": "PDF conversion error",
            "to_be_deleted이동": "move to 'to be deleted'",
            "충돌 보존 백업": "preserve conflict backup",
            "복사": "copy",
            "Playwright 브라우저 드라이버": "Playwright browser driver",
            "네트워크 연결 상태를 확인해 주세요": "Check the network connection",
        }
        for korean, english in replacements.items():
            text = text.replace(korean, english)
        return text

    def _bypass_message(self, value: object) -> str:
        text = str(value)
        marker, _separator, detail = text.partition("|")
        if marker == "SOURCE_KEPT":
            return self._text("source kept", "원본 보존", "źródło zachowane")
        if marker == "SOURCE_BACKED_UP":
            return self._text(
                f"source backed up: {detail}",
                f"원본 백업 이동: {detail}",
                f"kopia źródła: {detail}",
            )
        if marker == "SOURCE_BACKED_UP_MANIFEST_WARNING":
            backup_path, _separator, error = detail.partition("|")
            return self._text(
                f"source backed up, but recovery history was not recorded: {backup_path} ({error})",
                f"원본 백업 이동 완료, 복구 이력 기록 실패: {backup_path} ({error})",
                f"kopia źródła utworzona, ale nie zapisano historii: {backup_path} ({error})",
            )
        if marker == "SOURCE_BACKUP_FAILED":
            return self._text(
                f"conversion succeeded, but source backup failed: {detail}",
                f"변환 성공 후 원본 백업 이동 실패: {detail}",
                f"konwersja udana, ale kopia źródła nie powiodła się: {detail}",
            )
        if marker == "OUTPUT_NOT_CREATED":
            return self._text(
                f"output file was not created: {detail}",
                f"출력 파일이 생성되지 않음: {detail}",
                f"plik wyjściowy nie został utworzony: {detail}",
            )
        if marker == "SOURCE_TARGET_SAME":
            return self._text(
                f"source and output paths are identical: {detail}",
                f"원본과 출력 경로가 동일함: {detail}",
                f"ścieżki źródłowa i wyjściowa są identyczne: {detail}",
            )
        if marker == "TARGET_ALREADY_EXISTS":
            return self._text(
                f"output path already exists: {detail}",
                f"출력 경로에 파일이 이미 있음: {detail}",
                f"plik wyjściowy już istnieje: {detail}",
            )
        if marker == "OUTPUT_EMPTY":
            return self._text(
                f"the output file is empty: {detail}",
                f"출력 파일이 비어 있음: {detail}",
                f"plik wyjściowy jest pusty: {detail}",
            )
        return self._runtime_text(value)

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
                results[step].error_message = self._runtime_text(exc)
                results[step].details.append(
                    self._text("Fatal error", "치명적 오류", "Błąd krytyczny") + f": {self._runtime_text(exc)}"
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
            success_files, fail_files, errors = manager.execute_sync(
                actions,
                progress_callback=lambda current, total, filename: callbacks.step_progress(
                    current,
                    total,
                    self._text(
                        f"Synchronizing file: {filename}",
                        f"파일 동기화 중: {filename}",
                        f"Synchronizowanie pliku: {filename}",
                    ),
                ),
            )

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
                    callbacks.log(f"     - {self._text('Error', '오류', 'Błąd')}: {self._runtime_text(err)}")
            callbacks.log(f"   {msg}")
            result.details.append(msg)
            result.details.extend(f"{self._text('Error', '오류', 'Błąd')}: {self._runtime_text(err)}" for err in errors[:5])

        result.success_count = success_count
        result.total_count = total_groups
        result.status = StepStatus.COMPLETED if success_count == total_groups else StepStatus.PARTIAL
        callbacks.step_progress(
            total_groups,
            total_groups,
            self._text("Folder synchronization completed", "폴더 동기화 완료", "Synchronizacja folderów zakończona"),
        )

    def _run_eml(self, config: EmlRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[2] " + self._step_name(TaskStep.EML))
        total_tasks = len(config.tasks)
        success_tasks = 0

        for idx, task in enumerate(config.tasks):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return

            callbacks.log(self._text(f" -> Starting EML task [{task.name}]...", f" -> 태스크 [{task.name}] EML 파일 변환 시작...", f" -> Uruchamianie zadania EML [{task.name}]..."))
            callbacks.step_progress(idx, total_tasks, self._text(f"Running EML task: {task.name}", f"EML 태스크 진행 중: {task.name}", f"Uruchamianie zadania EML: {task.name}"))
            os.makedirs(task.target_folder, exist_ok=True)
            eml_files = [
                os.path.join(task.source_folder, name)
                for name in os.listdir(task.source_folder)
                if name.lower().endswith(".eml")
            ]

            if not eml_files:
                msg = self._text(f"Task [{task.name}] has no EML files (skipped)", f"태스크 [{task.name}] EML 파일 없음 (건너뜀)", f"Zadanie [{task.name}] nie zawiera plików EML (pominięto)")
                callbacks.log(self._text(f"   ✗ Warning: '{task.name}' contains no EML files.", f"   ✗ 경고: '{task.name}' 폴더 내에 EML 파일이 없습니다.", f"   ✗ Ostrzeżenie: '{task.name}' nie zawiera plików EML."))
                result.details.append(msg)
                continue

            task_success_count = 0
            for file_idx, eml_path in enumerate(eml_files):
                if not self.is_running:
                    result.status = StepStatus.CANCELLED
                    return
                filename = os.path.basename(eml_path)
                callbacks.step_progress(file_idx, len(eml_files), self._text(f"Converting EML: {filename}", f"EML 변환 중: {filename}", f"Konwersja EML: {filename}"))
                out_png = os.path.join(task.target_folder, os.path.splitext(filename)[0] + ".png")
                try:
                    if self.eml_converter.convert_eml_to_image(eml_path, out_png, width=config.width):
                        task_success_count += 1
                    else:
                        callbacks.log(self._text(f"      ✗ Conversion failed: {filename}", f"      ✗ 변환 실패: {filename}", f"      ✗ Konwersja nie powiodła się: {filename}"))
                except Exception as file_err:
                    detail = self._runtime_text(file_err)
                    callbacks.log(self._text(f"      ✗ Error ({filename}): {detail}", f"      ✗ 오류 발생 ({filename}): {detail}", f"      ✗ Błąd ({filename}): {detail}"))

            if task_success_count == len(eml_files):
                success_tasks += 1
                msg = self._text(f"✓ Task [{task.name}] completed ({task_success_count}/{len(eml_files)} successful)", f"✓ 태스크 [{task.name}] 완료 (성공: {task_success_count}/{len(eml_files)})", f"✓ Zadanie [{task.name}] zakończone ({task_success_count}/{len(eml_files)} powodzeń)" )
            else:
                msg = self._text(f"⚠ Task [{task.name}] partially completed ({task_success_count}/{len(eml_files)} successful)", f"⚠ 태스크 [{task.name}] 일부 완료 (성공: {task_success_count}/{len(eml_files)})", f"⚠ Zadanie [{task.name}] częściowo zakończone ({task_success_count}/{len(eml_files)} powodzeń)")
            callbacks.log(f"   {msg}")
            result.details.append(msg)

        result.success_count = success_tasks
        result.total_count = total_tasks
        result.status = StepStatus.COMPLETED if success_tasks == total_tasks else StepStatus.PARTIAL
        callbacks.step_progress(total_tasks, total_tasks, self._text("EML conversion completed", "EML 변환 완료", "Konwersja EML zakończona"))

    def _run_pdf(self, config: PdfRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[3] " + self._step_name(TaskStep.PDF))
        os.makedirs(config.output_folder, exist_ok=True)
        success_count = 0

        for idx, pdf_path in enumerate(config.pdf_paths):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return
            filename = os.path.basename(pdf_path)
            callbacks.log(self._text(f" -> Converting PDF: {filename}...", f" -> PDF 변환 중: {filename}...", f" -> Konwersja PDF: {filename}..."))
            callbacks.step_progress(idx, len(config.pdf_paths), self._text(f"Converting PDF: {filename}", f"PDF 변환 진행 중: {filename}", f"Konwersja PDF: {filename}"))
            try:
                image_paths = self.pdf_converter.convert(
                    pdf_path,
                    config.output_folder,
                    progress_callback=lambda current, total, _message, filename=filename: callbacks.step_progress(
                        current,
                        total,
                        self._text(
                            f"Converting PDF: {filename} ({current}/{total})",
                            f"PDF 변환 중: {filename} ({current}/{total})",
                            f"Konwersja PDF: {filename} ({current}/{total})",
                        ),
                    ),
                )
                success_count += 1
                msg = self._text(f"✓ PDF [{filename}] completed -> {len(image_paths)} images created", f"✓ PDF [{filename}] 완료 -> 이미지 {len(image_paths)}개 생성", f"✓ PDF [{filename}] zakończony -> utworzono {len(image_paths)} obrazów")
            except Exception as file_err:
                detail = self._runtime_text(file_err)
                msg = self._text(f"✗ PDF [{filename}] conversion failed: {detail}", f"✗ PDF [{filename}] 변환 실패: {detail}", f"✗ Konwersja PDF [{filename}] nie powiodła się: {detail}")
            callbacks.log(f"   {msg}")
            result.details.append(msg)

        result.success_count = success_count
        result.total_count = len(config.pdf_paths)
        result.status = StepStatus.COMPLETED if success_count == len(config.pdf_paths) else StepStatus.PARTIAL
        callbacks.step_progress(len(config.pdf_paths), len(config.pdf_paths), self._text("PDF conversion completed", "PDF 변환 완료", "Konwersja PDF zakończona"))

    def _run_ocr(self, config: OcrRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[4] " + self._step_name(TaskStep.OCR))
        success_count = 0

        for idx, img_path in enumerate(config.image_paths):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return
            filename = os.path.basename(img_path)
            callbacks.log(self._text(f" -> Running OCR: {filename}...", f" -> OCR 분석 중: {filename}...", f" -> OCR: {filename}..."))
            callbacks.step_progress(idx, len(config.image_paths), self._text(f"Running OCR: {filename}", f"OCR 진행 중: {filename}", f"OCR: {filename}"))
            try:
                success, promo_num, _ocr_text, error_msg = self.ocr_processor.process_image(img_path)
                if success and promo_num:
                    final_filename = self._rename_ocr_file(img_path, promo_num)
                    success_count += 1
                    msg = self._text(f"✓ OCR succeeded: {filename} -> {final_filename} (promotion: {promo_num})", f"✓ OCR 성공: {filename} -> {final_filename} (프로모션: {promo_num})", f"✓ OCR zakończony: {filename} -> {final_filename} (promocja: {promo_num})")
                else:
                    detail = self._runtime_text(error_msg or self._text("not recognized", "미인식", "nierozpoznano"))
                    msg = self._text(f"✗ OCR failed (promotion not found): {filename} ({detail})", f"✗ OCR 분석 실패 (프로모션 미발견): {filename} ({detail})", f"✗ OCR nie powiódł się (brak promocji): {filename} ({detail})")
            except Exception as file_err:
                detail = self._runtime_text(file_err)
                msg = self._text(f"✗ OCR file error ({filename}): {detail}", f"✗ OCR 파일 분석 오류 ({filename}): {detail}", f"✗ Błąd pliku OCR ({filename}): {detail}")
            callbacks.log(f"   {msg}")
            result.details.append(msg)

        result.success_count = success_count
        result.total_count = len(config.image_paths)
        result.status = StepStatus.COMPLETED if success_count == len(config.image_paths) else StepStatus.PARTIAL
        callbacks.step_progress(len(config.image_paths), len(config.image_paths), self._text("Image OCR completed", "이미지 OCR 완료", "OCR obrazów zakończony"))

    def _run_bypass(self, config: BypassRunConfig, result: StepResult, callbacks: RunnerCallbacks) -> None:
        callbacks.log("\n[5] " + self._step_name(TaskStep.BYPASS))
        if config.source_disposition == SourceDisposition.REPLACE:
            detail = self._text(
                "Source replacement must be confirmed and started directly from Convert Files because it recycles old sources and may permanently delete them when recycling is unavailable.",
                "원본 교체는 기존 원본을 휴지통으로 이동하고 불가능할 때 영구 삭제할 수 있으므로 파일 변환 화면에서 확인한 뒤 직접 실행해야 합니다.",
                "Zastąpienie źródeł wymaga potwierdzenia w Konwertuj pliki, ponieważ przenosi stare źródła do Kosza, a gdy to niemożliwe, może je trwale usunąć.",
            )
            callbacks.log(f"   ✗ {detail}")
            result.details.append(detail)
            result.error_message = detail
            result.success_count = 0
            result.total_count = len(config.tasks)
            result.status = StepStatus.FAILED
            return
        success_count = 0

        for idx, task in enumerate(config.tasks):
            if not self.is_running:
                result.status = StepStatus.CANCELLED
                return
            filename = os.path.basename(task.src)
            callbacks.log(self._text(f" -> Converting file: {filename} -> {task.ext}...", f" -> 파일 변환 중: {filename} -> {task.ext}...", f" -> Konwersja pliku: {filename} -> {task.ext}..."))
            callbacks.step_progress(idx, len(config.tasks), self._text(f"Converting file: {filename}", f"파일 변환 중: {filename}", f"Konwersja pliku: {filename}"))
            try:
                success, msg = self.bypass_converter.convert_file(
                    src_path=task.src,
                    tgt_path=task.tgt,
                    target_ext=task.ext,
                    preserve_meta=task.preserve_meta,
                    source_disposition=task.source_disposition,
                )
                if success:
                    success_count += 1
                    disposition_detail = self._bypass_message(msg)
                    rep_msg = self._text(f"✓ Conversion completed: {filename} -> {os.path.basename(task.tgt)}", f"✓ 파일 변환 완료: {filename} -> {os.path.basename(task.tgt)}", f"✓ Konwersja zakończona: {filename} -> {os.path.basename(task.tgt)}") + f" ({disposition_detail})"
                else:
                    detail = self._bypass_message(msg)
                    rep_msg = self._text(f"✗ Conversion failed ({filename}): {detail}", f"✗ 파일 변환 실패 ({filename}): {detail}", f"✗ Konwersja nie powiodła się ({filename}): {detail}")
            except Exception as file_err:
                detail = self._runtime_text(file_err)
                rep_msg = self._text(f"✗ File conversion error ({filename}): {detail}", f"✗ 파일 변환 오류 ({filename}): {detail}", f"✗ Błąd konwersji pliku ({filename}): {detail}")
            callbacks.log(f"   {rep_msg}")
            result.details.append(rep_msg)

        result.success_count = success_count
        result.total_count = len(config.tasks)
        result.status = StepStatus.COMPLETED if success_count == len(config.tasks) else StepStatus.PARTIAL
        callbacks.step_progress(len(config.tasks), len(config.tasks), self._text("File conversion completed", "파일 변환 완료", "Konwersja plików zakończona"))

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

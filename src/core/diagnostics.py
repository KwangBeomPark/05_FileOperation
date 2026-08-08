from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from enum import Enum
from threading import Event

from src.core.preflight import (
    check_office_apps,
    check_office_imports,
    check_ocr_engines,
    check_playwright_driver,
    required_office_apps,
)
from src.core.task_contracts import (
    BypassRunConfig,
    EmlRunConfig,
    OcrRunConfig,
    PdfRunConfig,
    RunPlan,
    SourceDisposition,
    SyncRunConfig,
    TaskStep,
)
from src.core.probe_runner import (
    DEPENDENCY_TIMEOUT_SECONDS,
    OFFICE_TIMEOUT_SECONDS,
    PATH_TIMEOUT_SECONDS,
    SMTP_TIMEOUT_SECONDS,
    ProbeResult,
    run_probe,
)
from src.ui.i18n import choose, get_app_language


class DiagnosticStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True)
class DiagnosticItem:
    code: str
    title: str
    status: DiagnosticStatus
    detail: str
    target: str


class DiagnosticsCancelled(RuntimeError):
    pass


def _probe_error_detail(language: str, result: ProbeResult, label: str) -> str:
    if result.timed_out:
        return choose(
            language,
            f"{label} timed out after {result.elapsed_seconds:.1f} seconds. Check the connection or application, then try again.",
            f"{label} 검사가 {result.elapsed_seconds:.1f}초 후 시간 초과되었습니다. 연결 또는 프로그램 상태를 확인한 뒤 다시 시도하세요.",
            f"Kontrola {label} przekroczyła limit {result.elapsed_seconds:.1f} s. Sprawdź połączenie lub aplikację i spróbuj ponownie.",
        )
    return choose(
        language,
        f"{label} could not be checked: {result.error}",
        f"{label} 검사 실패: {result.error}",
        f"Nie można sprawdzić {label}: {result.error}",
    )


def _path_probe_failures(language: str, failures: list[dict[str, str]]) -> list[str]:
    messages = []
    for failure in failures:
        path = failure.get("path", "")
        kind = failure.get("kind")
        if kind == "missing_file":
            messages.append(choose(language, f"Missing file: {path}", f"파일 없음: {path}", f"Brak pliku: {path}"))
        elif kind == "unreadable_file":
            messages.append(choose(language, f"Cannot read file: {path}", f"파일 읽기 불가: {path}", f"Brak odczytu pliku: {path}"))
        elif kind == "missing_folder":
            messages.append(choose(language, f"Missing folder: {path}", f"폴더 없음: {path}", f"Brak folderu: {path}"))
        elif kind == "unavailable_folder":
            error = failure.get("error", "")
            messages.append(choose(language, f"Cannot open folder: {path} ({error})", f"폴더 접근 불가: {path} ({error})", f"Brak dostępu do folderu: {path} ({error})"))
        elif kind == "unwritable_folder":
            messages.append(choose(language, f"Folder is not writable: {path}", f"폴더 쓰기 불가: {path}", f"Brak zapisu w folderze: {path}"))
    return messages


def _check_path_access(
    title: str,
    code: str,
    target: str,
    *,
    files: list[str] | None = None,
    read_folders: list[str] | None = None,
    write_folders: list[str] | None = None,
    language: str = "en",
    isolated: bool = False,
    cancel_event: Event | None = None,
) -> DiagnosticItem:
    files = sorted(set(files or []))
    read_folders = sorted(set(read_folders or []))
    write_folders = sorted(set(write_folders or []))
    failures: list[str] = []

    if isolated:
        result = run_probe(
            "path_access",
            {"files": files, "read_folders": read_folders, "write_folders": write_folders},
            timeout_seconds=PATH_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
        if result.cancelled:
            raise DiagnosticsCancelled()
        if not result.ok:
            return DiagnosticItem(code, title, DiagnosticStatus.FAIL, _probe_error_detail(language, result, title), target)
        failures = _path_probe_failures(language, list(result.value.get("failures") or []))
        checked_count = int(result.value.get("checked_count", 0))
        if failures:
            return DiagnosticItem(code, title, DiagnosticStatus.FAIL, "\n".join(failures), target)
        detail = choose(
            language,
            f"Accessible paths: {checked_count}",
            f"접근 가능한 경로: {checked_count}개",
            f"Dostępne ścieżki: {checked_count}",
        )
        return DiagnosticItem(code, title, DiagnosticStatus.PASS, detail, target)

    for path in files:
        if not os.path.isfile(path):
            failures.append(choose(language, f"Missing file: {path}", f"파일 없음: {path}", f"Brak pliku: {path}"))
        elif not os.access(path, os.R_OK):
            failures.append(choose(language, f"Cannot read file: {path}", f"파일 읽기 불가: {path}", f"Brak odczytu pliku: {path}"))

    for path in sorted(set(read_folders + write_folders)):
        if not os.path.isdir(path):
            failures.append(choose(language, f"Missing folder: {path}", f"폴더 없음: {path}", f"Brak folderu: {path}"))
            continue
        try:
            with os.scandir(path):
                pass
        except OSError as exc:
            failures.append(choose(language, f"Cannot open folder: {path} ({exc})", f"폴더 접근 불가: {path} ({exc})", f"Brak dostępu do folderu: {path} ({exc})"))
            continue
        if path in write_folders and not os.access(path, os.W_OK):
            failures.append(choose(language, f"Folder is not writable: {path}", f"폴더 쓰기 불가: {path}", f"Brak zapisu w folderze: {path}"))

    checked_count = len(files) + len(set(read_folders + write_folders))
    if failures:
        return DiagnosticItem(code, title, DiagnosticStatus.FAIL, "\n".join(failures), target)
    detail = choose(
        language,
        f"Accessible paths: {checked_count}",
        f"접근 가능한 경로: {checked_count}개",
        f"Dostępne ścieżki: {checked_count}",
    )
    return DiagnosticItem(code, title, DiagnosticStatus.PASS, detail, target)


def run_diagnostics(
    run_plan: RunPlan,
    config_manager,
    *,
    auto_email: bool,
    isolated: bool = False,
    cancel_event: Event | None = None,
) -> list[DiagnosticItem]:
    """Run non-destructive connectivity and dependency checks for selected tasks."""
    language = get_app_language(config_manager)
    t = lambda en, ko, pl: choose(language, en, ko, pl)
    items: list[DiagnosticItem] = []

    def ensure_not_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise DiagnosticsCancelled()

    sync_config = run_plan.get(TaskStep.SYNC)
    if isinstance(sync_config, SyncRunConfig):
        folders = [folder for group in sync_config.sync_groups for folder in group.folders]
        items.append(_check_path_access(
            t("Sync folder access", "동기화 폴더 접근", "Dostęp do folderów synchronizacji"),
            "sync_paths",
            TaskStep.SYNC.value,
            read_folders=folders,
            write_folders=folders,
            language=language,
            isolated=isolated,
            cancel_event=cancel_event,
        ))

    eml_config = run_plan.get(TaskStep.EML)
    if isinstance(eml_config, EmlRunConfig):
        items.append(_check_path_access(
            t("EML folder access", "EML 폴더 접근", "Dostęp do folderów EML"),
            "eml_paths",
            TaskStep.EML.value,
            read_folders=[task.source_folder for task in eml_config.tasks],
            write_folders=[task.target_folder for task in eml_config.tasks],
            language=language,
            isolated=isolated,
            cancel_event=cancel_event,
        ))
        ensure_not_cancelled()
        if isolated:
            browser_result = run_probe(
                "playwright_browser",
                timeout_seconds=DEPENDENCY_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            if browser_result.cancelled:
                raise DiagnosticsCancelled()
            ok = bool(browser_result.ok and browser_result.value.get("ok"))
            detail = (
                str(browser_result.value.get("detail", ""))
                if browser_result.ok
                else _probe_error_detail(language, browser_result, t("EML browser", "EML 브라우저", "przeglądarki EML"))
            )
        else:
            ok, detail = check_playwright_driver(check_browser=True)
        items.append(DiagnosticItem(
            "eml_browser",
            t("EML rendering browser", "EML 렌더링 브라우저", "Przeglądarka renderująca EML"),
            DiagnosticStatus.PASS if ok else DiagnosticStatus.FAIL,
            detail,
            TaskStep.EML.value,
        ))

    pdf_config = run_plan.get(TaskStep.PDF)
    if isinstance(pdf_config, PdfRunConfig):
        items.append(_check_path_access(
            t("PDF file and output access", "PDF 파일 및 저장 폴더 접근", "Dostęp do PDF i folderu wyjściowego"),
            "pdf_paths",
            TaskStep.PDF.value,
            files=pdf_config.pdf_paths,
            write_folders=[pdf_config.output_folder],
            language=language,
            isolated=isolated,
            cancel_event=cancel_event,
        ))

    ocr_config = run_plan.get(TaskStep.OCR)
    if isinstance(ocr_config, OcrRunConfig):
        items.append(_check_path_access(
            t("OCR image access", "OCR 이미지 접근", "Dostęp do obrazów OCR"),
            "ocr_paths",
            TaskStep.OCR.value,
            files=ocr_config.image_paths,
            language=language,
            isolated=isolated,
            cancel_event=cancel_event,
        ))
        ensure_not_cancelled()
        if isolated:
            ocr_result = run_probe(
                "ocr_engine",
                {"tesseract_path": config_manager.get("tesseract_path", "")},
                timeout_seconds=DEPENDENCY_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            if ocr_result.cancelled:
                raise DiagnosticsCancelled()
            ok = bool(ocr_result.ok and ocr_result.value.get("ok"))
            detail = (
                str(ocr_result.value.get("detail", ""))
                if ocr_result.ok
                else _probe_error_detail(language, ocr_result, t("OCR engine", "OCR 엔진", "silnika OCR"))
            )
            using_fallback = bool(ocr_result.ok and ocr_result.value.get("using_fallback"))
        else:
            ok, detail, using_fallback = check_ocr_engines(config_manager)
        status = DiagnosticStatus.WARNING if ok and using_fallback else DiagnosticStatus.PASS if ok else DiagnosticStatus.FAIL
        items.append(DiagnosticItem(
            "ocr_engine",
            t("OCR engine", "OCR 엔진", "Silnik OCR"),
            status,
            detail,
            "settings",
        ))

    bypass_config = run_plan.get(TaskStep.BYPASS)
    if isinstance(bypass_config, BypassRunConfig):
        source_files = [task.src for task in bypass_config.tasks]
        output_folders = [os.path.dirname(task.tgt) for task in bypass_config.tasks]
        if bypass_config.source_disposition == SourceDisposition.BACKUP:
            output_folders.extend(os.path.dirname(task.src) for task in bypass_config.tasks)
        items.append(_check_path_access(
            t("Convert Files path access", "파일 변환 경로 접근", "Dostęp do ścieżek konwersji"),
            "bypass_paths",
            TaskStep.BYPASS.value,
            files=source_files,
            write_folders=output_folders,
            language=language,
            isolated=isolated,
            cancel_event=cancel_event,
        ))

        office_apps = required_office_apps(bypass_config)
        if office_apps:
            imports_ok, import_detail = check_office_imports()
            if imports_ok:
                ensure_not_cancelled()
                if isolated:
                    office_result = run_probe(
                        "office_apps",
                        {"apps": office_apps},
                        timeout_seconds=OFFICE_TIMEOUT_SECONDS,
                        cancel_event=cancel_event,
                    )
                    if office_result.cancelled:
                        raise DiagnosticsCancelled()
                    office_ok = bool(office_result.ok and office_result.value.get("ok"))
                    errors = (
                        list(office_result.value.get("errors") or [])
                        if office_result.ok
                        else [_probe_error_detail(language, office_result, t("Office automation", "Office 자동화", "automatyzacji Office"))]
                    )
                else:
                    office_ok, errors = check_office_apps(office_apps)
                detail = t(
                    f"Started successfully: {', '.join(office_apps)}",
                    f"정상 실행: {', '.join(office_apps)}",
                    f"Uruchomiono: {', '.join(office_apps)}",
                ) if office_ok else "\n".join(errors)
            else:
                office_ok = False
                detail = import_detail
            items.append(DiagnosticItem(
                "office_com",
                t("Microsoft Office automation", "Microsoft Office 자동화", "Automatyzacja Microsoft Office"),
                DiagnosticStatus.PASS if office_ok else DiagnosticStatus.FAIL,
                detail,
                TaskStep.BYPASS.value,
            ))

        if (
            bool(config_manager.get("task_schedule_enabled", False))
            and bypass_config.source_disposition == SourceDisposition.BACKUP
            and not bool(config_manager.get("task_schedule_allow_source_backup", False))
        ):
            items.append(DiagnosticItem(
                "scheduled_backup_consent",
                t("Scheduled source-backup consent", "예약 원본 백업 동의", "Zgoda na zaplanowaną kopię źródeł"),
                DiagnosticStatus.FAIL,
                t(
                    "Scheduled source moves are not allowed yet.",
                    "예약 실행의 원본 백업 이동이 아직 허용되지 않았습니다.",
                    "Zaplanowane przenoszenie źródeł nie zostało jeszcze dozwolone.",
                ),
                "tasks",
            ))

    if auto_email:
        server = str(config_manager.get("smtp_server", "")).strip()
        port_value = config_manager.get("smtp_port", "")
        sender = str(config_manager.get("sender_email", "")).strip()
        receiver = str(config_manager.get("receiver_email", "")).strip()
        missing = [
            name
            for name, value in (
                (t("SMTP server", "SMTP 서버", "Serwer SMTP"), server),
                (t("sender", "발신자", "nadawca"), sender),
                (t("recipient", "수신자", "odbiorca"), receiver),
            )
            if not value
        ]
        try:
            port = int(port_value) if port_value else 587
            valid_port = 1 <= port <= 65535
        except (TypeError, ValueError):
            port = 0
            valid_port = False

        if missing or not valid_port:
            detail_parts = []
            if missing:
                detail_parts.append(t(f"Missing settings: {', '.join(missing)}", f"누락된 설정: {', '.join(missing)}", f"Brak ustawień: {', '.join(missing)}"))
            if not valid_port:
                detail_parts.append(t("Invalid SMTP port.", "SMTP 포트가 올바르지 않습니다.", "Nieprawidłowy port SMTP."))
            items.append(DiagnosticItem(
                "smtp_connection",
                t("SMTP server connection", "SMTP 서버 연결", "Połączenie z serwerem SMTP"),
                DiagnosticStatus.FAIL,
                "\n".join(detail_parts),
                "settings",
            ))
        else:
            ensure_not_cancelled()
            if isolated:
                smtp_result = run_probe(
                    "smtp_connect",
                    {"server": server, "port": port, "socket_timeout": SMTP_TIMEOUT_SECONDS},
                    timeout_seconds=SMTP_TIMEOUT_SECONDS + 1,
                    cancel_event=cancel_event,
                )
                if smtp_result.cancelled:
                    raise DiagnosticsCancelled()
                if smtp_result.ok:
                    status = DiagnosticStatus.PASS
                    detail = t(f"Connected to {server}:{port}.", f"{server}:{port}에 연결했습니다.", f"Połączono z {server}:{port}.")
                else:
                    status = DiagnosticStatus.FAIL
                    detail = _probe_error_detail(language, smtp_result, t("SMTP connection", "SMTP 연결", "połączenia SMTP"))
            else:
                try:
                    with socket.create_connection((server, port), timeout=5):
                        pass
                    status = DiagnosticStatus.PASS
                    detail = t(f"Connected to {server}:{port}.", f"{server}:{port}에 연결했습니다.", f"Połączono z {server}:{port}.")
                except OSError as exc:
                    status = DiagnosticStatus.FAIL
                    detail = t(f"Could not connect to {server}:{port}: {exc}", f"{server}:{port} 연결 실패: {exc}", f"Nie można połączyć z {server}:{port}: {exc}")
            items.append(DiagnosticItem(
                "smtp_connection",
                t("SMTP server connection", "SMTP 서버 연결", "Połączenie z serwerem SMTP"),
                status,
                detail,
                "settings",
            ))

    return items

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from threading import Event

from src.core.release_config import DEFAULT_GITHUB_REPOSITORY_SLUG
from src.core.task_contracts import BypassRunConfig, RunPlan, SourceDisposition, TaskStep
from src.core.probe_runner import DEPENDENCY_TIMEOUT_SECONDS, OFFICE_TIMEOUT_SECONDS, ProbeResult, run_probe
from src.ui.i18n import choose, get_app_language


class IssueLevel(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"


@dataclass(frozen=True)
class PreflightIssue:
    level: IssueLevel
    message: str
    detail: str = ""
    step: TaskStep | None = None


@dataclass
class PreflightReport:
    issues: list[PreflightIssue] = field(default_factory=list)
    language: str = "ko"

    @property
    def blockers(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.level == IssueLevel.BLOCKER]

    @property
    def warnings(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.level == IssueLevel.WARNING]

    @property
    def has_blockers(self) -> bool:
        return bool(self.blockers)

    def add_blocker(self, message: str, detail: str = "", step: TaskStep | None = None) -> None:
        self.issues.append(PreflightIssue(IssueLevel.BLOCKER, message, detail, step))

    def add_warning(self, message: str, detail: str = "", step: TaskStep | None = None) -> None:
        self.issues.append(PreflightIssue(IssueLevel.WARNING, message, detail, step))

    def format(self, include_warnings: bool = True, language: str | None = None) -> str:
        selected_language = language or self.language
        selected = self.blockers + (self.warnings if include_warnings else [])
        if not selected:
            return choose(selected_language, "No blocking preflight issues were found.", "사전 점검에서 차단 이슈가 발견되지 않았습니다.", "Kontrola wstępna nie wykryła problemów blokujących.")
        lines = []
        for issue in selected:
            prefix = (
                choose(selected_language, "Blocker", "차단", "Blokada")
                if issue.level == IssueLevel.BLOCKER
                else choose(selected_language, "Warning", "경고", "Ostrzeżenie")
            )
            step = f"[{issue.step.value}] " if issue.step else ""
            line = f"- {prefix}: {step}{issue.message}"
            if issue.detail:
                line += f"\n  {issue.detail}"
            lines.append(line)
        return "\n".join(lines)


def check_tesseract(config_manager) -> tuple[bool, str]:
    try:
        import pytesseract

        tesseract_path = config_manager.get("tesseract_path", "")
        if tesseract_path:
            if not os.path.exists(tesseract_path):
                return False, f"설정된 Tesseract 경로가 존재하지 않습니다: {tesseract_path}"
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        pytesseract.get_tesseract_version()
        return True, "Tesseract OCR 사용 가능"
    except Exception as exc:
        return False, str(exc)


def check_windows_ocr() -> tuple[bool, str]:
    try:
        from src.core.windows_ocr import windows_ocr_available

        return windows_ocr_available()
    except Exception as exc:
        return False, str(exc)


def check_ocr_engines(config_manager) -> tuple[bool, str, bool]:
    tesseract_ok, tesseract_detail = check_tesseract(config_manager)
    if tesseract_ok:
        return True, tesseract_detail, False

    windows_ok, windows_detail = check_windows_ocr()
    if windows_ok:
        return True, f"Tesseract는 사용할 수 없지만 Windows 내장 OCR fallback 사용 가능 ({tesseract_detail})", True

    return False, f"Tesseract 실패: {tesseract_detail}\nWindows OCR 실패: {windows_detail}", False


def check_playwright_driver(check_browser: bool = False) -> tuple[bool, str]:
    try:
        from playwright._impl._driver import compute_driver_executable

        node_path, cli_path = compute_driver_executable()
        if not os.path.exists(node_path):
            return False, f"Playwright node driver가 없습니다: {node_path}"
        if not os.path.exists(cli_path):
            return False, f"Playwright CLI가 없습니다: {cli_path}"
        if check_browser:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                browser.close()
        return True, "Playwright driver 사용 가능"
    except Exception as exc:
        return False, str(exc)


def check_office_imports() -> tuple[bool, str]:
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401

        return True, "pywin32 COM import 사용 가능"
    except Exception as exc:
        return False, str(exc)


def check_office_apps(app_names: list[str]) -> tuple[bool, list[str]]:
    try:
        import pythoncom
        import win32com.client
    except Exception as exc:
        return False, [f"pywin32 import 실패: {exc}"]

    errors = []
    for app_name in app_names:
        pythoncom.CoInitialize()
        app = None
        try:
            app = win32com.client.DispatchEx(app_name)
        except Exception as exc:
            errors.append(f"{app_name}: {exc}")
        finally:
            try:
                if app:
                    app.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()
    return not errors, errors


def required_office_apps(config: BypassRunConfig) -> list[str]:
    apps = set()
    for task in config.tasks:
        src_ext = os.path.splitext(task.src.lower())[1]
        if src_ext in (".xlsx", ".xls", ".xlsm"):
            apps.add("Excel.Application")
        elif src_ext in (".pptx", ".ppt", ".pptm"):
            apps.add("PowerPoint.Application")
        elif src_ext in (".docx", ".doc", ".docm"):
            apps.add("Word.Application")
    return sorted(apps)


def check_github_updater_settings(config_manager) -> tuple[bool, str]:
    repo = str(config_manager.get("github_repo", "") or "").strip()
    mode = str(config_manager.get("auto_check_update", "on_start") or "on_start").strip()
    allowed_modes = {"on_start", "manual", "weekly"}

    if mode not in allowed_modes:
        return False, f"auto_check_update 값이 올바르지 않습니다: {mode}"
    if not repo:
        return True, f"GitHub 저장소 설정이 비어 있어 기본 저장소({DEFAULT_GITHUB_REPOSITORY_SLUG})로 업데이트를 확인합니다."
    if repo.count("/") != 1:
        return False, "GitHub 저장소는 owner/repository 형식이어야 합니다."

    owner, name = (part.strip() for part in repo.split("/", 1))
    if not owner or not name:
        return False, "GitHub 저장소 owner 또는 repository 이름이 비어 있습니다."
    return True, f"GitHub updater 설정 형식 정상: {owner}/{name}"


def check_run_plan(
    run_plan: RunPlan,
    config_manager,
    *,
    auto_email: bool = False,
    check_browser: bool = False,
    check_office: bool = True,
    isolated: bool = False,
    cancel_event: Event | None = None,
) -> PreflightReport:
    language = get_app_language(config_manager)
    report = PreflightReport(language=language)
    def localize(english: str, korean: str, polish: str | None = None) -> str:
        return choose(language, english, korean, polish)

    def detail_text(value: str) -> str:
        if language == "ko":
            return value
        replacements = {
            "설정된 Tesseract 경로가 존재하지 않습니다": "The configured Tesseract path does not exist",
            "Tesseract는 사용할 수 없지만 Windows 내장 OCR fallback 사용 가능": "Tesseract is unavailable, but Windows OCR can be used",
            "Tesseract 실패": "Tesseract failed",
            "Windows OCR 실패": "Windows OCR failed",
            "Playwright node driver가 없습니다": "Playwright node driver is missing",
            "Playwright CLI가 없습니다": "Playwright CLI is missing",
            "pywin32 import 실패": "pywin32 import failed",
            "auto_check_update 값이 올바르지 않습니다": "Invalid auto_check_update value",
            f"GitHub 저장소 설정이 비어 있어 기본 저장소({DEFAULT_GITHUB_REPOSITORY_SLUG})로 업데이트를 확인합니다.": "The GitHub repository is empty; the default repository will be used.",
            "GitHub 저장소는 owner/repository 형식이어야 합니다.": "The GitHub repository must use owner/repository format.",
            "GitHub 저장소 owner 또는 repository 이름이 비어 있습니다.": "The GitHub repository owner or name is empty.",
            "GitHub updater 설정 형식 정상": "GitHub updater setting is valid",
            "Windows 내장 OCR 사용 가능": "Windows OCR is available",
        }
        translated = value
        for korean, english in replacements.items():
            translated = translated.replace(korean, english)
        return translated

    def probe_failure(label: str, probe_result: ProbeResult) -> str:
        if probe_result.timed_out:
            return localize(
                f"{label} timed out after {probe_result.elapsed_seconds:.1f} seconds. Open Diagnostics for recovery guidance.",
                f"{label} 검사가 {probe_result.elapsed_seconds:.1f}초 후 시간 초과되었습니다. 진단 및 복구에서 해결 방법을 확인하세요.",
                f"Przekroczono limit czasu kontroli {label} ({probe_result.elapsed_seconds:.1f} s). Otwórz Diagnostykę, aby uzyskać wskazówki naprawcze.",
            )
        if probe_result.cancelled:
            return localize(f"{label} was cancelled.", f"{label} 검사가 취소되었습니다.", f"Kontrola {label} została anulowana.")
        return localize(
            f"{label} could not be checked: {probe_result.error}",
            f"{label} 검사 실패: {probe_result.error}",
            f"Nie udało się sprawdzić {label}: {probe_result.error}",
        )

    if TaskStep.OCR in run_plan.configs:
        if isolated:
            ocr_probe = run_probe(
                "ocr_engine",
                {"tesseract_path": config_manager.get("tesseract_path", "")},
                timeout_seconds=DEPENDENCY_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            ok = bool(ocr_probe.ok and ocr_probe.value.get("ok"))
            detail = (
                str(ocr_probe.value.get("detail", ""))
                if ocr_probe.ok
                else probe_failure(localize("OCR engine", "OCR 엔진", "silnika OCR"), ocr_probe)
            )
            using_fallback = bool(ocr_probe.ok and ocr_probe.value.get("using_fallback"))
        else:
            ok, detail, using_fallback = check_ocr_engines(config_manager)
        if not ok:
            report.add_blocker(localize("No OCR engine is available.", "사용 가능한 OCR 엔진이 없습니다.", "Brak dostępnego silnika OCR."), detail_text(detail), TaskStep.OCR)
        elif using_fallback:
            report.add_warning(localize("Windows OCR will be used instead of Tesseract.", "Tesseract 대신 Windows 내장 OCR로 진행합니다.", "Zamiast Tesseract zostanie użyty mechanizm OCR systemu Windows."), detail_text(detail), TaskStep.OCR)

    if TaskStep.EML in run_plan.configs:
        if isolated and check_browser:
            browser_probe = run_probe(
                "playwright_browser",
                timeout_seconds=DEPENDENCY_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            ok = bool(browser_probe.ok and browser_probe.value.get("ok"))
            detail = (
                str(browser_probe.value.get("detail", ""))
                if browser_probe.ok
                else probe_failure(localize("EML browser", "EML 브라우저", "przeglądarki EML"), browser_probe)
            )
        else:
            ok, detail = check_playwright_driver(check_browser=check_browser)
        if not ok:
            report.add_blocker(localize("The Playwright EML rendering driver is unavailable.", "Playwright EML 렌더링 드라이버를 사용할 수 없습니다.", "Sterownik renderowania EML Playwright jest niedostępny."), detail_text(detail), TaskStep.EML)
        custom_chromium = config_manager.get("offline_chromium_path", "")
        if custom_chromium and not os.path.exists(custom_chromium):
            report.add_warning(localize("The offline Chromium path does not exist.", "오프라인 Chromium 경로가 존재하지 않습니다.", "Ścieżka do Chromium w trybie offline nie istnieje."), custom_chromium, TaskStep.EML)

    bypass_config = run_plan.configs.get(TaskStep.BYPASS)
    if isinstance(bypass_config, BypassRunConfig):
        ok, detail = check_office_imports()
        if not ok:
            report.add_blocker(localize("The Office COM automation module (pywin32) is unavailable.", "Office COM 자동화 모듈(pywin32)을 사용할 수 없습니다.", "Moduł automatyzacji Office COM (pywin32) jest niedostępny."), detail_text(detail), TaskStep.BYPASS)
        apps = required_office_apps(bypass_config)
        if apps and check_office:
            if isolated:
                office_probe = run_probe(
                    "office_apps",
                    {"apps": apps},
                    timeout_seconds=OFFICE_TIMEOUT_SECONDS,
                    cancel_event=cancel_event,
                )
                office_ok = bool(office_probe.ok and office_probe.value.get("ok"))
                errors = (
                    list(office_probe.value.get("errors") or [])
                    if office_probe.ok
                    else [probe_failure(localize("Office automation", "Office 자동화", "automatyzacji Office"), office_probe)]
                )
            else:
                office_ok, errors = check_office_apps(apps)
            if not office_ok:
                report.add_blocker(localize("The required Microsoft Office COM application could not be started.", "필요한 Microsoft Office COM 앱을 실행할 수 없습니다.", "Nie udało się uruchomić wymaganej aplikacji Microsoft Office COM."), "\n".join(errors), TaskStep.BYPASS)
        elif apps:
            report.add_warning(
                localize("Office conversion depends on Excel, Word, or PowerPoint being installed on this computer.", "Office 파일 변환은 대상 PC의 Excel/Word/PowerPoint COM 설치 상태에 의존합니다.", "Konwersja plików Office wymaga zainstalowanego programu Excel, Word lub PowerPoint na tym komputerze."),
                ", ".join(apps),
                TaskStep.BYPASS,
            )
        if bypass_config.source_disposition == SourceDisposition.BACKUP:
            source_folders = sorted({os.path.dirname(task.src) for task in bypass_config.tasks})
            backup_folders = [os.path.join(folder, "Original Backup") for folder in source_folders]
            report.add_warning(
                localize(
                    "Convert Files will move source files to recoverable backup folders after verified conversion.",
                    "파일 변환은 출력 검증 후 원본을 복구 가능한 백업 폴더로 이동합니다.",
                    "Po zweryfikowanej konwersji pliki źródłowe zostaną przeniesione do folderów kopii zapasowej z możliwością odzyskania.",
                ),
                "\n".join(backup_folders),
                TaskStep.BYPASS,
            )

    if auto_email:
        missing = []
        for key, label in [
            ("smtp_server", localize("SMTP server", "SMTP 서버", "serwer SMTP")),
            ("sender_email", localize("Sender email", "발신자 이메일", "adres nadawcy")),
            ("receiver_email", localize("Recipient email", "수신자 이메일", "adres odbiorcy")),
        ]:
            if not str(config_manager.get(key, "")).strip():
                missing.append(label)
        if missing:
            report.add_warning(
                localize("Some automatic email settings are missing; the report may be saved locally instead.", "이메일 자동 발송 설정이 일부 누락되어 작업 완료 후 로컬 보고서로 대체될 수 있습니다.", "Brakuje części ustawień automatycznej poczty; raport może zostać zapisany lokalnie."),
                ", ".join(missing),
            )

    updater_ok, updater_detail = check_github_updater_settings(config_manager)
    if not updater_ok:
        report.add_warning(localize("Check the GitHub updater settings.", "GitHub updater 설정을 확인해 주세요.", "Sprawdź ustawienia aktualizacji z GitHub."), detail_text(updater_detail))

    return report

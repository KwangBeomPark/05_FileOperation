from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from threading import Event

from src.core.task_contracts import BypassRunConfig, RunPlan, SourceDisposition, TaskStep
from src.core.probe_runner import DEPENDENCY_TIMEOUT_SECONDS, OFFICE_TIMEOUT_SECONDS, run_probe
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
            return choose(selected_language, "No blocking preflight issues were found.", "사전 점검에서 차단 이슈가 발견되지 않았습니다.")
        lines = []
        for issue in selected:
            prefix = (
                choose(selected_language, "Blocker", "차단")
                if issue.level == IssueLevel.BLOCKER
                else choose(selected_language, "Warning", "경고")
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
        return True, "GitHub 저장소 설정이 비어 있어 기본 저장소(KwangBeomPark/05_FileOperation)로 업데이트를 확인합니다."
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
    t = lambda english, korean: choose(language, english, korean)

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
            "GitHub 저장소 설정이 비어 있어 기본 저장소(KwangBeomPark/05_FileOperation)로 업데이트를 확인합니다.": "The GitHub repository is empty; the default repository will be used.",
            "GitHub 저장소는 owner/repository 형식이어야 합니다.": "The GitHub repository must use owner/repository format.",
            "GitHub 저장소 owner 또는 repository 이름이 비어 있습니다.": "The GitHub repository owner or name is empty.",
            "GitHub updater 설정 형식 정상": "GitHub updater setting is valid",
            "Windows 내장 OCR 사용 가능": "Windows OCR is available",
        }
        translated = value
        for korean, english in replacements.items():
            translated = translated.replace(korean, english)
        return translated

    def probe_failure(label: str, result) -> str:
        if result.timed_out:
            return t(
                f"{label} timed out after {result.elapsed_seconds:.1f} seconds. Open Diagnostics for recovery guidance.",
                f"{label} 검사가 {result.elapsed_seconds:.1f}초 후 시간 초과되었습니다. 진단 및 복구에서 해결 방법을 확인하세요.",
            )
        if result.cancelled:
            return t(f"{label} was cancelled.", f"{label} 검사가 취소되었습니다.")
        return t(f"{label} could not be checked: {result.error}", f"{label} 검사 실패: {result.error}")

    if TaskStep.OCR in run_plan.configs:
        if isolated:
            result = run_probe(
                "ocr_engine",
                {"tesseract_path": config_manager.get("tesseract_path", "")},
                timeout_seconds=DEPENDENCY_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            ok = bool(result.ok and result.value.get("ok"))
            detail = str(result.value.get("detail", "")) if result.ok else probe_failure(t("OCR engine", "OCR 엔진"), result)
            using_fallback = bool(result.ok and result.value.get("using_fallback"))
        else:
            ok, detail, using_fallback = check_ocr_engines(config_manager)
        if not ok:
            report.add_blocker(t("No OCR engine is available.", "사용 가능한 OCR 엔진이 없습니다."), detail_text(detail), TaskStep.OCR)
        elif using_fallback:
            report.add_warning(t("Windows OCR will be used instead of Tesseract.", "Tesseract 대신 Windows 내장 OCR로 진행합니다."), detail_text(detail), TaskStep.OCR)

    if TaskStep.EML in run_plan.configs:
        if isolated and check_browser:
            result = run_probe(
                "playwright_browser",
                timeout_seconds=DEPENDENCY_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            ok = bool(result.ok and result.value.get("ok"))
            detail = str(result.value.get("detail", "")) if result.ok else probe_failure(t("EML browser", "EML 브라우저"), result)
        else:
            ok, detail = check_playwright_driver(check_browser=check_browser)
        if not ok:
            report.add_blocker(t("The Playwright EML rendering driver is unavailable.", "Playwright EML 렌더링 드라이버를 사용할 수 없습니다."), detail_text(detail), TaskStep.EML)
        custom_chromium = config_manager.get("offline_chromium_path", "")
        if custom_chromium and not os.path.exists(custom_chromium):
            report.add_warning(t("The offline Chromium path does not exist.", "오프라인 Chromium 경로가 존재하지 않습니다."), custom_chromium, TaskStep.EML)

    bypass_config = run_plan.configs.get(TaskStep.BYPASS)
    if isinstance(bypass_config, BypassRunConfig):
        ok, detail = check_office_imports()
        if not ok:
            report.add_blocker(t("The Office COM automation module (pywin32) is unavailable.", "Office COM 자동화 모듈(pywin32)을 사용할 수 없습니다."), detail_text(detail), TaskStep.BYPASS)
        apps = required_office_apps(bypass_config)
        if apps and check_office:
            if isolated:
                result = run_probe(
                    "office_apps",
                    {"apps": apps},
                    timeout_seconds=OFFICE_TIMEOUT_SECONDS,
                    cancel_event=cancel_event,
                )
                office_ok = bool(result.ok and result.value.get("ok"))
                errors = list(result.value.get("errors") or []) if result.ok else [probe_failure(t("Office automation", "Office 자동화"), result)]
            else:
                office_ok, errors = check_office_apps(apps)
            if not office_ok:
                report.add_blocker(t("The required Microsoft Office COM application could not be started.", "필요한 Microsoft Office COM 앱을 실행할 수 없습니다."), "\n".join(errors), TaskStep.BYPASS)
        elif apps:
            report.add_warning(
                t("Office conversion depends on Excel, Word, or PowerPoint being installed on this computer.", "Office 파일 변환은 대상 PC의 Excel/Word/PowerPoint COM 설치 상태에 의존합니다."),
                ", ".join(apps),
                TaskStep.BYPASS,
            )
        if bypass_config.source_disposition == SourceDisposition.BACKUP:
            source_folders = sorted({os.path.dirname(task.src) for task in bypass_config.tasks})
            backup_folders = [os.path.join(folder, "Original Backup") for folder in source_folders]
            report.add_warning(
                t(
                    "Convert Files will move source files to recoverable backup folders after verified conversion.",
                    "파일 변환은 출력 검증 후 원본을 복구 가능한 백업 폴더로 이동합니다.",
                ),
                "\n".join(backup_folders),
                TaskStep.BYPASS,
            )

    if auto_email:
        missing = []
        for key, label in [
            ("smtp_server", t("SMTP server", "SMTP 서버")),
            ("sender_email", t("Sender email", "발신자 이메일")),
            ("receiver_email", t("Recipient email", "수신자 이메일")),
        ]:
            if not str(config_manager.get(key, "")).strip():
                missing.append(label)
        if missing:
            report.add_warning(
                t("Some automatic email settings are missing; the report may be saved locally instead.", "이메일 자동 발송 설정이 일부 누락되어 작업 완료 후 로컬 보고서로 대체될 수 있습니다."),
                ", ".join(missing),
            )

    updater_ok, updater_detail = check_github_updater_settings(config_manager)
    if not updater_ok:
        report.add_warning(t("Check the GitHub updater settings.", "GitHub updater 설정을 확인해 주세요."), detail_text(updater_detail))

    return report

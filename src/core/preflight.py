from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from src.core.task_contracts import BypassRunConfig, RunPlan, TaskStep


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

    def format(self, include_warnings: bool = True) -> str:
        selected = self.blockers + (self.warnings if include_warnings else [])
        if not selected:
            return "사전 점검에서 차단 이슈가 발견되지 않았습니다."
        lines = []
        for issue in selected:
            prefix = "차단" if issue.level == IssueLevel.BLOCKER else "경고"
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
        return True, "GitHub 저장소 설정이 비어 있어 기본 저장소(KwangBeomPark/FileOps-Hub)로 업데이트를 확인합니다."
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
) -> PreflightReport:
    report = PreflightReport()

    if TaskStep.OCR in run_plan.configs:
        ok, detail, using_fallback = check_ocr_engines(config_manager)
        if not ok:
            report.add_blocker("사용 가능한 OCR 엔진이 없습니다.", detail, TaskStep.OCR)
        elif using_fallback:
            report.add_warning("Tesseract 대신 Windows 내장 OCR로 진행합니다.", detail, TaskStep.OCR)

    if TaskStep.EML in run_plan.configs:
        ok, detail = check_playwright_driver(check_browser=check_browser)
        if not ok:
            report.add_blocker("Playwright EML 렌더링 드라이버를 사용할 수 없습니다.", detail, TaskStep.EML)
        custom_chromium = config_manager.get("offline_chromium_path", "")
        if custom_chromium and not os.path.exists(custom_chromium):
            report.add_warning("오프라인 Chromium 경로가 존재하지 않습니다.", custom_chromium, TaskStep.EML)

    bypass_config = run_plan.configs.get(TaskStep.BYPASS)
    if isinstance(bypass_config, BypassRunConfig):
        ok, detail = check_office_imports()
        if not ok:
            report.add_blocker("Office COM 자동화 모듈(pywin32)을 사용할 수 없습니다.", detail, TaskStep.BYPASS)
        apps = required_office_apps(bypass_config)
        if apps and check_office:
            office_ok, errors = check_office_apps(apps)
            if not office_ok:
                report.add_blocker("필요한 Microsoft Office COM 앱을 실행할 수 없습니다.", "\n".join(errors), TaskStep.BYPASS)
        elif apps:
            report.add_warning(
                "Office 파일 변환은 대상 PC의 Excel/Word/PowerPoint COM 설치 상태에 의존합니다.",
                ", ".join(apps),
                TaskStep.BYPASS,
            )

    if auto_email:
        missing = []
        for key, label in [
            ("smtp_server", "SMTP 서버"),
            ("sender_email", "발신자 이메일"),
            ("receiver_email", "수신자 이메일"),
        ]:
            if not str(config_manager.get(key, "")).strip():
                missing.append(label)
        if missing:
            report.add_warning(
                "이메일 자동 발송 설정이 일부 누락되어 작업 완료 후 로컬 보고서로 대체될 수 있습니다.",
                ", ".join(missing),
            )

    updater_ok, updater_detail = check_github_updater_settings(config_manager)
    if not updater_ok:
        report.add_warning("GitHub updater 설정을 확인해 주세요.", updater_detail)

    return report

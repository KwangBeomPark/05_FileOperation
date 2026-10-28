"""Result-report delivery for the integrated task tab (email, webhook, local fallback).

Everything here is Qt-free so it can run on a background thread; messages are
reported through a ``log`` callback that the caller marshals to the UI.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from src.core.email_sender import send_email
from src.core.notifier import build_webhook_payload, send_webhook
from src.ui.i18n import replace_phrases
from src.utils.logger import get_logger

logger = get_logger()

DEFAULT_SUBJECT_KO = "통합 작업 완료 결과 보고서"
DEFAULT_SUBJECT_EN = "Task Result Report"

_RUNTIME_ERROR_REPLACEMENTS = {
    "필수 이메일 발송 설정 항목이 누락되었습니다": "Required email settings are missing",
    "수신자 이메일 주소가 비어있습니다": "The recipient email address is empty",
    "SMTP 인증에 실패했습니다": "SMTP authentication failed",
    "이메일 주소 또는 비밀번호(앱 비밀번호)를 확인하세요": "Check the email address and app password",
    "이메일 전송 중 에러가 발생했습니다": "An error occurred while sending email",
}


def localized_text(language: str, english: str, korean: str, polish: str) -> str:
    return {"ko": korean, "pl": polish}.get(language, english)


def localize_runtime_error(value, language: str) -> str:
    """Translate the Korean messages returned by ``send_email`` for non-Korean UIs."""
    text = str(value)
    if language == "ko":
        return text
    return replace_phrases(text, _RUNTIME_ERROR_REPLACEMENTS)


@dataclass(frozen=True)
class ReportNotification:
    """Snapshot of the notification settings, taken on the UI thread."""

    language: str
    smtp_server: str
    smtp_port: int
    sender_email: str
    sender_password: str
    receiver_email: str
    subject: str
    body_header: str
    webhook_url: str
    webhook_type: str
    has_saved_report: bool

    @classmethod
    def from_config(cls, config_manager, language: str, *, has_saved_report: bool) -> ReportNotification:
        get = config_manager.get
        subject = get("mail_subject", DEFAULT_SUBJECT_KO).strip()
        if language != "ko" and subject == DEFAULT_SUBJECT_KO:
            subject = DEFAULT_SUBJECT_EN
        smtp_port_raw = get("smtp_port", "")
        try:
            smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
        except ValueError:
            smtp_port = 587
        return cls(
            language=language,
            smtp_server=get("smtp_server", "").strip(),
            smtp_port=smtp_port,
            sender_email=get("sender_email", "").strip(),
            sender_password=get("sender_password", ""),
            receiver_email=get("receiver_email", "").strip(),
            subject=subject,
            body_header=get("mail_body_header", "").strip(),
            webhook_url=str(get("webhook_url", "") or "").strip(),
            webhook_type=str(get("webhook_type", "generic") or "generic"),
            has_saved_report=bool(has_saved_report),
        )

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_server and self.sender_email and self.receiver_email)

    def email_body(self, report_body: str) -> str:
        full_body = ""
        if self.body_header:
            full_body += f"{self.body_header}\n\n"
            full_body += "=" * 60 + "\n\n"
        full_body += report_body
        return full_body


def save_fallback_report(content: str, *, log: Callable[[str], None], text) -> str | None:
    """Atomically save the report under the user logs folder; returns the path or None."""
    from src.app_identity import user_data_dir
    log_dir = str(user_data_dir() / 'logs')

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    filename = f"task_report_{timestamp}.txt"

    temp_path = os.path.join(log_dir, f"{filename}.tmp")
    final_path = os.path.join(log_dir, filename)

    try:
        os.makedirs(log_dir, exist_ok=True)
        # 원자적 파일 쓰기(Atomic Write) 보장
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_path, final_path)

        msg = text("💾 Result report saved locally", "💾 결과 보고서를 로컬에 저장했습니다", "💾 Raport zapisano lokalnie") + f": {final_path}"
        log(msg)
        logger.info(msg)
        return final_path
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to save fallback report atomically: {e}")
        log(text("✗ Could not save the result report", "✗ 결과 보고서를 저장하지 못했습니다", "✗ Nie można zapisać raportu") + f": {e}")
        return None


def deliver_report(notification: ReportNotification, report_body: str, log: Callable[[str], None]) -> None:
    """Send the result report by email (+ webhook), saving a local copy when email cannot be sent.

    Blocking (SMTP/HTTP); call it from a background thread when invoked from the UI.
    """
    language = notification.language

    def text(english, korean, polish):
        return localized_text(language, english, korean, polish)

    if not notification.email_configured:
        log(text("✗ Email was skipped because SMTP settings are incomplete.", "✗ SMTP 설정이 누락되어 이메일 발송을 건너뜁니다.", "✗ Pominięto e-mail z powodu niepełnych ustawień SMTP."))
        if not notification.has_saved_report:
            save_fallback_report(report_body, log=log, text=text)
        return

    full_body = notification.email_body(report_body)
    receiver_email = notification.receiver_email
    log(text(f"✉ Sending the result to [{receiver_email}]...", f"✉ [{receiver_email}]에 결과를 발송합니다...", f"✉ Wysyłanie wyniku do [{receiver_email}]..."))

    ok, send_msg = send_email(
        smtp_server=notification.smtp_server,
        smtp_port=notification.smtp_port,
        sender_email=notification.sender_email,
        sender_password=notification.sender_password,
        receiver_emails=receiver_email,
        subject=notification.subject,
        body_text=full_body,
    )

    if ok:
        log(text("✓ Email sent successfully.", "✓ 이메일을 전송했습니다.", "✓ E-mail wysłany pomyślnie."))
    else:
        log(text("✗ Email failed", "✗ 이메일 전송 실패", "✗ Nie udało się wysłać e-maila") + f": {localize_runtime_error(send_msg, language)}")
        if not notification.has_saved_report:
            save_fallback_report(full_body, log=log, text=text)

    # Multi-channel webhook notification
    if notification.webhook_url:
        log(text("✉ Sending Webhook notification...", "✉ 웹훅 알림을 전송합니다...", "✉ Wysyłanie powiadomienia Webhook..."))
        payload = build_webhook_payload(notification.webhook_type, notification.subject, report_body, success=True)
        wb_ok, wb_msg = send_webhook(notification.webhook_url, payload)
        if wb_ok:
            log(text("✓ Webhook notification sent successfully.", "✓ 웹훅 알림이 성공적으로 전송되었습니다.", "✓ Powiadomienie Webhook wysłane pomyślnie."))
        else:
            log(text("✗ Webhook notification failed", "✗ 웹훅 알림 전송 실패", "✗ Nie udało się wysłać powiadomienia Webhook") + f": {wb_msg}")

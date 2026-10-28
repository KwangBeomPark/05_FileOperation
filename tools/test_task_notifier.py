import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from src.core.task_notifier import (
    ReportNotification,
    deliver_report,
    localize_runtime_error,
    save_fallback_report,
)
from src.ui.notification_worker import NotificationWorker


class FakeConfig:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


SMTP_CONFIG = {
    "smtp_server": "smtp.example.com",
    "smtp_port": "465",
    "sender_email": "sender@example.com",
    "sender_password": "secret",
    "receiver_email": "ops@example.com",
    "mail_body_header": "Header",
}


def make_notification(values=None, language="en", has_saved_report=False):
    return ReportNotification.from_config(FakeConfig(values), language, has_saved_report=has_saved_report)


def english(english_text, _korean, _polish):
    return english_text


class ReportNotificationConfigTests(unittest.TestCase):
    def test_defaults_and_invalid_port(self):
        notification = make_notification({"smtp_port": "abc"})
        self.assertEqual(notification.smtp_port, 587)
        self.assertEqual(notification.subject, "Task Result Report")
        self.assertEqual(notification.webhook_type, "generic")
        self.assertFalse(notification.email_configured)

    def test_korean_keeps_default_subject_and_builds_body_header(self):
        notification = make_notification(SMTP_CONFIG, language="ko")
        self.assertEqual(notification.subject, "통합 작업 완료 결과 보고서")
        self.assertEqual(notification.smtp_port, 465)
        self.assertTrue(notification.email_configured)
        self.assertEqual(notification.email_body("Body"), "Header\n\n" + "=" * 60 + "\n\nBody")

    def test_runtime_error_is_translated_except_for_korean(self):
        message = "SMTP 인증에 실패했습니다."
        self.assertEqual(localize_runtime_error(message, "en"), "SMTP authentication failed.")
        self.assertEqual(localize_runtime_error(message, "ko"), message)


class DeliverReportTests(unittest.TestCase):
    @patch("src.core.task_notifier.send_webhook")
    @patch("src.core.task_notifier.send_email", return_value=(True, "ok"))
    def test_email_and_webhook_success(self, send_email, send_webhook):
        send_webhook.return_value = (True, "HTTP 200")
        notification = make_notification({**SMTP_CONFIG, "webhook_url": "https://hooks.example.com/x", "webhook_type": "slack"})
        logs = []

        deliver_report(notification, "Body", logs.append)

        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["smtp_port"], 465)
        self.assertEqual(kwargs["receiver_emails"], "ops@example.com")
        self.assertTrue(kwargs["body_text"].endswith("Body"))
        url, payload = send_webhook.call_args.args
        self.assertEqual(url, "https://hooks.example.com/x")
        self.assertIn("Body", payload["text"])
        self.assertTrue(any("Email sent successfully" in line for line in logs))
        self.assertTrue(any("Webhook notification sent successfully" in line for line in logs))

    @patch("src.core.task_notifier.save_fallback_report")
    @patch("src.core.task_notifier.send_webhook")
    @patch("src.core.task_notifier.send_email", return_value=(False, "SMTP 인증에 실패했습니다."))
    def test_email_failure_saves_fallback_and_still_sends_webhook(self, _send_email, send_webhook, fallback):
        send_webhook.return_value = (False, "Webhook HTTP error: 500")
        notification = make_notification({**SMTP_CONFIG, "webhook_url": "https://hooks.example.com/x"})
        logs = []

        deliver_report(notification, "Body", logs.append)

        self.assertIn("Header", fallback.call_args.args[0])
        self.assertTrue(any("Email failed: SMTP authentication failed." in line for line in logs))
        self.assertTrue(any("Webhook notification failed: Webhook HTTP error: 500" in line for line in logs))

    @patch("src.core.task_notifier.save_fallback_report")
    @patch("src.core.task_notifier.send_email", return_value=(False, "down"))
    def test_email_failure_skips_fallback_when_run_report_exists(self, _send_email, fallback):
        deliver_report(make_notification(SMTP_CONFIG, has_saved_report=True), "Body", lambda _line: None)
        fallback.assert_not_called()

    @patch("src.core.task_notifier.save_fallback_report")
    @patch("src.core.task_notifier.send_webhook")
    @patch("src.core.task_notifier.send_email")
    def test_incomplete_smtp_skips_email_and_webhook(self, send_email, send_webhook, fallback):
        logs = []
        deliver_report(make_notification({"webhook_url": "https://hooks.example.com/x"}), "Body", logs.append)

        send_email.assert_not_called()
        send_webhook.assert_not_called()
        self.assertEqual(fallback.call_args.args[0], "Body")
        self.assertIn("SMTP settings are incomplete", logs[0])


class FallbackReportTests(unittest.TestCase):
    def test_fallback_report_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logs = []
            with patch("src.app_identity.user_data_dir", return_value=Path(temp_dir)):
                path = save_fallback_report("내용", log=logs.append, text=english)

            self.assertIsNotNone(path)
            self.assertEqual(Path(path).read_text(encoding="utf-8"), "내용")
            self.assertEqual([p.name for p in (Path(temp_dir) / "logs").iterdir()], [Path(path).name])
            self.assertIn("saved locally", logs[0])

    def test_fallback_report_failure_is_logged(self):
        logs = []
        with patch("src.core.task_notifier.os.makedirs", side_effect=PermissionError("denied")):
            self.assertIsNone(save_fallback_report("report", log=logs.append, text=english))
        self.assertIn("Could not save the result report: denied", logs[0])


class NotificationWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @patch("src.core.task_notifier.send_email")
    def test_delivery_runs_off_the_ui_thread_and_logs_via_signal(self, send_email):
        ui_thread = threading.get_ident()
        send_threads = []

        def fake_send(**_kwargs):
            send_threads.append(threading.get_ident())
            return True, "ok"

        send_email.side_effect = fake_send
        worker = NotificationWorker(make_notification(SMTP_CONFIG), "Body")
        logs = []
        worker.log_signal.connect(logs.append)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait()
        QCoreApplication.processEvents()

        self.assertEqual(len(send_threads), 1)
        self.assertNotEqual(send_threads[0], ui_thread)
        self.assertTrue(any("Email sent successfully" in line for line in logs))


if __name__ == "__main__":
    unittest.main()

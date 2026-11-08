"""Synthetic SMTP boundary tests; no messages or network connections are made."""

import logging
import smtplib
import unittest
from unittest.mock import Mock, patch

SMTP_TEST_LOGGER = logging.getLogger("fileops.tests.smtp")
SMTP_TEST_LOGGER.propagate = False
with patch("src.utils.logger.get_logger", return_value=SMTP_TEST_LOGGER):
    from src.core.email_sender import send_email


class EmailSenderBoundaryTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch("src.core.email_sender.logger", SMTP_TEST_LOGGER)
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def send(self):
        return send_email("smtp.example.invalid", 465, "sender@example.invalid",
                          "synthetic-password", ["receiver@example.invalid"], "test", "body")

    def test_cleanup_failure_preserves_success_without_logging_exception_details(self):
        server = Mock()
        server.quit.side_effect = RuntimeError("sensitive-cleanup-detail")
        with patch("src.core.email_sender.smtplib.SMTP_SSL", return_value=server), self.assertLogs(SMTP_TEST_LOGGER, level="WARNING") as logs:
            result = self.send()
        self.assertTrue(result[0])
        self.assertEqual([record.getMessage() for record in logs.records], ["SMTP connection cleanup failed"])
        server.sendmail.assert_called_once()

    def test_authentication_failure_retains_message_despite_cleanup_failure(self):
        server = Mock()
        server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"rejected")
        server.quit.side_effect = OSError("cleanup")
        with patch("src.core.email_sender.smtplib.SMTP_SSL", return_value=server):
            result = self.send()
        self.assertFalse(result[0])
        self.assertIn("SMTP 인증", result[1])
        server.sendmail.assert_not_called()

    def test_provider_failure_remains_a_failed_result(self):
        with patch("src.core.email_sender.smtplib.SMTP_SSL", side_effect=RuntimeError("provider failed")):
            result = self.send()
        self.assertFalse(result[0])
        self.assertIn("provider failed", result[1])

    def test_starttls_failure_does_not_attempt_login_or_delivery(self):
        server = Mock()
        server.starttls.side_effect = smtplib.SMTPException("TLS unavailable")
        with patch("src.core.email_sender.smtplib.SMTP", return_value=server):
            result = send_email("smtp.example.invalid", 587, "sender@example.invalid", "fixture",
                                ["receiver@example.invalid"], "test", "body")
        self.assertFalse(result[0])
        self.assertIn("TLS unavailable", result[1])
        server.login.assert_not_called()
        server.sendmail.assert_not_called()
        server.quit.assert_called_once()

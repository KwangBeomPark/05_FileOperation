"""Automated unit & regression tests for Phase 4 Generalization features.

Covers:
- Workflow preset manager (sanitization, export, load, category-based apply)
- Multi-channel notification dispatcher (Slack, Teams, Discord, Generic Webhook, Email integration)
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.error

from src.core.notifier import (
    build_webhook_payload,
    dispatch_notifications,
    send_webhook,
)
from src.core.preset_manager import (
    apply_workflow_preset,
    export_workflow_preset,
    is_sensitive_key,
    load_workflow_preset,
    sanitize_config_for_export,
)


class TestPresetManagerPhase4(unittest.TestCase):
    """Test preset sanitization, export, load, and application."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sensitive_keys_detection(self):
        self.assertTrue(is_sensitive_key("github_token"))
        self.assertTrue(is_sensitive_key("sender_password"))
        self.assertTrue(is_sensitive_key("api_key"))
        self.assertTrue(is_sensitive_key("slack_secret_token"))
        self.assertFalse(is_sensitive_key("sync_groups"))
        self.assertFalse(is_sensitive_key("ocr_rule_mode"))

    def test_sanitize_and_export_excludes_secrets_and_transient_data(self):
        raw_config = {
            "github_token": "ghp_super_secret_token",
            "sender_password": "my_email_password",
            "task_schedule_last_started_at": "2026-09-26T12:00:00",
            "recent_files": ["C:/test.pdf"],
            "sync_groups": [{"name": "Production", "folders": ["C:/Src", "C:/Dst"]}],
            "ocr_rule_mode": "invoice_number",
            "task_schedule_time": "18:30",
        }

        sanitized = sanitize_config_for_export(raw_config)
        self.assertNotIn("github_token", sanitized)
        self.assertNotIn("sender_password", sanitized)
        self.assertNotIn("task_schedule_last_started_at", sanitized)
        self.assertNotIn("recent_files", sanitized)
        self.assertIn("sync_groups", sanitized)
        self.assertIn("ocr_rule_mode", sanitized)

        export_file = os.path.join(self.temp_dir, "test_preset.json")
        envelope = export_workflow_preset(raw_config, export_file, preset_name="Test Preset")

        self.assertTrue(os.path.exists(export_file))
        self.assertEqual(envelope["preset_format"], "fileops.workflow.v1")
        self.assertEqual(envelope["name"], "Test Preset")

        # Verify on-disk file has no secrets
        with open(export_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        self.assertNotIn("github_token", disk_data["settings"])
        self.assertNotIn("sender_password", disk_data["settings"])

    def test_load_and_apply_preset(self):
        export_file = os.path.join(self.temp_dir, "sample.json")
        payload = {
            "preset_format": "fileops.workflow.v1",
            "name": "Invoice Workflow",
            "settings": {
                "ocr_rule_mode": "invoice_number",
                "ocr_rename_template": "INV_{match}",
                "sync_move_to_deleted": True,
                "injected_token": "should_be_stripped",
            },
        }
        with open(export_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        loaded = load_workflow_preset(export_file)
        self.assertEqual(loaded["ocr_rule_mode"], "invoice_number")
        self.assertNotIn("injected_token", loaded)

        mock_config = Mock()
        mock_config.update = Mock()

        applied = apply_workflow_preset(mock_config, loaded, categories=["ocr"])
        self.assertEqual(applied, 2)  # ocr_rule_mode, ocr_rename_template
        mock_config.update.assert_called_once()
        updated_dict = mock_config.update.call_args[0][0]
        self.assertIn("ocr_rule_mode", updated_dict)
        self.assertNotIn("sync_move_to_deleted", updated_dict)


class TestNotifierPhase4(unittest.TestCase):
    """Test webhook payloads, webhook delivery, and multi-channel dispatch."""

    def test_build_webhook_payloads(self):
        # Slack
        slack_p = build_webhook_payload("slack", "Daily Report", "Body text", success=True)
        self.assertIn("text", slack_p)
        self.assertIn("Daily Report", slack_p["text"])
        self.assertIn("✅", slack_p["text"])

        # Teams
        teams_p = build_webhook_payload("teams", "Daily Report", "Body text", success=False)
        self.assertIn("text", teams_p)
        self.assertIn("❌", teams_p["text"])

        # Discord
        discord_p = build_webhook_payload("discord", "Daily Report", "Body text", success=True)
        self.assertIn("content", discord_p)

        # Generic
        gen_p = build_webhook_payload("generic", "Daily Report", "Body text", success=True)
        self.assertEqual(gen_p["event"], "fileops_task_result")
        self.assertTrue(gen_p["success"])

    def test_send_webhook_invalid_url(self):
        ok, msg = send_webhook("invalid_url", {"test": 1})
        self.assertFalse(ok)
        self.assertIn("Invalid or missing Webhook URL", msg)

    @patch("urllib.request.urlopen")
    def test_send_webhook_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        ok, msg = send_webhook("https://hooks.slack.com/services/xxx", {"text": "hello"})
        self.assertTrue(ok)
        self.assertIn("HTTP 200", msg)

    @patch("urllib.request.urlopen")
    def test_send_webhook_http_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://example.com/webhook",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=None,
        )

        ok, msg = send_webhook("https://example.com/webhook", {"text": "hello"})
        self.assertFalse(ok)
        self.assertIn("400", msg)

    @patch("src.core.notifier.send_email")
    @patch("src.core.notifier.send_webhook")
    def test_dispatch_notifications(self, mock_webhook, mock_email):
        mock_email.return_value = (True, "Email sent")
        mock_webhook.return_value = (True, "Webhook sent")

        config = {
            "task_auto_email": True,
            "smtp_server": "smtp.example.com",
            "sender_email": "sender@example.com",
            "receiver_email": "rc@example.com",
            "webhook_url": "https://hooks.slack.com/services/xxx",
            "webhook_type": "slack",
        }

        results = dispatch_notifications(config, "Subject", "Body", success=True)
        self.assertIn("email", results)
        self.assertIn("webhook", results)
        self.assertTrue(results["email"][0])
        self.assertTrue(results["webhook"][0])
        mock_email.assert_called_once()
        mock_webhook.assert_called_once()


if __name__ == "__main__":
    unittest.main()

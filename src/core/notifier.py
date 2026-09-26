"""Multi-channel notification dispatcher supporting Email and Webhooks (Slack, Teams, Discord, Generic)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from src.core.email_sender import send_email

logger = logging.getLogger(__name__)


def build_webhook_payload(
    webhook_type: str,
    subject: str,
    body: str,
    success: bool = True,
) -> dict[str, Any]:
    """Format notification payload for specific messaging platforms."""
    wb_type = str(webhook_type or "generic").strip().lower()

    if wb_type == "slack":
        status_icon = "✅" if success else "❌"
        return {
            "text": f"{status_icon} *{subject}*\n```{body}```",
        }

    if wb_type == "teams":
        status_icon = "✅" if success else "❌"
        return {
            "text": f"### {status_icon} {subject}\n\n{body}",
        }

    if wb_type == "discord":
        status_icon = "✅" if success else "❌"
        truncated_body = body[:1900] if len(body) > 1900 else body
        return {
            "content": f"{status_icon} **{subject}**\n```{truncated_body}```",
        }

    # Generic Webhook
    return {
        "event": "fileops_task_result",
        "subject": subject,
        "body": body,
        "success": bool(success),
        "timestamp": datetime.now().isoformat(),
    }


def send_webhook(
    url: str,
    payload: dict[str, Any],
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """Deliver a JSON payload to a Webhook URL synchronously with bounded timeout."""
    target_url = str(url or "").strip()
    if not target_url or not (target_url.startswith("http://") or target_url.startswith("https://")):
        return False, "Invalid or missing Webhook URL (must begin with http:// or https://)"

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "FileOps-Hub/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=max(1.0, float(timeout))) as response:
            status_code = getattr(response, "status", 200)
            return True, f"Webhook delivered successfully (HTTP {status_code})"
    except urllib.error.HTTPError as e:
        msg = f"Webhook HTTP error: {e.code} {e.reason}"
        logger.warning(msg)
        return False, msg
    except urllib.error.URLError as e:
        msg = f"Webhook URL network error: {e.reason}"
        logger.warning(msg)
        return False, msg
    except Exception as e:
        msg = f"Webhook delivery error: {e}"
        logger.exception("Unexpected error during webhook delivery")
        return False, msg


def dispatch_notifications(
    config: dict[str, Any],
    subject: str,
    body_text: str,
    success: bool = True,
) -> dict[str, tuple[bool, str]]:
    """Dispatch execution reports to all configured notification channels."""
    outcomes: dict[str, tuple[bool, str]] = {}

    # 1. Email notification
    if config.get("task_auto_email", True):
        smtp_server = config.get("smtp_server", "")
        smtp_port_raw = config.get("smtp_port", 587)
        sender_email = config.get("sender_email", "")
        sender_password = config.get("sender_password", "")
        receiver_email = config.get("receiver_email", "")
        body_header = config.get("mail_body_header", "").strip()

        if smtp_server and sender_email and receiver_email:
            try:
                smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
            except ValueError:
                smtp_port = 587

            full_body = ""
            if body_header:
                full_body += f"{body_header}\n\n" + "=" * 60 + "\n\n"
            full_body += body_text

            ok, msg = send_email(
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                sender_email=sender_email,
                sender_password=sender_password,
                receiver_emails=receiver_email,
                subject=subject,
                body_text=full_body,
            )
            outcomes["email"] = (ok, msg)

    # 2. Webhook notification
    webhook_url = str(config.get("webhook_url", "") or "").strip()
    if webhook_url:
        webhook_type = str(config.get("webhook_type", "generic") or "generic")
        payload = build_webhook_payload(webhook_type, subject, body_text, success=success)
        timeout = float(config.get("webhook_timeout", 5.0) or 5.0)
        ok, msg = send_webhook(webhook_url, payload, timeout=timeout)
        outcomes["webhook"] = (ok, msg)

    return outcomes

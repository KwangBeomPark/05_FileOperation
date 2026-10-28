"""Shared, localized summary for manual and master CollectSync executions."""

from src.core.collect_sync import (
    ACTION_COPY,
    ACTION_ERROR,
    ACTION_REPLACE,
    ACTION_TARGET_NEWER,
    ACTION_UNCHANGED,
)
from src.core.task_contracts import StepResult, StepStatus, TaskStep
from src.ui.i18n import tr


def collect_step_result(report, language, error_code=""):
    total = len(report.actions)
    success = total - report.count(ACTION_ERROR)
    status = (
        StepStatus.CANCELLED
        if report.cancelled
        else (StepStatus.PARTIAL if success else StepStatus.FAILED)
        if error_code or report.count(ACTION_ERROR)
        else StepStatus.COMPLETED
    )
    details = [
        tr(
            "collect_summary",
            language,
            copy=report.count(ACTION_COPY),
            replace=report.count(ACTION_REPLACE),
            unchanged=report.count(ACTION_UNCHANGED),
            newer=report.count(ACTION_TARGET_NEWER),
            error=report.count(ACTION_ERROR),
        )
    ]
    error = tr(error_code, language) if error_code else ""
    if error:
        details.append(error)
    for action in report.actions:
        message = (
            tr("collect_error_" + (action.message_code or "io"), language)
            if action.kind == ACTION_ERROR
            else tr("collect_newer_message", language)
            if action.kind == ACTION_TARGET_NEWER
            else action.message
        )
        details.append(
            f"{tr('collect_' + action.kind, language)}: {action.source} → {action.target_name} {message}"
        )
    return StepResult(TaskStep.COLLECT_SYNC, status, details, success, total, error)

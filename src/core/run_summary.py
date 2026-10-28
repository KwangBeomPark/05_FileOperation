"""Read-only change previews. No converters, output creation or credential access."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field

from src.core.sync_manager import SyncManager
from src.core.task_contracts import (
    BypassRunConfig, EmlRunConfig, OcrRunConfig, PdfRunConfig, RunPlan,
    SourceDisposition, SyncRunConfig, TaskStep,
)


DISPLAY_LIMIT = 200
OBSERVATION_LIMIT = 100_000
SUMMARY_TIMEOUT_SECONDS = 30.0


@dataclass
class ChangeEntry:
    step: str
    group: str
    action: str
    source: str
    target: str
    count: int | None = 1


@dataclass
class RunChangeSummary:
    entries: list[ChangeEntry] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    total_entries: int = 0
    fingerprint: str = ""
    pending_counts: list[str] = field(default_factory=list)

    @property
    def requires_acknowledgement(self) -> bool:
        return bool(self.risks)


class _SummaryBuilder:
    def __init__(self):
        self.summary = RunChangeSummary()
        self.observations = {}
        self.actions = []

    def observe(self, path: str, *, required=False):
        path = os.path.abspath(path)
        try:
            info = os.stat(path)
        except FileNotFoundError:
            if required:
                raise
            # Also observe an existing parent: target creation must not go unnoticed.
            parent = os.path.dirname(path)
            if parent != path:
                self.observe(parent)
            self.observations[path] = None
        else:
            self.observations[path] = (
                info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_mode,
            )
        if len(self.observations) > OBSERVATION_LIMIT:
            raise ValueError("Preview exceeds 100000 observed paths; use a smaller scope.")

    def add(self, step, group, action, source, target, count=1):
        entry = ChangeEntry(step.value, group, action, source, target, count)
        self.summary.total_entries += 1
        if len(self.summary.entries) < DISPLAY_LIMIT:
            self.summary.entries.append(entry)
        self.summary.counts[action] = self.summary.counts.get(action, 0) + (count or 0)
        if count is None and action not in self.summary.pending_counts:
            self.summary.pending_counts.append(action)
        self.actions.append(json.dumps(asdict(entry), ensure_ascii=False, sort_keys=True))

    def risk(self, code):
        if code not in self.summary.risks:
            self.summary.risks.append(code)

    def note(self, code):
        if code not in self.summary.notes:
            self.summary.notes.append(code)

    def sync(self, config: SyncRunConfig):
        for group in config.sync_groups:
            for folder in group.folders:
                if not os.path.isdir(folder):
                    raise FileNotFoundError(folder)
            manager = SyncManager(**{
                key: value for key, value in group.to_legacy_dict().items() if key != "name"
            }, observe_scan=True)
            actions = manager.analyze_sync()
            if manager.scan_errors:
                raise OSError(str(manager.scan_errors[0]))
            self.observations.update(manager.scan_observations)
            if not group.move_to_deleted:
                # A later overlapping group may discover more deletions at execution.
                self.risk("delete_policy")
            for action in actions:
                source = os.path.join(action["source_folder"], action["filename"])
                target = os.path.join(action["target_folder"], action["filename"])
                if action["action"] == "복사":
                    kind = "copy"
                    self.observe(target)
                elif action["action"] == "to_be_deleted이동":
                    kind = "archive" if group.move_to_deleted else "delete"
                    self.risk("move_sources" if group.move_to_deleted else "delete_policy")
                elif action["action"] == "충돌 보존 백업":
                    kind = "conflict_backup"
                    target = os.path.join(action["source_folder"], manager.archive_folder_name)
                    self.risk("conflicts")
                else:
                    raise ValueError(f"Unsupported synchronization action: {action['action']}")
                self.add(TaskStep.SYNC, group.name, kind, source, target if kind != "delete" else "")
        if len(config.sync_groups) > 1:
            self.note("sync_estimate")

    def eml(self, config: EmlRunConfig):
        for task in config.tasks:
            self.observe(task.source_folder, required=True)
            self.observe(task.target_folder)
            with os.scandir(task.source_folder) as files:
                paths = sorted(item.path for item in files if item.name.lower().endswith(".eml") and item.is_file())
            for path in paths:
                self.observe(path, required=True)
                self.add(TaskStep.EML, task.name, "convert", path, task.target_folder)
        self.note("dynamic_outputs")

    def pdf(self, config: PdfRunConfig):
        self.observe(config.output_folder)
        for path in config.pdf_paths:
            self.observe(path, required=True)
            self.add(TaskStep.PDF, "", "convert", path, config.output_folder)
        self.note("dynamic_outputs")

    def ocr(self, config: OcrRunConfig, chained: bool):
        action = "ocr" if config.rule_mode == "full_text_txt" else "rename"
        save_text = config.export_txt or config.rule_mode == "full_text_txt"
        if chained:
            self.add(TaskStep.OCR, "", action, "", "", None)
            self.note("chained_ocr")
            if save_text:
                self.add(TaskStep.OCR, "", "text_output", "", "", None)
                self.risk("ocr_text_policy")
        else:
            for path in config.image_paths:
                self.observe(path, required=True)
                self.add(TaskStep.OCR, "", action, path, os.path.dirname(path))
                if save_text:
                    output = os.path.splitext(path)[0] + ".txt"
                    self.observe(output)
                    if os.path.exists(output):
                        self.add(TaskStep.OCR, "", "overwrite", path, output)
                        self.risk("overwrite_text")
                    else:
                        self.add(TaskStep.OCR, "", "text_output", path, output)
        if action == "rename":
            self.note("ocr_names")

    def bypass(self, config: BypassRunConfig):
        for task in config.tasks:
            self.observe(task.src, required=True)
            self.observe(task.tgt)
            self.add(TaskStep.BYPASS, "", "convert", task.src, task.tgt)
            if os.path.exists(task.tgt):
                self.risk("target_exists")
            if task.generate_pdf_html and task.src.lower().endswith(".pdf"):
                html_target = os.path.splitext(task.tgt)[0] + ".html"
                if os.path.normcase(html_target) != os.path.normcase(task.tgt):
                    self.observe(html_target)
                    self.add(TaskStep.BYPASS, "", "extra_output", task.src, html_target)
                    if os.path.exists(html_target):
                        self.risk("target_exists")
            if task.source_disposition == SourceDisposition.BACKUP:
                self.add(TaskStep.BYPASS, "", "archive", task.src, os.path.join(os.path.dirname(task.src), "Original Backup"))
                self.risk("move_sources")
            elif task.source_disposition == SourceDisposition.REPLACE:
                self.add(TaskStep.BYPASS, "", "replace", task.src, "")
                self.risk("replace_policy")


def build_run_summary(plan: RunPlan) -> RunChangeSummary:
    """Inspect inputs without writing anything; counts are operations/input files.

    Output names determined by OCR/rendering and downstream group effects are not
    promised. Metadata fingerprints detect common changes while the dialog is open;
    they are not a filesystem transaction or a content-hash integrity guarantee.
    """
    builder = _SummaryBuilder()
    earlier = set()
    for step in plan.active_steps:
        config = plan.get(step)
        if isinstance(config, SyncRunConfig):
            builder.sync(config)
        elif isinstance(config, EmlRunConfig):
            builder.eml(config)
        elif isinstance(config, PdfRunConfig):
            builder.pdf(config)
        elif isinstance(config, OcrRunConfig):
            builder.ocr(config, plan.chain_outputs and bool(earlier & {TaskStep.EML, TaskStep.PDF}))
        elif isinstance(config, BypassRunConfig):
            builder.bypass(config)
        else:
            raise ValueError(f"Unsupported summary step: {step}")
        earlier.add(step)
    if len(builder.observations) > OBSERVATION_LIMIT:
        raise ValueError("Preview exceeds 100000 observed paths; use a smaller scope.")
    if len(plan.active_steps) > 1:
        builder.note("step_estimates")
    payload = {"plan": asdict(plan), "files": sorted(builder.observations.items()), "actions": sorted(builder.actions)}
    builder.summary.fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return builder.summary

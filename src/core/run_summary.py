"""Read-only change previews. No converters, output creation or credential access."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field

from src.core.sync_manager import SyncManager, sync_path_observation
from src.core.task_contracts import (
    BypassRunConfig,
    CollectRunConfig,
    EmlRunConfig,
    OcrRunConfig,
    PdfRunConfig,
    RunPlan,
    SourceDisposition,
    SyncRunConfig,
    TaskStep,
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
    filename: str = ""
    reason: str = ""


@dataclass
class RunChangeSummary:
    entries: list[ChangeEntry] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    total_entries: int = 0
    fingerprint: str = ""
    pending_counts: list[str] = field(default_factory=list)
    approved_manifest: list[dict] = field(default_factory=list)
    sync_fingerprints: dict[str, str] = field(default_factory=dict)
    write_fingerprint: str = ""

    @property
    def requires_acknowledgement(self) -> bool:
        return bool(self.risks)


class _SummaryBuilder:
    def __init__(self):
        self.summary = RunChangeSummary()
        self.observations = {}
        self.actions = []
        self.approved_manifest = []

    def observe(self, path: str, *, required=False, for_sync=False):
        path = os.path.abspath(path)
        try:
            info = os.stat(path)
        except FileNotFoundError:
            if required:
                raise
            # Record the parent identity as well as the missing target itself.
            parent = os.path.dirname(path)
            if parent != path:
                self.observe(parent, for_sync=for_sync)
            self.observations[path] = None
        else:
            self.observations[path] = sync_path_observation(info) if for_sync else (
                info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_mode,
            )
        if len(self.observations) > OBSERVATION_LIMIT:
            raise ValueError("Preview exceeds 100000 observed paths; use a smaller scope.")

    def add(self, step, group, action, source, target, count=1, filename="", reason=""):
        entry = ChangeEntry(step.value, group, action, source, target, count, filename=filename, reason=reason)
        self.summary.total_entries += 1
        if len(self.summary.entries) < DISPLAY_LIMIT:
            self.summary.entries.append(entry)
        self.summary.counts[action] = self.summary.counts.get(action, 0) + (count or 0)
        if count is None and action not in self.summary.pending_counts:
            self.summary.pending_counts.append(action)
        self.actions.append(json.dumps(asdict(entry), ensure_ascii=False, sort_keys=True))
        manifest_entry = {
            "step": step.value,
            "group": group,
            "action": action,
            "source": os.path.normcase(os.path.abspath(source)) if source else "",
            "target": os.path.normcase(os.path.abspath(target)) if target else "",
            "filename": os.path.normcase(filename) if filename else "",
        }
        if step == TaskStep.SYNC and action in ("copy", "archive", "conflict_backup") and source:
            snapshot = self.observations.get(os.path.abspath(source))
            if snapshot is not None:
                manifest_entry["source_snapshot"] = snapshot
        self.approved_manifest.append(manifest_entry)

    def risk(self, code):
        if code not in self.summary.risks:
            self.summary.risks.append(code)

    def note(self, code):
        if code not in self.summary.notes:
            self.summary.notes.append(code)

    def sync(self, config: SyncRunConfig, *, item_key: str = ""):
        if item_key and len(config.sync_groups) != 1:
            raise ValueError("An ordered sync row must refer to exactly one group.")
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
            if item_key:
                group_builder = _SummaryBuilder()
                group_builder.sync_group(group.name, manager, actions)
                snapshot = _finish_sync_group(group_builder, group.to_legacy_dict())
                self.summary.sync_fingerprints[item_key] = snapshot.write_fingerprint
                self.observations.update(group_builder.observations)
                self.actions.extend(group_builder.actions)
                self.approved_manifest.extend(snapshot.approved_manifest)
                self.summary.entries.extend(snapshot.entries[:DISPLAY_LIMIT - len(self.summary.entries)])
                self.summary.total_entries += snapshot.total_entries
                for action, count in snapshot.counts.items():
                    self.summary.counts[action] = self.summary.counts.get(action, 0) + count
                for risk in snapshot.risks:
                    self.risk(risk)
            else:
                self.sync_group(group.name, manager, actions)
        if len(config.sync_groups) > 1:
            self.note("sync_estimate")

    def sync_group(self, group_name, manager, actions):
        """Build approved actions from the same scan used to render the preview."""
        self.observations.update(manager.scan_observations)
        for action in actions:
            source = os.path.join(action["source_folder"], action["filename"])
            target = os.path.join(action["target_folder"], action["filename"])
            if action["action"] in ("날짜 보류", "보류"):
                if action["action"] == "보류":
                    source = action["source_folder"]
                self.add(TaskStep.SYNC, group_name, "held", source, target, filename=action.get("filename", ""), reason=action.get("reason") or action.get("status", ""))
                continue
            if action["action"] == "날짜 동기화":
                if not action["existing"]:
                    self.observe(target, for_sync=True)
                    self.add(TaskStep.SYNC, group_name, "copy", source, target, filename=action["filename"])
                archive_mode = manager.date_archive_mode
                for old in action["old"]:
                    old_path = os.path.join(action["target_folder"], old["filename"])
                    if archive_mode == "trash":
                        self.add(TaskStep.SYNC, group_name, "trash", old_path, "", filename=old["filename"])
                    else:
                        archive = os.path.join(action["target_folder"], manager.archive_folder_name, os.path.dirname(old["filename"]))
                        self.add(TaskStep.SYNC, group_name, "archive", old_path, archive, filename=old["filename"])
                    self.risk("move_sources")
                continue
            if action["action"] == "복사":
                kind = "copy"
                self.observe(target, for_sync=True)
            elif action["action"] == "to_be_deleted이동":
                kind = "archive"
                target = os.path.join(action["source_folder"], manager.archive_folder_name, os.path.dirname(action["filename"]))
                self.risk("move_sources")
            elif action["action"] == "충돌 보존 백업":
                kind = "conflict_backup"
                target = os.path.join(action["source_folder"], manager.archive_folder_name)
                self.risk("conflicts")
            else:
                raise ValueError(f"Unsupported synchronization action: {action['action']}")
            self.add(TaskStep.SYNC, group_name, kind, source, target if kind != "delete" else "", filename=action.get("filename", ""))

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


def summarize_scanned_sync_group(group: dict, manager: SyncManager, actions: list, *, track_writes=False) -> RunChangeSummary:
    """Bind a manual preview to its group settings, operations and scan observations."""
    builder = _SummaryBuilder()
    builder.sync_group(group["name"], manager, actions)
    return _finish_sync_group(builder, group) if track_writes else _finish_summary(builder, group)


def _finish_sync_group(builder, settings):
    """Distinguish changed writes from unrelated changes in the observed folders."""
    summary = _finish_summary(builder, settings)
    observations = {os.path.normcase(path): info for path, info in builder.observations.items()}
    writes = []
    for entry in summary.approved_manifest:
        if entry["action"] == "held":
            continue
        # Manifest paths are already normalized by add(); keep both lookup sides explicit.
        target = os.path.normcase(entry["target"])
        parent = os.path.dirname(target)
        while parent and observations.get(parent) is None:
            next_parent = os.path.dirname(parent)
            if next_parent == parent:
                break
            parent = next_parent
        source = os.path.normcase(entry["source"])
        writes.append(json.dumps((entry, observations.get(source), observations.get(target),
                                  parent, observations.get(parent)), sort_keys=True))
    payload = json.dumps((settings, sorted(writes)), ensure_ascii=False, sort_keys=True).encode()
    summary.write_fingerprint = hashlib.sha256(payload).hexdigest()
    return summary


def _finish_summary(builder, plan_data):
    if len(builder.observations) > OBSERVATION_LIMIT:
        raise ValueError("Preview exceeds 100000 observed paths; use a smaller scope.")
    payload = {"plan": plan_data, "files": sorted(builder.observations.items()), "actions": sorted(builder.actions),
               "sync_fingerprints": builder.summary.sync_fingerprints}
    builder.summary.fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    builder.summary.approved_manifest = list(builder.approved_manifest)
    return builder.summary


def build_run_summary(plan: RunPlan) -> RunChangeSummary:
    """Inspect inputs without writing anything; counts are operations/input files.

    Output names determined by OCR/rendering and downstream group effects are not
    promised. Metadata fingerprints detect common changes while the dialog is open;
    they are not a filesystem transaction or a content-hash integrity guarantee.
    """
    builder = _SummaryBuilder()
    earlier = set()
    if plan.stop_on_failure and plan.items:
        # Preserve interleaved rows (e.g. copy → convert → copy) in the actual queue.
        work = [(item.key, item.step, item.config) for item in plan.items if not item.error and item.config is not None]
    else:
        work = [("", step, plan.get(step)) for step in plan.active_steps]
    for key, step, config in work:
        if isinstance(config, SyncRunConfig):
            builder.sync(config, item_key=key if not plan.is_scheduled else "")
        elif isinstance(config, CollectRunConfig):
            for group in config.groups:
                for source in group.sources:
                    builder.add(TaskStep.COLLECT_SYNC, group.name, "copy", source, group.target, None)
        elif isinstance(config, EmlRunConfig):
            builder.eml(config)
        elif isinstance(config, PdfRunConfig):
            builder.pdf(config)
        elif isinstance(config, OcrRunConfig):
            builder.ocr(config, plan.chain_outputs and bool(earlier & {TaskStep.EML, TaskStep.PDF}))
        elif isinstance(config, BypassRunConfig):
            builder.bypass(config)
        else:
            # Preserve the public invalid-plan value error for unsupported configurations.
            raise ValueError(f"Unsupported summary step: {step}")  # noqa: TRY004
        earlier.add(step)
    if len(plan.active_steps) > 1:
        builder.note("step_estimates")
    return _finish_summary(builder, asdict(plan))

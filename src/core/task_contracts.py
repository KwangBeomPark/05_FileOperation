from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStep(str, Enum):
    SYNC = "sync"
    EML = "eml"
    PDF = "pdf"
    OCR = "ocr"
    BYPASS = "bypass"


class StepStatus(str, Enum):
    PENDING = "대기 중"
    RUNNING = "진행 중"
    COMPLETED = "완료"
    PARTIAL = "일부 실패"
    FAILED = "실패"
    CANCELLED = "취소됨"
    SKIPPED = "건너뜀"


class TaskValidationError(ValueError):
    def __init__(
        self,
        user_message: str,
        detail: str | None = None,
        *,
        message_key: str | None = None,
        values: dict[str, Any] | None = None,
    ):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail or user_message
        self.message_key = message_key
        self.values = values or {}


class DependencyError(RuntimeError):
    def __init__(self, user_message: str, detail: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail or user_message


@dataclass(frozen=True)
class SyncGroupConfig:
    name: str
    folders: list[str]
    move_to_deleted: bool = True

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "folders": list(self.folders),
            "move_to_deleted": self.move_to_deleted,
        }


@dataclass(frozen=True)
class SyncRunConfig:
    sync_groups: list[SyncGroupConfig]

    def to_legacy_dict(self) -> dict[str, Any]:
        return {"sync_groups": [group.to_legacy_dict() for group in self.sync_groups]}


@dataclass(frozen=True)
class EmlTaskConfig:
    name: str
    source_folder: str
    target_folder: str

    def to_legacy_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "source_folder": self.source_folder,
            "target_folder": self.target_folder,
        }


@dataclass(frozen=True)
class EmlRunConfig:
    tasks: list[EmlTaskConfig]
    width: int = 1024

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "tasks": [task.to_legacy_dict() for task in self.tasks],
            "width": self.width,
        }


@dataclass(frozen=True)
class PdfRunConfig:
    pdf_paths: list[str]
    output_folder: str

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "pdf_paths": list(self.pdf_paths),
            "output_folder": self.output_folder,
        }


@dataclass(frozen=True)
class OcrRunConfig:
    image_paths: list[str]

    def to_legacy_dict(self) -> dict[str, Any]:
        return {"image_paths": list(self.image_paths)}


@dataclass(frozen=True)
class BypassFileConfig:
    src: str
    tgt: str
    ext: str
    preserve_meta: bool
    delete_original: bool

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "src": self.src,
            "tgt": self.tgt,
            "ext": self.ext,
            "preserve_meta": self.preserve_meta,
            "delete_original": self.delete_original,
        }


@dataclass(frozen=True)
class BypassRunConfig:
    tasks: list[BypassFileConfig]
    delete_original: bool

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "tasks": [task.to_legacy_dict() for task in self.tasks],
            "delete_original": self.delete_original,
        }


RunConfig = SyncRunConfig | EmlRunConfig | PdfRunConfig | OcrRunConfig | BypassRunConfig


@dataclass(frozen=True)
class RunPlan:
    configs: dict[TaskStep, RunConfig] = field(default_factory=dict)

    @property
    def active_steps(self) -> list[TaskStep]:
        order = [TaskStep.SYNC, TaskStep.EML, TaskStep.PDF, TaskStep.OCR, TaskStep.BYPASS]
        return [step for step in order if step in self.configs]

    def get(self, step: TaskStep) -> RunConfig | None:
        return self.configs.get(step)

    def is_empty(self) -> bool:
        return not self.configs


@dataclass
class StepResult:
    step: TaskStep
    status: StepStatus = StepStatus.PENDING
    details: list[str] = field(default_factory=list)
    success_count: int = 0
    total_count: int = 0
    error_message: str = ""


@dataclass
class RunReport:
    results: dict[TaskStep, StepResult]
    report_body: str
    message: str
    overall_success: bool
    cancelled: bool = False

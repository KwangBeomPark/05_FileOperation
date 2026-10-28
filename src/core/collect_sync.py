"""Collect files whose names match keywords from several source folders into one flat target folder.

Rules:
- Sources are only read. Target files are never deleted.
- One source file maps to one target file. The mapping is stored by source path, so the
  same source is never confused with another source that has the same file name.
- An unchanged file (same size and SHA-256) is skipped.
- A changed source replaces its target file. The previous target file moves to the
  ``이전 버전`` folder as ``<name> (01).<ext>``, ``(02)``, and so on.
- If the target copy is newer than its source, it is kept and reported instead.
- When two different sources share a file name, the second and later ones get the source
  folder name in brackets, for example ``보고서 [B].xlsx``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from src.utils.atomic_write import atomic_write_json
from src.utils.logger import get_logger

logger = get_logger()

ARCHIVE_DIR_NAME = "이전 버전"
STATE_VERSION = 1
LOCK_FILE_PREFIX = "~$"
MTIME_TOLERANCE_SECONDS = 1.0
HASH_CHUNK_BYTES = 1024 * 1024

ACTION_COPY = "copy"
ACTION_REPLACE = "replace"
ACTION_UNCHANGED = "unchanged"
ACTION_TARGET_NEWER = "target_newer"
ACTION_ERROR = "error"


class CollectConfigError(ValueError):
    """A collect group cannot be run safely as configured."""

    def __init__(self, message: str, code: str = "config", path: str = ""):
        super().__init__(message)
        self.code = code
        self.path = path


class CollectStateError(RuntimeError):
    """Stop on mapping failure, retaining any already completed actions for reporting."""

    def __init__(self, message: str, report=None):
        super().__init__(message)
        self.report = report


class CollectRunError(RuntimeError):
    """An unexpected failure stops execution without discarding committed results."""

    def __init__(self, message: str, report):
        super().__init__(message)
        self.report = report


class CollectRecoveryRequired(CollectStateError):
    """A readable pending journal requires an explicit recovery decision."""


@dataclass(frozen=True)
class CollectGroup:
    name: str
    sources: tuple[str, ...]
    keywords: tuple[str, ...]
    target: str
    include_subfolders: bool = False


@dataclass
class CollectAction:
    kind: str
    source: str = ""
    target_name: str = ""
    archived_name: str = ""
    message: str = ""
    message_code: str = ""


@dataclass
class CollectReport:
    actions: list[CollectAction] = field(default_factory=list)
    cancelled: bool = False

    def count(self, kind: str) -> int:
        return sum(1 for action in self.actions if action.kind == kind)


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_within(path: str, base: str) -> bool:
    try:
        return os.path.commonpath([path, base]) == base
    except ValueError:  # Different drives cannot contain each other.
        return False


def normalize_keywords(keywords) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        text = str(keyword).strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return tuple(result)


def _is_link(path) -> bool:
    """Treat Windows junctions as links without excluding ordinary cloud files."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False  # New destination files need not exist yet.
    # Unlike islink/isjunction predicates, an access error must not mean "safe".
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) == getattr(
        stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003
    )


def cyclic_group_indexes(groups) -> set[int]:
    """Find feedback loops without disk access; ordinary acyclic chains remain valid."""
    edges = {index: set() for index in range(len(groups))}
    for index, writer in enumerate(groups):
        if not writer.target.strip():
            continue
        outputs = (
            _norm(writer.target.strip()),
            _norm(Path(writer.target.strip()) / ARCHIVE_DIR_NAME),
        )
        for other, reader in enumerate(groups):
            if other == index:
                continue  # Same-group overlap has its own configuration error.
            for source in reader.sources:
                if not source.strip():
                    continue
                source_key = _norm(source.strip())
                if any(
                    output == source_key
                    or (reader.include_subfolders and _is_within(output, source_key))
                    for output in outputs
                ):
                    edges[index].add(other)
    cyclic = set()
    for start, destinations in edges.items():
        pending, visited = list(destinations), set()
        while pending:
            current = pending.pop()
            if current == start:
                cyclic.add(start)
                break
            if current not in visited:
                visited.add(current)
                pending.extend(edges[current])
    return cyclic


def has_link_ancestor(path) -> bool:
    """Use the same no-link policy for execution and recovery, including parents."""
    absolute = Path(os.path.abspath(path))
    return any(_is_link(item) for item in (absolute, *absolute.parents))


def valid_target_name(name) -> bool:
    """Check a Windows filename component before persisting a pending copy."""
    if not isinstance(name, str) or not name or name.endswith((".", " ")):
        return False
    if any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name):
        return False
    if name.split(".", 1)[0].rstrip(" ").upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
        *(f"COM{number}" for number in "¹²³"),
        *(f"LPT{number}" for number in "¹²³"),
    }:
        return False
    try:
        return len(name.encode("utf-16-le")) <= 510
    except UnicodeError:
        return False


def validate_group(group: CollectGroup) -> CollectGroup:
    """Return a cleaned copy of the group, or raise CollectConfigError."""
    sources = tuple(
        str(source).strip() for source in group.sources if str(source).strip()
    )
    keywords = normalize_keywords(group.keywords)
    target = str(group.target).strip()
    if not sources:
        raise CollectConfigError(
            f"[{group.name}] 소스 폴더를 1개 이상 등록해야 합니다.", "sources"
        )
    if not keywords:
        raise CollectConfigError(
            f"[{group.name}] 파일명 키워드를 1개 이상 입력해야 합니다.", "keywords"
        )
    if not target or not os.path.isdir(target):
        raise CollectConfigError(
            f"[{group.name}] 타겟 폴더가 없습니다: {target}", "target", target
        )
    for source in sources:
        if not os.path.isdir(source):
            raise CollectConfigError(
                f"[{group.name}] 소스 폴더가 없습니다: {source}", "source", source
            )
    for path in (*sources, target):
        if has_link_ancestor(path):
            raise CollectConfigError(
                f"Link folder is not followed: {path}", "link", path
            )

    normalized_sources = [_norm(source) for source in sources]
    if len(set(normalized_sources)) != len(normalized_sources):
        raise CollectConfigError(
            f"[{group.name}] 같은 소스 폴더가 중복 등록되어 있습니다.", "duplicate"
        )
    for left, right in combinations(normalized_sources, 2):
        if _is_within(left, right) or _is_within(right, left):
            raise CollectConfigError(
                f"[{group.name}] 소스 폴더끼리 포함 관계입니다. 겹치지 않게 등록해 주세요.",
                "overlap",
            )
    target_norm = _norm(target)
    for source in normalized_sources:
        if _is_within(source, target_norm) or _is_within(target_norm, source):
            raise CollectConfigError(
                f"[{group.name}] 타겟 폴더와 소스 폴더가 같거나 포함 관계입니다.",
                "overlap",
            )

    return CollectGroup(
        name=group.name,
        sources=sources,
        keywords=keywords,
        target=target,
        include_subfolders=bool(group.include_subfolders),
    )


def _matches_keywords(filename: str, keywords: tuple[str, ...]) -> bool:
    folded = filename.casefold()
    return any(keyword.casefold() in folded for keyword in keywords)


def _source_folder_label(folder: str) -> str:
    path = Path(folder)
    label = path.name or path.drive.rstrip("\\/").split("\\")[-1].rstrip(":")
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", label).strip(" .") or "source"


def find_candidates(
    group: CollectGroup, should_cancel=None, errors=None
) -> list[tuple[str, str, str]]:
    """Return (source file path, source folder path, source folder label) for matching files."""
    found: list[tuple[str, str, str]] = []
    for source_root in group.sources:
        label = _source_folder_label(source_root)
        pending = [source_root]
        while pending:
            if should_cancel and should_cancel():
                return found
            folder = pending.pop()
            try:
                if _is_link(folder):
                    continue
                with os.scandir(folder) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name.casefold())
            except OSError as exc:
                if folder == source_root or errors is None:
                    raise
                logger.warning("Collect subfolder unavailable: %s (%s)", folder, exc)
                errors.append(
                    CollectAction(
                        ACTION_ERROR, source=folder, message=str(exc), message_code="io"
                    )
                )
                continue
            for entry in entries:
                if should_cancel and should_cancel():
                    return found
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if group.include_subfolders and not os.path.isjunction(
                            entry.path
                        ):
                            pending.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError as exc:
                    if errors is None:
                        raise
                    logger.warning(
                        "Collect entry unavailable: %s (%s)", entry.path, exc
                    )
                    errors.append(
                        CollectAction(
                            ACTION_ERROR,
                            source=entry.path,
                            message=str(exc),
                            message_code="io",
                        )
                    )
                    continue
                if entry.name.startswith(LOCK_FILE_PREFIX):
                    continue
                if _matches_keywords(entry.name, group.keywords):
                    found.append((entry.path, source_root, label))
    return found


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_content(source: Path, target: Path) -> bool:
    if source.stat().st_size != target.stat().st_size:
        return False
    return sha256_of(source) == sha256_of(target)


def unique_target_name(filename: str, folder_label: str, used: set[str]) -> str:
    """Keep the file name if it is free, otherwise add the source folder label in brackets."""
    if filename.casefold() not in used:
        return filename
    stem, ext = os.path.splitext(filename)
    candidate = f"{stem} [{folder_label}]{ext}"
    number = 2
    while candidate.casefold() in used:
        candidate = f"{stem} [{folder_label}-{number}]{ext}"
        number += 1
    return candidate


def next_archive_path(archive_dir: Path, target_name: str) -> Path:
    """Return the next free ``<stem> (NN)<ext>`` path inside the archive folder."""
    stem, ext = os.path.splitext(target_name)
    pattern = re.compile(
        rf"^{re.escape(stem)} \((\d+)\){re.escape(ext)}$", re.IGNORECASE
    )
    highest = 0
    if archive_dir.is_dir():
        for entry in archive_dir.iterdir():
            match = pattern.match(entry.name)
            if match:
                highest = max(highest, int(match.group(1)))
    number = highest + 1
    while True:
        candidate = archive_dir / f"{stem} ({number:02d}){ext}"
        if not valid_target_name(candidate.name):
            raise CollectConfigError(
                "Archive filename exceeds the safe name limit.", "name", str(candidate)
            )
        if not candidate.exists():
            return candidate
        number += 1


def _temp_path(target: Path) -> Path:
    return target.with_name(f".collect-tmp-{uuid.uuid4().hex}")


def _remove_temp(temp: Path) -> None:
    """Remove our own copy2 temporary file without masking the original error."""
    try:
        if temp.exists():
            os.chmod(temp, stat.S_IWRITE | stat.S_IREAD)
            temp.unlink()
    except OSError:
        logger.exception("Cannot remove collect temporary file: %s", temp)


def _copy_new(source: Path, target: Path) -> None:
    temp = _temp_path(target)
    try:
        shutil.copy2(source, temp)
        # Never overwrite a user file which appeared after the directory scan.
        if os.name == "nt":
            os.rename(temp, target)
        else:
            os.link(temp, target)
    finally:
        _remove_temp(temp)


def _move_exclusive(source: Path, target: Path) -> None:
    """Move one file without replacing a concurrently created destination."""
    if os.name == "nt":
        os.rename(source, target)
    else:
        os.link(source, target)
        source.unlink()


def _replace_with_archive(source: Path, target: Path, archived: Path) -> Path:
    """Copy the new file first, then move the old target aside, then move the copy in place."""
    temp = _temp_path(target)
    try:
        shutil.copy2(source, temp)
        archived.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(100):
            try:
                _move_exclusive(target, archived)
                break
            except FileExistsError:
                archived = next_archive_path(archived.parent, target.name)
        else:
            raise FileExistsError(f"Archive names keep changing: {archived.parent}")
        try:
            _move_exclusive(temp, target)
        except OSError as install_error:
            # Put the old version back so the target is never left missing.
            # Refuse to overwrite any file which appeared during this operation.
            try:
                _move_exclusive(archived, target)
            except OSError as rollback_error:
                raise OSError(
                    f"Replacement failed ({install_error}); previous copy preserved "
                    f"at {archived}; restore refused ({rollback_error})"
                ) from install_error
            raise
        return archived
    finally:
        _remove_temp(temp)


class CollectState:
    """Stores which source file each target file came from, per target folder."""

    def __init__(self, path: Path, targets: dict[str, dict[str, str]] | None = None):
        self.path = Path(path)
        self.targets: dict[str, dict[str, str]] = targets or {}
        self.pending: dict[str, str] = {}

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        allow_pending: bool = False,
        allow_invalid_pending_name: bool = False,
    ) -> CollectState:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            targets = data["targets"]
            if not isinstance(targets, dict):
                raise TypeError("targets must be an object")
            if data.get("version") != STATE_VERSION:
                raise ValueError("Unsupported collect state version")
            pending = data.get("pending", {})
            if not isinstance(pending, dict):
                raise TypeError("Invalid pending copy")
            if pending and (
                set(pending) != {"target", "source", "name"}
                or not all(
                    isinstance(value, str) and value for value in pending.values()
                )
                or not os.path.isabs(pending["target"])
                or not os.path.isabs(pending["source"])
                or (
                    not allow_invalid_pending_name
                    and not valid_target_name(pending["name"])
                )
            ):
                raise ValueError("Unsafe pending copy paths")
            if pending and not allow_pending:
                raise CollectRecoveryRequired(
                    "An incomplete copy needs mapping recovery; automatic retry is blocked"
                )
            for key, mapping in targets.items():
                if not isinstance(key, str) or not isinstance(mapping, dict):
                    raise TypeError("Invalid target mapping")
                names = set()
                for source, name in mapping.items():
                    if (
                        not isinstance(source, str)
                        or not isinstance(name, str)
                        or not name
                        or name in (".", "..")
                        or "/" in name
                        or "\\" in name
                        or ":" in name
                        or name.casefold() in names
                    ):
                        raise ValueError(
                            "Unsafe or duplicate target file name in state"
                        )
                    names.add(name.casefold())
            if pending:
                owned = targets.get(pending["target"], {})
                if pending["source"] in owned or pending["name"].casefold() in {
                    name.casefold() for name in owned.values()
                }:
                    raise ValueError("Pending copy conflicts with committed ownership")
        except FileNotFoundError:
            return cls(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CollectStateError(
                f"수집 동기화 상태 파일을 읽을 수 없어 실행을 중단했습니다: {path} ({exc})"
            ) from exc
        state = cls(path, {str(key): dict(value) for key, value in targets.items()})
        state.pending = dict(pending)
        return state

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                self.path,
                {
                    "version": STATE_VERSION,
                    "targets": self.targets,
                    "pending": self.pending,
                },
                indent=2,
                ensure_ascii=True,
            )
        except (OSError, ValueError) as exc:
            raise CollectStateError(
                f"Cannot save collect state: {self.path} ({exc})"
            ) from exc

    def mapping_for(self, target_key: str) -> dict[str, str]:
        return dict(self.targets.get(target_key, {}))

    def record(self, target_key: str, source_key: str, target_name: str) -> None:
        self.targets.setdefault(target_key, {})[source_key] = target_name


def _save_progress(state: CollectState, report: CollectReport) -> None:
    """Propagate a state error with the already completed file results intact."""
    try:
        state.save()
    except CollectStateError as exc:
        report.actions.append(
            CollectAction(
                ACTION_ERROR,
                source=str(state.path),
                message=str(exc),
                message_code="state",
            )
        )
        exc.report = report
        raise


def run_collect_group(
    group: CollectGroup,
    state: CollectState,
    dry_run: bool = False,
    progress_callback=None,
    should_cancel=None,
) -> CollectReport:
    """Run one collect group. With dry_run=True nothing is written, and the state is not changed."""
    report = CollectReport()
    try:
        return _run_collect_group(
            group, state, report, dry_run, progress_callback, should_cancel
        )
    except (CollectStateError, CollectConfigError, CollectRunError):
        raise
    except Exception as exc:
        if isinstance(exc, OSError) and not report.actions:
            raise  # A group preflight/scan failure must not block healthy groups.
        report.actions.append(
            CollectAction(
                ACTION_ERROR, source=group.name, message=str(exc), message_code="io"
            )
        )
        raise CollectRunError(str(exc), report) from exc


def _run_collect_group(group, state, report, dry_run, progress_callback, should_cancel):
    """Accumulate results in caller-owned storage before any callback or disk write."""
    group = validate_group(group)
    target_dir = Path(group.target)
    target_key = _norm(target_dir)
    archive_dir = target_dir / ARCHIVE_DIR_NAME
    mapping = state.mapping_for(target_key)

    used = {
        ARCHIVE_DIR_NAME.casefold(),
        *(name.casefold() for name in mapping.values()),
    }
    used.update(entry.name.casefold() for entry in target_dir.iterdir())

    # A name for a new source never matches an existing target file, so a new source is never
    # compared with a file it did not create.
    planned: list[tuple[str, str, str]] = []
    if progress_callback:
        progress_callback(0, 0, group.name)
    try:
        candidates = find_candidates(group, should_cancel, report.actions)
    except OSError as exc:
        # Scanning has not applied any files. Keep its errors but allow other groups.
        report.actions.append(
            CollectAction(
                ACTION_ERROR,
                source=str(getattr(exc, "filename", "") or group.name),
                message=str(exc),
                message_code="io",
            )
        )
        return report
    for source_path, _source_root, label in candidates:
        source_key = _norm(source_path)
        if source_key in mapping:
            target_name = mapping[source_key]
        else:
            target_name = unique_target_name(os.path.basename(source_path), label, used)
            used.add(target_name.casefold())
        planned.append((source_key, source_path, target_name))

    for index, (source_key, source_path, target_name) in enumerate(planned):
        if should_cancel and should_cancel():
            report.cancelled = True
            break
        source = Path(source_path)
        target = target_dir / target_name
        if not valid_target_name(target_name):
            report.actions.append(
                CollectAction(
                    ACTION_ERROR,
                    source_path,
                    target_name,
                    message="Target filename is invalid or exceeds 255 UTF-16 units.",
                    message_code="name",
                )
            )
            continue
        new_target = source_key not in mapping
        if not dry_run and new_target:
            # Reserve the stable name before touching files. A failed state write
            # must not leave an untracked copy which would be duplicated on retry.
            state.pending = {
                "target": target_key,
                "source": source_key,
                "name": target_name,
            }
            _save_progress(state, report)
        try:
            action = _apply_one(
                source, target, archive_dir, dry_run, new_target=new_target
            )
        except (OSError, CollectConfigError) as exc:
            logger.error("Collect sync failed for %s: %s", source_path, exc)
            report.actions.append(
                CollectAction(
                    ACTION_ERROR,
                    source_path,
                    target_name,
                    message=str(exc),
                    message_code=getattr(exc, "code", "io"),
                )
            )
            if not dry_run and new_target:
                # Only clear a reservation when no copy was committed, or an
                # exclusive creation explicitly refused an unrelated target.
                uncertain = not isinstance(exc, (FileExistsError, CollectConfigError))
                if uncertain:
                    try:
                        target.lstat()
                    except FileNotFoundError:
                        uncertain = False
                    except OSError:
                        logger.exception(
                            "Cannot determine failed copy outcome: %s", target
                        )
                if uncertain:
                    raise CollectStateError(
                        "Copy outcome is uncertain; mapping recovery required", report
                    ) from exc
                state.pending = {}
                _save_progress(state, report)
        except Exception as exc:
            report.actions.append(
                CollectAction(
                    ACTION_ERROR,
                    source_path,
                    target_name,
                    message=str(exc),
                    message_code="io",
                )
            )
            raise CollectRunError(str(exc), report) from exc
        else:
            action.target_name = target_name
            report.actions.append(action)
            if not dry_run and new_target:
                state.record(target_key, source_key, target_name)
                state.pending = {}
                _save_progress(state, report)
        if progress_callback:
            progress_callback(index + 1, len(planned), f"[{group.name}] {source_path}")

    if should_cancel and should_cancel():
        report.cancelled = True

    if not dry_run:
        _save_progress(state, report)
    return report


def _apply_one(
    source: Path,
    target: Path,
    archive_dir: Path,
    dry_run: bool,
    new_target: bool = False,
) -> CollectAction:
    source_text = str(source)
    for path in (source, target, archive_dir):
        if has_link_ancestor(path):
            raise CollectConfigError(
                f"Link path is not followed: {path}", "link", str(path)
            )
    if new_target or not target.exists():
        if not dry_run:
            _copy_new(source, target)
        return CollectAction(ACTION_COPY, source_text)

    if same_content(source, target):
        return CollectAction(ACTION_UNCHANGED, source_text)

    source_mtime = source.stat().st_mtime
    target_mtime = target.stat().st_mtime
    if source_mtime + MTIME_TOLERANCE_SECONDS < target_mtime:
        return CollectAction(
            ACTION_TARGET_NEWER,
            source_text,
            message="타겟 파일이 원본보다 최신이라 덮어쓰지 않았습니다.",
            message_code="newer",
        )

    archived = next_archive_path(archive_dir, target.name)
    if not dry_run:
        archived = _replace_with_archive(source, target, archived)
    return CollectAction(ACTION_REPLACE, source_text, archived_name=archived.name)


def run_collect_groups(
    groups,
    state_path: Path,
    dry_run: bool = False,
    progress_callback=None,
    should_cancel=None,
    configured_groups=None,
) -> CollectReport:
    """Run several groups with one shared state file. Group-level config errors do not stop the others."""
    groups = tuple(groups)
    configured = tuple(configured_groups) if configured_groups is not None else groups
    cyclic = [configured[index] for index in cyclic_group_indexes(configured)]
    state = CollectState.load(state_path)
    report = CollectReport()
    for group in groups:
        if should_cancel and should_cancel():
            report.cancelled = True
            break
        try:
            if group in cyclic:
                raise CollectConfigError(
                    f"[{group.name}] Collection groups form a feedback loop. Change source/target folders.",
                    "cycle",
                    group.name,
                )
            result = run_collect_group(
                group, state, dry_run, progress_callback, should_cancel
            )
            report.actions.extend(result.actions)
            report.cancelled = result.cancelled
            if result.cancelled:
                break
        except (CollectStateError, CollectRunError) as exc:
            if exc.report:
                report.actions.extend(exc.report.actions)
                report.cancelled = exc.report.cancelled
            exc.report = report
            raise
        except (CollectConfigError, OSError) as exc:
            logger.exception("Collect group failed: %s", group.name)
            report.actions.append(
                CollectAction(
                    ACTION_ERROR,
                    source=getattr(exc, "path", "") or group.name,
                    message=str(exc),
                    message_code=getattr(exc, "code", "io"),
                )
            )
    return report

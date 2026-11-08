import fnmatch
import hashlib
import logging
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)

# 파일명에서 버전 정보를 정밀하게 추출하기 위한 정규식
# 예: MyApp_v1.0.1.exe -> base: MyApp, ver: 1.0.1
# 예: App_v20260618.zip -> base: App, ver: 20260618
# 예: build-v2.0 -> base: build, ver: 2.0
# [_-]?[vV] 패턴 뒤에 점(.)으로 분할된 숫자 패턴이 오고 그것이 파일명 끝에 매칭되는 경우
VERSION_PATTERN = re.compile(r"^(.*?)[_-]?[vV](\d+(?:\.\d+)*)$")

DEFAULT_EXCLUDE_PATTERNS = ("~$*", "*.tmp", "Thumbs.db", ".DS_Store")
SYNC_TEMP_PREFIX = ".fileops-sync-"


def _move_without_replacement(source_path: str, target_path: str) -> None:
    """Move without replacement; POSIX unlink failure can leave both names."""
    if os.name == "nt":
        os.rename(source_path, target_path)
    else:
        os.link(source_path, target_path)
        os.unlink(source_path)


def _file_fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _normalized_version(version):
    """Treat trailing zero components as equivalent (1.0 == 1.0.0)."""
    version = tuple(version)
    while len(version) > 1 and version[-1] == 0:
        version = version[:-1]
    return version


def _check_analyzed_file(info, action, path):
    """Reject a file whose observed size or modification time changed after analysis."""
    if (("size" in action and info.st_size != action["size"])
            or ("mtime" in action and info.st_mtime != action["mtime"])):
        raise OSError(f"File changed since analysis: {path}")


def _file_digest(stream, cancelled=None):
    digest = hashlib.sha256()
    while True:
        if cancelled and cancelled():
            raise InterruptedError("Synchronization cancelled during content verification")
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.digest()


def _same_stable_content(first_path, second_path, cancelled=None):
    """Compare bytes only if both paths remain stable throughout the read."""
    with open(first_path, "rb") as first, open(second_path, "rb") as second:
        first_before = _file_fingerprint(os.fstat(first.fileno()))
        second_before = _file_fingerprint(os.fstat(second.fileno()))
        first_path_before = _file_fingerprint(os.stat(first_path))
        second_path_before = _file_fingerprint(os.stat(second_path))
        if first_before[:2] != first_path_before[:2] or second_before[:2] != second_path_before[:2]:
            raise OSError("File path changed during content comparison")
        same = _file_digest(first, cancelled) == _file_digest(second, cancelled)
        if (first_before != _file_fingerprint(os.fstat(first.fileno()))
                or second_before != _file_fingerprint(os.fstat(second.fileno()))
                or first_path_before != _file_fingerprint(os.stat(first_path))
                or second_path_before != _file_fingerprint(os.stat(second_path))):
            raise OSError("File changed during content comparison")
        return same


class SyncResult:
    """3-item unpackable result tuple that distinguishes held operations from errors."""

    def __init__(
        self,
        success: int = 0,
        fail: int = 0,
        errors: list | None = None,
        held: list | None = None,
    ):
        self.success = int(success)
        self.fail = int(fail)
        self.errors = list(errors or [])
        self.held = list(held or [])

    @property
    def held_count(self) -> int:
        return len(self.held)

    def __iter__(self):
        return iter((self.success, self.fail, self.errors))

    def __getitem__(self, index):
        return (self.success, self.fail, self.errors)[index]

    def __len__(self):
        return 3

    def __repr__(self):
        return f"SyncResult(success={self.success}, fail={self.fail}, errors={len(self.errors)}, held={len(self.held)})"


def check_approved_sync_action(
    approved_actions,
    action_type: str,
    source_path: str,
    target_path: str | None = None,
    group_name: str = "",
) -> bool:
    """Validate that the given path and action were approved in manual confirmation."""
    if approved_actions is None:
        return True
    norm_src = os.path.normcase(os.path.abspath(source_path)) if source_path else ""
    norm_tgt = os.path.normcase(os.path.abspath(target_path)) if target_path else ""

    action_aliases = {
        "copy": {"copy", "복사", "신규 복사", "최신 업데이트"},
        "archive": {"archive", "보관", "to_be_deleted이동", "구버전 정리"},
        "delete": {"delete", "삭제", "영구 삭제"},
        "trash": {"trash", "휴지통이동", "recycle"},
        "conflict_backup": {"conflict_backup", "충돌 보존 백업"},
        "date_sync": {"date_sync", "날짜 동기화"},
    }

    for item in approved_actions:
        if item.get("step") and item["step"] != "sync":
            continue
        if group_name and item.get("step") == "sync" and item.get("group") != group_name:
            continue
        if group_name and item.get("group") and item.get("group") != group_name:
            continue
        item_action = item.get("action", "")
        matched = False
        for std, aliases in action_aliases.items():
            if (action_type in aliases or action_type == std) and (item_action in aliases or item_action == std):
                matched = True
                break
        if not matched and item_action != action_type:
            continue
        item_src = item.get("source", "")
        if item_src and norm_src != item_src:
            continue
        item_tgt = item.get("target", "")
        if item_tgt and norm_tgt and norm_tgt != item_tgt:
            continue
        snapshot = item.get("source_snapshot")
        if snapshot is not None:
            try:
                info = os.stat(source_path)
            except OSError:
                return False
            current = (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_mode)
            if tuple(snapshot) != current:
                return False
        return True
    return False


class SyncManager:
    """
    여러 대상 폴더들을 비교 분석하여 가장 최신 파일로 동기화하고,
    구버전 파일들은 하위의 'to be deleted' 폴더로 안전하게 이송 및 정리하는 비즈니스 코어 클래스.
    """

    def __init__(
        self,
        folders: list,
        move_to_deleted: bool = True,
        archive_folder_name: str = "to be deleted",
        exclude_patterns: list | None = None,
        include_subfolders: bool = False,
        sync_mode: str = "two_way",
        observe_scan: bool = False,
        date_latest_only: bool = False,
        date_archive_mode: str = "folder",
        approved_actions: list | tuple | set | None = None,
        group_name: str = "",
        is_scheduled: bool = False,
    ):
        """
        Args:
            folders (list): 동기화할 대상 폴더 경로들의 리스트
            move_to_deleted (bool): 구버전 설정 호환용이며 값과 무관하게 보관합니다.
            archive_folder_name (str): 구버전 격리 보관 폴더명 (기본값: 'to be deleted')
            exclude_patterns (list): 동기화에서 제외할 와일드카드 패턴 목록
            include_subfolders (bool): 하위 폴더까지 재귀적으로 동기화할지 여부
            sync_mode (str): 'two_way' (양방향 최신본 일치) 또는 'one_way' (첫 번째 폴더 -> 나머지 단방향 배포)
            date_archive_mode (str): 날짜 구버전 처리 모드 ('trash' 또는 'folder')
            approved_actions (list|None): GUI 수동 확인에서 승인된 경로/행동 목록
            group_name (str): 동기화 그룹 이름
            is_scheduled (bool): 스케줄 예약 실행 여부
        """
        # 공백 제거 및 유효한 경로 필터링
        self.is_scheduled = bool(is_scheduled)
        self.date_latest_only = bool(date_latest_only)
        self.date_archive_mode = str(date_archive_mode or "folder")
        self.approved_actions = approved_actions
        self.group_name = str(group_name or "")
        self.folders = [os.path.abspath(f) for f in folders if f and (self.date_latest_only or os.path.exists(f))]
        # Retain the argument for older callers, but never delete sync versions.
        self.move_to_deleted = True
        self.date_archive_name = str(archive_folder_name or "to be deleted")
        cleaned_archive = os.path.basename(str(archive_folder_name or "").strip().strip("/\\"))
        if not cleaned_archive or cleaned_archive in (".", ".."):
            cleaned_archive = "to be deleted"
        self.archive_folder_name = self.date_archive_name if self.date_latest_only else cleaned_archive
        self.exclude_patterns = (
            [str(p).strip() for p in exclude_patterns if str(p).strip()]
            if exclude_patterns is not None
            else []
        )
        self.include_subfolders = bool(include_subfolders)
        self.sync_mode = sync_mode if sync_mode in ("two_way", "one_way") else "two_way"
        self.is_cancelled = False  # 작업 취소 플래그
        self.observe_scan = observe_scan
        self.scan_observations = {}
        self.scan_errors = []

    def cancel(self):
        """동기화 작업을 중간에 취소합니다."""
        self.is_cancelled = True
        logger.info("Sync cancellation requested.")

    def is_excluded(self, filename: str) -> bool:
        """지정된 제외 패턴(exclude_patterns)과 파일명이 매칭되는지 확인합니다."""
        base = os.path.basename(filename)
        if base.startswith((SYNC_TEMP_PREFIX, ".fileops-date-")) and base.endswith(".tmp"):
            return True
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(base, pattern) or fnmatch.fnmatch(filename, pattern):
                return True
        return False

    @staticmethod
    def parse_version(filename: str) -> tuple:
        """
        파일명에서 버전 문자열을 찾아 비교 가능한 정수 튜플로 반환합니다.
        예: '1.2.3' -> (1, 2, 3)
        버전 패턴이 없으면 None을 반환합니다.
        """
        # 확장자를 제외한 파일명 획득
        name_without_ext, _ = os.path.splitext(os.path.basename(filename))
        
        match = VERSION_PATTERN.match(name_without_ext)
        if match:
            base_name = match.group(1).rstrip('_-')
            if not base_name:  # base_name이 비어 있는 파일(예: v1.0.txt)은 유효한 버전 파일로 보지 않음
                return None
                
            version_str = match.group(2)
            
            try:
                # 점(.)으로 쪼개서 정수 리스트로 변환
                version_tuple = tuple(int(x) for x in version_str.split('.'))
                return base_name, version_tuple, version_str
            except ValueError:
                # 숫자로 파싱이 불가능한 경우 (예: vA.B.C) 패턴 매칭 스킵
                return None
        return None

    @staticmethod
    def is_safe_path(base_dir: str, path: str) -> bool:
        """Reject traversal and links/reparse points below the selected root.

        The root itself may legitimately be a link or a mounted cloud folder.
        This is a best-effort check, not an atomic defence against replacement
        of a path component by another process after the check.
        """
        base_abs = os.path.abspath(base_dir)
        path_abs = os.path.abspath(path)
        try:
            if os.path.commonpath([base_abs, path_abs]) != base_abs:
                return False
            relative = os.path.relpath(path_abs, base_abs)
            current = base_abs
            for part in relative.split(os.sep):
                if part == '.':
                    continue
                current = os.path.join(current, part)
                try:
                    info = os.lstat(current)
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(info.st_mode) or (getattr(info, 'st_file_attributes', 0) & 0x400):
                    return False
            return True
        except (OSError, ValueError):
            return False

    def get_unique_deleted_path(self, folder: str, filename: str) -> str:
        """to be deleted (또는 지정된 보관 폴더) 내에 덮어쓰기 유실이 발생하지 않도록 고유한 파일 경로를 생성합니다."""
        rel_dir = os.path.dirname(filename)
        base_filename = os.path.basename(filename)
        deleted_dir = os.path.join(folder, self.archive_folder_name, rel_dir) if rel_dir else os.path.join(folder, self.archive_folder_name)
        if not self.is_safe_path(folder, deleted_dir):
            raise PermissionError(f'Unsafe archive path: {deleted_dir}')
        os.makedirs(deleted_dir, exist_ok=True)
        if not self.is_safe_path(folder, deleted_dir):
            raise PermissionError(f'Unsafe archive path: {deleted_dir}')
        
        target_path = os.path.join(deleted_dir, base_filename)
        if not os.path.exists(target_path):
            return target_path
            
        name, ext = os.path.splitext(base_filename)
        counter = 1
        while True:
            new_filename = f"{name}_{counter}{ext}"
            new_path = os.path.join(deleted_dir, new_filename)
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def _register_scanned_file(
        self,
        folder: str,
        rel_path: str,
        full_path: str,
        version_groups: dict,
        plain_files: dict,
    ) -> None:
        if self.is_excluded(rel_path):
            return
        file_stat = os.stat(full_path)
        if self.observe_scan:
            self._observe_path(full_path, file_stat)
        mtime = file_stat.st_mtime
        size = file_stat.st_size
        base_item = os.path.basename(rel_path)
        rel_dir = os.path.dirname(rel_path)
        _, ext = os.path.splitext(base_item)
        ext = ext.lower()

        version_info = self.parse_version(base_item)
        if version_info:
            base_name, version_tuple, version_str = version_info
            # Windows filenames are ordinarily case-insensitive: versions of
            # the same family must not bypass a newer-target hold by casing.
            key = (rel_dir.casefold(), base_name.casefold(), ext) if rel_dir else (base_name.casefold(), ext)
            file_entry = {
                "folder": folder,
                "filename": rel_path,
                "full_path": full_path,
                "mtime": mtime,
                "size": size,
                "version_tuple": version_tuple,
                "version_str": version_str,
                "fingerprint": _file_fingerprint(file_stat),
            }
            version_groups.setdefault(key, []).append(file_entry)
        else:
            file_entry = {
                "folder": folder,
                "filename": rel_path,
                "full_path": full_path,
                "mtime": mtime,
                "size": size,
                "fingerprint": _file_fingerprint(file_stat),
            }
            plain_files.setdefault(os.path.normcase(rel_path), []).append(file_entry)

    def _observe_path(self, path, info=None):
        """Collect metadata only for a bounded, read-only change preview."""
        if len(self.scan_observations) >= 100_000:
            raise OSError("Preview exceeds 100000 observed paths; use a smaller scope.")
        info = info or os.stat(path)
        self.scan_observations[os.path.abspath(path)] = (
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_mode,
        )

    def scan_files(self) -> tuple:
        """
        대상 폴더들의 직계 최상위 파일들(또는 include_subfolders=True 시 하위 폴더 포함)을 스캔하여
        버전 파일 그룹과 일반 파일 그룹으로 분류합니다.
        
        Returns:
            tuple: (version_groups, plain_files)
        """
        version_groups = {} # {(base_name, ext): [file_info_dict, ...]}
        plain_files = {}    # {filename_with_ext: [file_info_dict, ...]}
        ignored_dirs = {"to be deleted", self.archive_folder_name.lower()}
        self.scan_observations.clear()
        self.scan_errors.clear()

        for folder in self.folders:
            if self.is_cancelled:
                break
                
            try:
                if self.observe_scan:
                    self._observe_path(folder)
                if self.include_subfolders:
                    for root, dirs, files in os.walk(folder, onerror=self.scan_errors.append):
                        if self.is_cancelled:
                            break
                        if self.observe_scan:
                            self._observe_path(root)
                        dirs[:] = [
                            d for d in dirs
                            if d.lower() not in ignored_dirs and not self.is_excluded(d)
                        ]
                        for item in files:
                            full_path = os.path.join(root, item)
                            rel_path = os.path.relpath(full_path, folder)
                            self._register_scanned_file(folder, rel_path, full_path, version_groups, plain_files)
                else:
                    # 직계 최상위 아이템 목록 조회
                    for item in os.listdir(folder):
                        full_path = os.path.join(folder, item)
                        
                        # 폴더 및 'to be deleted' 폴더는 동기화 대상에서 명시적 제외
                        if os.path.isdir(full_path) or item.lower() in ignored_dirs:
                            continue
                        self._register_scanned_file(folder, item, full_path, version_groups, plain_files)
            except Exception as e:
                self.scan_errors.append(e)
                logger.error(f"Error scanning folder '{folder}': {e}")
                
        return version_groups, plain_files

    def analyze_sync(self) -> list:
        """
        동기화 실행 전 가상 분석(Dry Run)을 실행하여 조치 계획 목록을 생성합니다.
        
        Returns:
            list: [ { "filename": str, "status": str, "source_folder": str, "target_folder": str, "action": str, "size": int }, ... ]
        """
        if self.date_latest_only:
            from src.core.date_sync import analyze_date_sync
            return analyze_date_sync(self)
        self.is_cancelled = False
        actions = []
        
        if len(self.folders) < 2:
            logger.warning("Sync requires at least 2 folders.")
            return actions

        version_groups, plain_files = self.scan_files()
        master_folder = self.folders[0]
        target_folders = self.folders[1:] if self.sync_mode == "one_way" else self.folders

        # 1. 버전 파일 그룹 분석
        for entries in version_groups.values():
            if self.is_cancelled:
                break

            if self.sync_mode == "one_way":
                master_entries = [e for e in entries if e["folder"] == master_folder]
                if not master_entries:
                    continue
                newest_entry = max(master_entries, key=lambda x: (_normalized_version(x["version_tuple"]), x["fingerprint"][3]))
            else:
                # 전체 폴더 중 가장 버전이 높은 최신 파일 결정
                # 버전이 동일할 경우 수정 시간이 가장 최근인 파일 선택
                newest_entry = max(entries, key=lambda x: (_normalized_version(x["version_tuple"]), x["fingerprint"][3]))

                equivalent = next((e for e in entries
                                   if _normalized_version(e['version_tuple']) == _normalized_version(newest_entry['version_tuple'])
                                   and os.path.normcase(e['filename']) != os.path.normcase(newest_entry['filename'])), None)
                if equivalent:
                    reason = 'Target has an equivalent version with a different filename'
                    actions.append({'filename': equivalent['filename'], 'status': reason, 'reason': reason,
                                    'source_folder': newest_entry['folder'], 'target_folder': equivalent['folder'],
                                    'action': '보류', 'size': equivalent['size'], 'mtime': equivalent['mtime']})
                    continue
                tied = [e for e in entries if _normalized_version(e['version_tuple']) == _normalized_version(newest_entry['version_tuple'])
                        and os.path.normcase(e['filename']) == os.path.normcase(newest_entry['filename'])
                        and e['fingerprint'][3] == newest_entry['fingerprint'][3]
                        and e is not newest_entry]
                try:
                    conflict = next((e for e in tied if not _same_stable_content(newest_entry['full_path'], e['full_path'], lambda: self.is_cancelled)), None)
                except OSError as exc:
                    self.scan_errors.append(exc)
                    logger.warning('Could not compare latest version files: %s', exc)
                    continue
                if conflict:
                    reason = 'Same version files differ with equal modification times'
                    actions.append({'filename': conflict['filename'], 'status': reason, 'reason': reason,
                                    'source_folder': newest_entry['folder'], 'target_folder': conflict['folder'],
                                    'action': '보류', 'size': conflict['size'], 'mtime': conflict['mtime']})
                    continue

            newest_filename = newest_entry["filename"]
            newest_ver_str = newest_entry["version_str"]
            
            # 각 폴더별 상태 체크
            for folder in target_folders:
                # 해당 폴더에 존재하는 이 그룹의 파일들 탐색
                folder_entries = [e for e in entries if e["folder"] == folder]
                higher_entries = [e for e in folder_entries if _normalized_version(e["version_tuple"]) > _normalized_version(newest_entry["version_tuple"])] if self.sync_mode == "one_way" else []
                equivalent_entries = [e for e in folder_entries if _normalized_version(e["version_tuple"]) == _normalized_version(newest_entry["version_tuple"]) and os.path.normcase(e["filename"]) != os.path.normcase(newest_filename)]
                if higher_entries or equivalent_entries:
                    held_entry = max(higher_entries, key=lambda e: _normalized_version(e["version_tuple"])) if higher_entries else equivalent_entries[0]
                    reason = 'Target has a newer version' if higher_entries else 'Target has an equivalent version with a different filename'
                    actions.append({
                        "filename": held_entry["filename"],
                        "status": reason,
                        "reason": reason,
                        "source_folder": newest_entry["folder"],
                        "target_folder": folder,
                        "action": "보류",
                        "size": newest_entry["size"],
                        "mtime": newest_entry["mtime"],
                    })
                    continue
                
                if not folder_entries:
                    # 파일이 전혀 없는 폴더 -> 최신 파일 복사(동기화) 대상
                    actions.append({
                        "filename": newest_filename,
                        "status": "신규 복사",
                        "source_folder": newest_entry["folder"],
                        "target_folder": folder,
                        "action": "복사",
                        "size": newest_entry["size"],
                        "mtime": newest_entry["mtime"]
                    })
                else:
                    for entry in folder_entries:
                        # 최신 생존 파일이 아닌 구버전 파일 -> to be deleted 이송 대상
                        if os.path.normcase(entry["filename"]) != os.path.normcase(newest_filename):
                            actions.append({
                                "filename": entry["filename"],
                                "status": f"구버전 정리 (최신: v{newest_ver_str})",
                                "source_folder": folder,
                                "target_folder": os.path.join(folder, self.archive_folder_name),
                                "action": "to_be_deleted이동",
                                "size": entry["size"],
                                "mtime": entry["mtime"]
                            })
                            
                            # 만약 이 폴더에 최신 파일 본체도 존재하지 않는다면, 복사 액션도 함께 추가
                            if not any(os.path.normcase(e["filename"]) == os.path.normcase(newest_filename) for e in folder_entries):
                                # 중복 추가 방지를 위해 하나만 추가
                                if not any(a["filename"] == newest_filename and a["target_folder"] == folder for a in actions):
                                    actions.append({
                                        "filename": newest_filename,
                                        "status": "최신 업데이트",
                                        "source_folder": newest_entry["folder"],
                                        "target_folder": folder,
                                        "action": "복사",
                                        "size": newest_entry["size"],
                                        "mtime": newest_entry["mtime"]
                                    })
                        else:
                            if os.path.normcase(entry["full_path"]) == os.path.normcase(newest_entry["full_path"]):
                                continue
                            try:
                                same = _same_stable_content(
                                    entry["full_path"], newest_entry["full_path"], lambda: self.is_cancelled
                                )
                            except OSError as exc:
                                self.scan_errors.append(exc)
                                logger.warning("Could not compare version files; holding '%s': %s", entry["filename"], exc)
                                continue
                            if same:
                                continue
                            if self.sync_mode == "two_way" and entry["fingerprint"][3] == newest_entry["fingerprint"][3]:
                                reason = "Same version files differ with equal modification times"
                                actions.append({
                                    "filename": entry["filename"], "status": reason, "reason": reason,
                                    "source_folder": newest_entry["folder"], "target_folder": folder,
                                    "action": "보류", "size": entry["size"], "mtime": entry["mtime"],
                                })
                                continue
                            # The user chose source authority for one-way sync and
                            # the newer modification time for two-way sync.
                            actions.append({
                                "filename": entry["filename"], "status": "구버전 정리",
                                "source_folder": folder,
                                "target_folder": os.path.join(folder, self.archive_folder_name),
                                "action": "to_be_deleted이동", "size": entry["size"], "mtime": entry["mtime"],
                            })
                            actions.append({
                                "filename": newest_filename, "status": "최신 업데이트",
                                "source_folder": newest_entry["folder"], "target_folder": folder,
                                "action": "복사", "size": newest_entry["size"], "mtime": newest_entry["mtime"],
                            })

        # 2. 일반 파일 그룹 분석
        for entries in plain_files.values():
            if self.is_cancelled:
                break

            if self.sync_mode == "one_way":
                master_entry = next((e for e in entries if e["folder"] == master_folder), None)
                if not master_entry:
                    continue
                newest_entry = master_entry
                has_conflict = False
            else:
                # 수정 시간 기준 가장 최신 파일 결정
                newest_entry = max(entries, key=lambda x: x["fingerprint"][3])

                tied = [e for e in entries if e is not newest_entry and e['fingerprint'][3] == newest_entry['fingerprint'][3]]
                try:
                    conflict = next((e for e in tied if not _same_stable_content(newest_entry['full_path'], e['full_path'], lambda: self.is_cancelled)), None)
                except OSError as exc:
                    self.scan_errors.append(exc)
                    logger.warning('Could not compare latest files: %s', exc)
                    continue
                if conflict:
                    reason = 'Different contents with identical modification times'
                    actions.append({'filename': conflict['filename'], 'status': reason, 'reason': reason,
                                    'source_folder': newest_entry['folder'], 'target_folder': conflict['folder'],
                                    'action': '보류', 'size': conflict['size'], 'mtime': conflict['mtime']})
                    continue
                
                # 충돌 검증 (10초 이내 오차이면서 다른 내용을 가질 가능성이 있는 경우 경고)
                has_conflict = False
                for entry in entries:
                    if entry != newest_entry:
                        # 수정 시간 차이가 10초 이내인 경우 충돌 후보로 판별
                        time_diff = abs(newest_entry["mtime"] - entry["mtime"])
                        if time_diff < 10.0 and newest_entry["size"] != entry["size"]:
                            has_conflict = True
                            break

            filename = newest_entry['filename']
            for folder in target_folders:
                folder_entry = next((e for e in entries if e["folder"] == folder), None)
                
                if not folder_entry:
                    # 파일이 아예 없는 폴더 -> 복사 대상
                    actions.append({
                        "filename": filename,
                        "status": "신규 복사",
                        "source_folder": newest_entry["folder"],
                        "target_folder": folder,
                        "action": "복사",
                        "size": newest_entry["size"],
                        "mtime": newest_entry["mtime"]
                    })
                else:
                    if folder_entry["full_path"] != newest_entry["full_path"]:
                        if folder_entry['filename'] != filename:
                            actions.append({"filename": folder_entry['filename'], "status": "Filename case differs", "reason": "Filename case differs", "source_folder": newest_entry['folder'], "target_folder": folder, "action": "보류", "size": folder_entry['size'], "mtime": folder_entry['mtime']})
                            continue
                        if abs(folder_entry["mtime"] - newest_entry["mtime"]) < 1.0 and folder_entry["size"] == newest_entry["size"]:
                            try:
                                if _same_stable_content(folder_entry["full_path"], newest_entry["full_path"], lambda: self.is_cancelled):
                                    continue
                            except OSError as exc:
                                self.scan_errors.append(exc)
                                logger.warning("Could not compare sync files; holding '%s': %s", filename, exc)
                                continue
                        if self.sync_mode == 'two_way' and folder_entry['fingerprint'][3] == newest_entry['fingerprint'][3]:
                            actions.append({"filename": filename, "status": "Different contents with identical modification times", "reason": "Different contents with identical modification times", "source_folder": newest_entry['folder'], "target_folder": folder, "action": "보류", "size": folder_entry['size'], "mtime": folder_entry['mtime']})
                            continue
                        if has_conflict:
                            # 충돌본을 먼저 보존하고 같은 실행에서 최신본까지 배포합니다.
                            actions.append({
                                "filename": filename,
                                "status": "동시 수정 충돌",
                                "source_folder": folder,
                                "target_folder": folder,
                                "action": "충돌 보존 백업",
                                "size": folder_entry["size"],
                                "mtime": folder_entry["mtime"]
                            })
                            actions.append({
                                "filename": filename,
                                "status": "충돌 백업 후 최신 업데이트",
                                "source_folder": newest_entry["folder"],
                                "target_folder": folder,
                                "action": "복사",
                                "size": newest_entry["size"],
                                "mtime": newest_entry["mtime"]
                            })
                        else:
                            # 구버전 파일을 to be deleted로 치워두고, 최신 파일을 복사
                            actions.append({
                                "filename": filename,
                                "status": "구버전 정리",
                                "source_folder": folder,
                                "target_folder": os.path.join(folder, self.archive_folder_name),
                                "action": "to_be_deleted이동",
                                "size": folder_entry["size"],
                                "mtime": folder_entry["mtime"]
                            })
                            actions.append({
                                "filename": filename,
                                "status": "최신 업데이트",
                                "source_folder": newest_entry["folder"],
                                "target_folder": folder,
                                "action": "복사",
                                "size": newest_entry["size"],
                                "mtime": newest_entry["mtime"]
                            })

        fingerprints = {os.path.normcase(os.path.abspath(entry['full_path'])): entry['fingerprint']
                        for group in list(version_groups.values()) + list(plain_files.values()) for entry in group}
        for action in actions:
            source = os.path.normcase(os.path.abspath(os.path.join(action['source_folder'], action['filename'])))
            if source in fingerprints:
                action['source_fingerprint'] = fingerprints[source]
        return actions

    def execute_sync(self, actions: list, progress_callback=None) -> tuple:
        """Execute the analyzed actions, preserving existing files on failure.

        Each replacement is staged and verified before its approved version
        family is archived. Failed publication attempts restore archived files
        without replacing another file that appeared in the meantime.

        Args:
            actions: Action plan returned by analyze_sync().
            progress_callback: Optional callback (current_count, total_count, filename).

        Returns:
            SyncResult: Successful and failed action counts, errors, and held items.
        """
        if self.date_latest_only:
            from src.core.date_sync import execute_date_sync
            return execute_date_sync(self, actions, progress_callback)
        if self.scan_errors:
            return SyncResult(0, len(self.scan_errors), [str(e) for e in self.scan_errors])
        self.is_cancelled = False
        success, fail, errors, held = 0, 0, [], []

        def family(filename):
            version = self.parse_version(filename)
            if version:
                return (os.path.dirname(filename).casefold(), version[0].casefold(),
                        os.path.splitext(filename)[1].casefold())
            return (os.path.dirname(filename), os.path.basename(filename), None)

        copies = [a for a in actions if a['action'] == '복사']
        assigned = set()
        batches = []
        for copy in copies:
            related = [a for a in actions if a['action'] in ('to_be_deleted이동', '충돌 보존 백업')
                       and os.path.normcase(os.path.abspath(a['source_folder'])) == os.path.normcase(os.path.abspath(copy['target_folder']))
                       and family(a['filename']) == family(copy['filename'])]
            batches.append((related, copy))
            assigned.update(id(a) for a in related)
            assigned.add(id(copy))
        batches.extend(([a], None) for a in actions if id(a) not in assigned)

        for old_actions, copy in batches:
            if self.is_cancelled:
                errors.append('사용자에 의해 작업이 중단되었습니다.')
                break
            if copy is None and old_actions[0]['action'] == '보류':
                item = old_actions[0]
                held.append(f"{item['status']}: {os.path.join(item['target_folder'], item['filename'])}")
                continue
            temp_path = None
            moved = []
            try:
                for action in old_actions + ([copy] if copy else []):
                    filename = action['filename']
                    source = os.path.join(action['source_folder'], filename)
                    target = os.path.join(action['target_folder'], filename)
                    if not self.is_safe_path(action['source_folder'], source):
                        raise PermissionError(f'Path Traversal Blocked: {source}')
                    kind = 'archive' if action['action'] == 'to_be_deleted이동' else action['action']
                    if not check_approved_sync_action(self.approved_actions, kind, source,
                                                      target if kind == '복사' else None, self.group_name):
                        raise PermissionError(f'Action not approved or file changed since preview: {kind} for {filename}')
                    if progress_callback:
                        progress_callback(success + fail, len(actions), filename)
                if copy:
                    source = os.path.join(copy['source_folder'], copy['filename'])
                    target = os.path.join(copy['target_folder'], copy['filename'])
                    if not self.is_safe_path(copy['target_folder'], target):
                        raise PermissionError(f'Path Traversal Blocked on target copy: {target}')
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    if not self.is_safe_path(copy['target_folder'], target):
                        raise PermissionError(f'Unsafe target copy path: {target}')
                    if not self.is_safe_path(copy['source_folder'], source):
                        raise PermissionError(f'Unsafe source copy path: {source}')
                    with open(source, 'rb') as stream:
                        source_info = os.fstat(stream.fileno())
                        _check_analyzed_file(source_info, copy, source)
                        before = _file_fingerprint(source_info)
                        path_before = _file_fingerprint(os.stat(source))
                        if before[:2] != path_before[:2]:
                            raise OSError('Source path changed during copy; publication blocked')
                        fd, temp_path = tempfile.mkstemp(prefix=SYNC_TEMP_PREFIX, suffix='.tmp', dir=os.path.dirname(target))
                        with os.fdopen(fd, 'wb') as out:
                            shutil.copyfileobj(stream, out)
                        stream.seek(0)
                        with open(temp_path, 'rb') as copied:
                            source_digest = _file_digest(stream, lambda: self.is_cancelled)
                            copy_digest = _file_digest(copied, lambda: self.is_cancelled)
                        shutil.copystat(stream.fileno(), temp_path)
                        stream.seek(0)
                        final_digest = _file_digest(stream, lambda: self.is_cancelled)
                        if (source_digest != copy_digest or final_digest != copy_digest
                                or before != _file_fingerprint(os.fstat(stream.fileno()))
                                or path_before != _file_fingerprint(os.stat(source))):
                            raise OSError('Source changed during copy; publication blocked')
                for action in old_actions:
                    if self.is_cancelled:
                        raise InterruptedError('Synchronization cancelled before publication')
                    filename = action['filename']
                    source = os.path.join(action['source_folder'], filename)
                    if action['action'] == '충돌 보존 백업':
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        name, ext = os.path.splitext(os.path.basename(filename))
                        filename = os.path.join(os.path.dirname(filename), f'{name}_conflict_{timestamp}{ext}')
                    elif action['action'] != 'to_be_deleted이동':
                        raise ValueError(f"Unsupported synchronization action: {action['action']}")
                    kind = 'archive' if action['action'] == 'to_be_deleted이동' else action['action']
                    if not check_approved_sync_action(self.approved_actions, kind, source, None, self.group_name):
                        raise PermissionError(f'Unapproved or changed file action blocked: {source}')
                    expected = action.get('source_fingerprint')
                    if expected is not None and tuple(expected) != _file_fingerprint(os.stat(source)):
                        raise OSError(f'File changed since analysis: {source}')
                    if not self.is_safe_path(action['source_folder'], source):
                        raise PermissionError(f'Unsafe archive source: {source}')
                    _check_analyzed_file(os.stat(source, follow_symlinks=False), action, source)
                    with open(source, 'rb') as archive_source:
                        before_archive_path = _file_fingerprint(os.fstat(archive_source.fileno()))
                        archive_digest = _file_digest(archive_source, lambda: self.is_cancelled)
                        if before_archive_path != _file_fingerprint(os.fstat(archive_source.fileno())):
                            raise OSError(f'File changed while verifying: {source}')
                    archive = self.get_unique_deleted_path(action['source_folder'], filename)
                    if not self.is_safe_path(action['source_folder'], archive):
                        raise PermissionError(f'Path Traversal Blocked on target: {archive}')
                    if not self.is_safe_path(action['source_folder'], source):
                        raise PermissionError(f'Unsafe archive source: {source}')
                    _check_analyzed_file(os.stat(source, follow_symlinks=False), action, source)
                    if not check_approved_sync_action(self.approved_actions, kind, source, None, self.group_name):
                        raise PermissionError(f'Unapproved or changed file action blocked: {source}')
                    if expected is not None and tuple(expected) != _file_fingerprint(os.stat(source, follow_symlinks=False)):
                        raise OSError(f'File changed since analysis: {source}')
                    with open(source, 'rb') as archive_source:
                        if (before_archive_path != _file_fingerprint(os.fstat(archive_source.fileno()))
                                or archive_digest != _file_digest(archive_source, lambda: self.is_cancelled)
                                or before_archive_path != _file_fingerprint(os.fstat(archive_source.fileno()))):
                            raise OSError(f'File changed while preparing archive: {source}')
                    _move_without_replacement(source, archive)
                    moved.append((source, archive))
                if copy:
                    if self.is_cancelled:
                        raise InterruptedError('Synchronization cancelled before publication')
                    if not self.is_safe_path(copy['target_folder'], target):
                        raise PermissionError(f'Unsafe target copy path: {target}')
                    _move_without_replacement(temp_path, target)
                    temp_path = None
                success += len(old_actions) + bool(copy)
            except Exception as exc:  # noqa: BLE001 - restore archived files after any batch failure
                fail += len(old_actions) + bool(copy)
                recovery = []
                for original, archive in reversed(moved):
                    try:
                        root = next(a['source_folder'] for a in old_actions
                                    if os.path.join(a['source_folder'], a['filename']) == original)
                        if not self.is_safe_path(root, original) or not self.is_safe_path(root, archive):
                            raise PermissionError('Unsafe recovery path')
                        _move_without_replacement(archive, original)
                    except Exception as restore_error:  # noqa: BLE001 - report every failed restoration
                        recovery.append(f'복원 실패: {original}; 보관 위치: {archive} ({restore_error})')
                errors.append(f'동기화 실패: {exc}' + ('; ' + '; '.join(recovery) if recovery else ''))
            finally:
                if temp_path is not None and os.path.exists(temp_path):
                    try:
                        os.chmod(temp_path, stat.S_IWRITE | stat.S_IREAD)
                    except OSError as exc:
                        logger.warning('Could not change sync temporary file permissions: %s', exc)
                    try:
                        os.unlink(temp_path)
                    except OSError as exc:
                        errors.append(f'임시 파일 정리 실패: {temp_path}: {exc}')
                        fail += 1
        return SyncResult(success, fail, errors, held)

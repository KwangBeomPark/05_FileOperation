import os
import re
import shutil
import logging
import stat
from datetime import datetime

logger = logging.getLogger(__name__)

# 파일명에서 버전 정보를 정밀하게 추출하기 위한 정규식
# 예: MyApp_v1.0.1.exe -> base: MyApp, ver: 1.0.1
# 예: App_v20260618.zip -> base: App, ver: 20260618
# 예: build-v2.0 -> base: build, ver: 2.0
# [_-]?[vV] 패턴 뒤에 점(.)으로 분할된 숫자 패턴이 오고 그것이 파일명 끝에 매칭되는 경우
VERSION_PATTERN = re.compile(r"^(.*?)[_-]?[vV](\d+(?:\.\d+)*)$")

class SyncManager:
    """
    여러 대상 폴더들을 비교 분석하여 가장 최신 파일로 동기화하고,
    구버전 파일들은 하위의 'to be deleted' 폴더로 안전하게 이송 및 정리하는 비즈니스 코어 클래스.
    """

    def __init__(self, folders: list, move_to_deleted: bool = True):
        """
        Args:
            folders (list): 동기화할 대상 폴더 경로들의 리스트
            move_to_deleted (bool): 구버전을 삭제하지 않고 'to be deleted' 폴더로 이동할지 여부
        """
        # 공백 제거 및 유효한 경로 필터링
        self.folders = [os.path.abspath(f) for f in folders if f and os.path.exists(f)]
        self.move_to_deleted = move_to_deleted
        self.is_cancelled = False  # 작업 취소 플래그

    def cancel(self):
        """동기화 작업을 중간에 취소합니다."""
        self.is_cancelled = True
        logger.info("Sync cancellation requested.")

    @staticmethod
    def parse_version(filename: str) -> tuple:
        """
        파일명에서 버전 문자열을 찾아 비교 가능한 정수 튜플로 반환합니다.
        예: '1.2.3' -> (1, 2, 3)
        버전 패턴이 없으면 None을 반환합니다.
        """
        # 확장자를 제외한 파일명 획득
        name_without_ext, _ = os.path.splitext(filename)
        
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
        """경로 탈출(Path Traversal) 공격 방지를 위해 경로 유효성을 검증합니다."""
        base_abs = os.path.abspath(base_dir)
        path_abs = os.path.abspath(path)
        return os.path.commonpath([base_abs]) == os.path.commonpath([base_abs, path_abs])

    def get_unique_deleted_path(self, folder: str, filename: str) -> str:
        """to be deleted 폴더 내에 덮어쓰기 유실이 발생하지 않도록 고유한 파일 경로를 생성합니다."""
        deleted_dir = os.path.join(folder, "to be deleted")
        os.makedirs(deleted_dir, exist_ok=True)
        
        target_path = os.path.join(deleted_dir, filename)
        if not os.path.exists(target_path):
            return target_path
            
        name, ext = os.path.splitext(filename)
        counter = 1
        while True:
            new_filename = f"{name}_{counter}{ext}"
            new_path = os.path.join(deleted_dir, new_filename)
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    def scan_files(self) -> tuple:
        """
        대상 폴더들의 직계 최상위 파일들을 스캔하여 버전 파일 그룹과 일반 파일 그룹으로 분류합니다.
        
        Returns:
            tuple: (version_groups, plain_files)
        """
        version_groups = {} # {(base_name, ext): [file_info_dict, ...]}
        plain_files = {}    # {filename_with_ext: [file_info_dict, ...]}

        for folder in self.folders:
            if self.is_cancelled:
                break
                
            try:
                # 직계 최상위 아이템 목록 조회
                for item in os.listdir(folder):
                    full_path = os.path.join(folder, item)
                    
                    # 폴더 및 'to be deleted' 폴더는 동기화 대상에서 명시적 제외
                    if os.path.isdir(full_path) or item.lower() == "to be deleted":
                        continue
                        
                    # 파일 메타데이터 수집
                    stat = os.stat(full_path)
                    mtime = stat.st_mtime
                    size = stat.st_size
                    _, ext = os.path.splitext(item)
                    ext = ext.lower()
                    
                    # 버전 정보 파싱 시도
                    version_info = self.parse_version(item)
                    
                    if version_info:
                        base_name, version_tuple, version_str = version_info
                        key = (base_name, ext)
                        file_entry = {
                            "folder": folder,
                            "filename": item,
                            "full_path": full_path,
                            "mtime": mtime,
                            "size": size,
                            "version_tuple": version_tuple,
                            "version_str": version_str
                        }
                        version_groups.setdefault(key, []).append(file_entry)
                    else:
                        # 일반 파일
                        file_entry = {
                            "folder": folder,
                            "filename": item,
                            "full_path": full_path,
                            "mtime": mtime,
                            "size": size
                        }
                        plain_files.setdefault(item, []).append(file_entry)
            except Exception as e:
                logger.error(f"Error scanning folder '{folder}': {e}")
                
        return version_groups, plain_files

    def analyze_sync(self) -> list:
        """
        동기화 실행 전 가상 분석(Dry Run)을 실행하여 조치 계획 목록을 생성합니다.
        
        Returns:
            list: [ { "filename": str, "status": str, "source_folder": str, "target_folder": str, "action": str, "size": int }, ... ]
        """
        self.is_cancelled = False
        actions = []
        
        if len(self.folders) < 2:
            logger.warning("Sync requires at least 2 folders.")
            return actions

        version_groups, plain_files = self.scan_files()

        # 1. 버전 파일 그룹 분석
        for _, entries in version_groups.items():
            if self.is_cancelled:
                break
                
            # 전체 폴더 중 가장 버전이 높은 최신 파일 결정
            # 버전이 동일할 경우 수정 시간이 가장 최근인 파일 선택
            newest_entry = max(entries, key=lambda x: (x["version_tuple"], x["mtime"]))
            newest_filename = newest_entry["filename"]
            newest_ver_str = newest_entry["version_str"]
            
            # 각 폴더별 상태 체크
            for folder in self.folders:
                # 해당 폴더에 존재하는 이 그룹의 파일들 탐색
                folder_entries = [e for e in entries if e["folder"] == folder]
                
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
                        if entry["filename"] != newest_filename:
                            actions.append({
                                "filename": entry["filename"],
                                "status": f"구버전 정리 (최신: v{newest_ver_str})",
                                "source_folder": folder,
                                "target_folder": os.path.join(folder, "to be deleted"),
                                "action": "to_be_deleted이동",
                                "size": entry["size"],
                                "mtime": entry["mtime"]
                            })
                            
                            # 만약 이 폴더에 최신 파일 본체도 존재하지 않는다면, 복사 액션도 함께 추가
                            if not any(e["filename"] == newest_filename for e in folder_entries):
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
                            # 이미 최신 파일인 경우 -> 정상 상태로 스킵
                            pass

        # 2. 일반 파일 그룹 분석
        for filename, entries in plain_files.items():
            if self.is_cancelled:
                break
                
            # 수정 시간 기준 가장 최신 파일 결정
            newest_entry = max(entries, key=lambda x: x["mtime"])
            
            # 충돌 검증 (10초 이내 오차이면서 다른 내용을 가질 가능성이 있는 경우 경고)
            has_conflict = False
            for entry in entries:
                if entry != newest_entry:
                    # 수정 시간 차이가 10초 이내인 경우 충돌 후보로 판별
                    time_diff = abs(newest_entry["mtime"] - entry["mtime"])
                    if time_diff < 10.0 and newest_entry["size"] != entry["size"]:
                        has_conflict = True
                        break

            for folder in self.folders:
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
                                "target_folder": os.path.join(folder, "to be deleted"),
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

        return actions

    def execute_sync(self, actions: list, progress_callback=None) -> tuple:
        """
        가상 분석(Dry Run) 액션 계획을 토대로 실제 파일 복사 및 이동 처리를 수행합니다.
        
        Args:
            actions (list): analyze_sync()로 도출된 액션 리스트
            progress_callback (callable): 진행률 피드백 콜백 (current_count, total_count, filename)
            
        Returns:
            tuple: (success_count, fail_count, list_of_errors)
        """
        self.is_cancelled = False
        success_count = 0
        fail_count = 0
        errors = []
        
        total = len(actions)
        
        # 1. 안전을 위해 이동(to_be_deleted) 작업을 먼저 처리한 후, 복사(copy) 작업을 처리합니다.
        # 이렇게 정렬해야 복사 덮어쓰기 전에 기존 파일이 안전하게 이송되어 대피합니다.
        ordered_actions = sorted(actions, key=lambda x: 0 if "이동" in x["action"] or "백업" in x["action"] else 1)

        for idx, action in enumerate(ordered_actions):
            if self.is_cancelled:
                logger.info("Sync execution interrupted by user cancel.")
                errors.append("사용자에 의해 작업이 중단되었습니다.")
                break
                
            filename = action["filename"]
            action_type = action["action"]
            src_folder = action["source_folder"]
            tgt_folder = action["target_folder"]
            
            src_path = os.path.join(src_folder, filename)
            
            # 콜백 알림
            if progress_callback:
                progress_callback(idx, total, filename)

            try:
                # 1) 경로 보안성 검증
                if not self.is_safe_path(src_folder, src_path):
                    raise PermissionError(f"Path Traversal Blocked: {src_path} leaves root {src_folder}")
                
                # 2) 개별 액션 분기
                if action_type == "to_be_deleted이동":
                    if self.move_to_deleted:
                        # 덮어쓰기 유실 방지 고유 경로 획득
                        unique_deleted_path = self.get_unique_deleted_path(src_folder, filename)
                        
                        # 경로 탈출 2차 검증
                        if not self.is_safe_path(src_folder, unique_deleted_path):
                            raise PermissionError(f"Path Traversal Blocked on target: {unique_deleted_path}")
                            
                        # 파일 이동
                        shutil.move(src_path, unique_deleted_path)
                        logger.info(f"Moved old version: {filename} -> to be deleted")
                    else:
                        # 백업하지 않도록 설정된 경우 삭제
                        os.remove(src_path)
                        logger.info(f"Deleted old version: {filename}")
                        
                elif action_type == "충돌 보존 백업":
                    # 충돌이 발생한 로컬 파일은 삭제하거나 덮어쓰지 않고 conflict 접미사를 붙여 백업 디렉토리로 이동
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    name, ext = os.path.splitext(filename)
                    conflict_filename = f"{name}_conflict_{timestamp}{ext}"
                    
                    unique_deleted_path = self.get_unique_deleted_path(src_folder, conflict_filename)
                    shutil.move(src_path, unique_deleted_path)
                    logger.warning(f"Conflict preserved: {filename} -> to be deleted/{conflict_filename}")
                    
                elif action_type == "복사":
                    tgt_path = os.path.join(tgt_folder, filename)
                    
                    # 목적지 보안성 검증
                    if not self.is_safe_path(tgt_folder, tgt_path):
                        raise PermissionError(f"Path Traversal Blocked on target copy: {tgt_path}")
                        
                    # 대상 파일이 존재하고 읽기 전용 속성이 있는 경우 해제 처리 (시니어 노하우)
                    if os.path.exists(tgt_path):
                        try:
                            os.chmod(tgt_path, stat.S_IWRITE)
                        except Exception as chmod_err:
                            logger.warning(f"Failed to lift read-only attribute on '{tgt_path}': {chmod_err}")
                            
                    # 파일 복사 (메타데이터 수정시간 포함 복사)
                    shutil.copy2(src_path, tgt_path)
                    logger.info(f"Copied latest: {src_path} -> {tgt_path}")
                    
                success_count += 1
                
            except Exception as e:
                fail_count += 1
                err_msg = f"Failed {action_type} for '{filename}': {str(e)}"
                logger.error(err_msg)
                errors.append(err_msg)

        return success_count, fail_count, errors

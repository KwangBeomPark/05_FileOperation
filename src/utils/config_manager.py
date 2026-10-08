import copy
import json
import os
import threading
import shutil
import uuid
from .atomic_write import atomic_write_json
from .security import encrypt_data, decrypt_data
import logging
from src.app_identity import CONFIG_FILENAME, user_data_dir

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    애플리케이션 설정을 스레드 안전하게 JSON 파일로 로드하고 저장하는 클래스.
    보안 데이터(GitHub Token 등)는 자동으로 DPAPI를 통해 암/복호화되어 보관됩니다.
    """
    
    DEFAULT_CONFIG = {
        "config_version": 3,

        # PDF 변환 설정
        "output_folder": "",
        "last_pdf_directory": "",
        "recent_files": [],
        "promotion_regex": r"PL-[A-Z]TS[A-Z]-202\d{5}-\d{4}",
        "tesseract_path": "",
        "dpi_large": 100,
        "dpi_small": 150,
        "dpi_threshold": 842,
        "document_types": ["1. Claim Entry", "3. Customer Sign"],
        "last_selected_doc_type": "1. Claim Entry",
        "settlement_working_folder": "",
        "search_depth": 2,
        
        # EML 변환 설정
        "eml_incremental": True,
        "eml_output_width": 1024,
        "offline_chromium_path": "",
        "last_eml_directory": "",
        "eml_tasks": [],                 # 다중 EML 변환 태스크 목록 [{"name": "태스크명", "source_folder": "", "target_folder": ""}]
        
        # 폴더 동기화 설정
        "sync_folders": [],             # (구버전 호환용) 단일 동기화 폴더 목록
        "sync_groups": [],              # 다중 동기화 그룹 목록 [{"name": "그룹명", "folders": []}]
        "sync_last_group_index": 0,     # 마지막으로 선택한 그룹 인덱스
        "sync_move_to_deleted": True,   # 이전 버전 파일 to be deleted로 이동 여부
        
        # GitHub 자동 업데이트 설정
        "github_repo": "",              # 예: "owner/repo"
        "github_token": "",             # DPAPI로 암호화되어 저장될 토큰
        "auto_check_update": "on_start", #on_start / weekly / manual
        
        # 포맷 우회 변환 설정
        "bypass_excel_target": ".xlsb",
        "bypass_ppt_target": ".pptm",
        "bypass_word_target": ".docm",
        "bypass_pdf_target": ".zip",
        "bypass_output_mode": "inplace",
        "bypass_source_disposition": "keep",
        # Legacy safety key. It is never used to authorize source replacement;
        # the explicit in-place mode and per-run confirmation are required.
        "bypass_delete_original": False,
        "bypass_preserve_meta": True,
        "last_bypass_source_directory": "",
        "last_bypass_target_directory": "",

        # 통합 실행 및 결과 알림 설정
        "task_schedule_enabled": False,
        "task_schedule_time": "18:00",
        "task_schedule_last_run_date": "",
        "task_schedule_attempt_date": "",
        "task_schedule_attempt_count": 0,
        "task_schedule_last_attempt_at": "",
        "task_schedule_last_started_at": "",
        "task_schedule_last_finished_at": "",
        "task_schedule_last_success_at": "",
        "task_schedule_last_failure_at": "",
        "task_schedule_last_failure_reason": "",
        "task_schedule_allow_source_backup": False,
        "task_step_last_results": {},
        "task_auto_email": True,
        # Run Tasks에서 실제로 실행할 기능. 기존 설정에는 이 키가 없으므로
        # 안전한 기본값인 폴더 동기화만 선택합니다.
        "task_enabled_steps": ["sync"],
        "smtp_server": "",
        "smtp_port": "",
        "sender_email": "",
        "sender_password": "",         # DPAPI로 암호화되어 저장
        "receiver_email": "",
        "mail_subject": "통합 작업 완료 결과 보고서",
        "mail_body_header": "",
        
        # UI 설정
        "ui_language": "auto",       # auto / en / ko / pl
        "last_ocr_image_directory": "",
        "window_size": [1400, 900]
    }
    
    # DPAPI로 자동 암복호화할 보안 키 목록
    SECURE_KEYS = ["github_token", "sender_password"]

    def __init__(self, config_file=CONFIG_FILENAME):
        self.config_file = config_file
        self.lock = threading.Lock()
        
        # The installed application's UserSetting is the sole data store.
        self.app_dir = str(user_data_dir())
        
        try:
            os.makedirs(self.app_dir, exist_ok=True)
        except OSError as exc:
            # Never silently read or write settings in an unrelated working folder.
            raise OSError(
                f"Cannot create the FileOps UserSetting folder: {self.app_dir}. "
                "Check the installation folder's write permissions."
            ) from exc
            
        self.config_path = os.path.join(self.app_dir, self.config_file)
        self.config = self.load_config()

    def load_config(self) -> dict:
        """JSON 파일로부터 설정을 로드하고 기본값과 병합합니다."""
        with self.lock:
            # 리스트/딕셔너리 기본값이 ConfigManager 인스턴스 사이에서 공유되지 않도록 복제합니다.
            config = copy.deepcopy(self.DEFAULT_CONFIG)
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                        if not isinstance(loaded, dict):
                            raise ValueError("Configuration root must be an object.")
                        config.update(loaded)
                        migrated = self._migrate_config(config, loaded)
                    logger.debug(f"Configuration loaded successfully from {self.config_path}")
                    if migrated:
                        self._save_config_raw(config)
                except OSError as exc:
                    # Permission/locking failures do not imply corrupt content.
                    raise OSError("Cannot read FileOps settings. Check permissions and retry.") from exc
                except (json.JSONDecodeError, UnicodeError, ValueError) as e:
                    logger.error(f"Error loading configuration file ({self.config_path}): {e}")
                    # 손상된 설정 파일 백업 및 초기 복원
                    try:
                        bak_path = self.config_path + "." + uuid.uuid4().hex + ".bak"
                        shutil.copy2(self.config_path, bak_path)
                        with open(self.config_path, "rb") as source, open(bak_path, "rb") as backup:
                            if source.read() != backup.read():
                                raise OSError("Corrupt settings backup could not be verified.")
                        logger.info(f"Corrupted config file backed up to {bak_path}")
                    except Exception as backup_err:
                        logger.error(f"Failed to backup corrupted config: {backup_err}")
                        raise OSError("Cannot preserve unreadable FileOps settings. Restore a backup or check permissions.") from backup_err
                    # 기본값 저장
                    config = copy.deepcopy(self.DEFAULT_CONFIG)
                    # The corrupt original has been preserved. Normal writes below
                    # reject invalid existing content rather than replacing it.
                    try:
                        atomic_write_json(self.config_path, config, indent=4)
                    except Exception as save_error:
                        raise OSError("Cannot save recovered FileOps settings. The original and backup were retained.") from save_error
            else:
                logger.info(f"Config file not found. Creating default config at {self.config_path}")
                # 초기 생성
                if not self._save_config_raw(config):
                    raise OSError("Cannot create FileOps settings. Check write permissions and retry.")
            return config

    def _migrate_config(self, config: dict, loaded: dict) -> bool:
        """기존 사용자 설정 파일을 삭제하지 않고 현재 스키마로 보강합니다."""
        migrated = False
        try:
            version = int(loaded.get("config_version", 1) or 1)
        except (TypeError, ValueError):
            version = 1
        if version < 2:
            # v1의 sender_password는 SettingsDialog에서 이미 DPAPI 암호문으로 저장되던 값입니다.
            # ConfigManager 보안 키로 편입하되 값을 다시 암호화하지 않습니다.
            config["config_version"] = 3
            migrated = True
        if version < 3:
            config["config_version"] = 3
            migrated = True
        if "config_version" not in loaded:
            config["config_version"] = 3
            migrated = True
        # Older releases inferred custom output merely from a remembered target
        # path. Preserve that behavior during migration so an update never turns
        # an existing non-destructive workflow into source replacement.
        if loaded.get("bypass_output_mode") not in ("inplace", "custom"):
            config["bypass_output_mode"] = (
                "custom" if str(loaded.get("last_bypass_target_directory", "")).strip() else "inplace"
            )
            migrated = True
        # v1.1.x could permanently delete converted source files and defaulted
        # that action to on. Never carry that ambiguous choice across upgrade;
        # the current replace mode requires an explicit screen choice and run.
        if loaded.get("bypass_delete_original") is not False:
            config["bypass_delete_original"] = False
            migrated = True
        if loaded.get("bypass_source_disposition") not in ("keep", "backup"):
            config["bypass_source_disposition"] = "keep"
            migrated = True
        return migrated

    def save_config(self) -> bool:
        """현재 설정을 스레드 안전하게 JSON 파일로 기록합니다."""
        with self.lock:
            return self._save_config_raw(self.config)

    def _save_config_raw(self, config_dict) -> bool:
        """스레드 락이 취득된 상태에서 임시 파일을 이용해 원자적(Atomic)으로 설정을 기록하는 내부 헬퍼 메소드"""
        try:
            try:
                with open(self.config_path, "r", encoding="utf-8") as stream:
                    existing = json.load(stream)
            except FileNotFoundError:
                pass
            else:
                if not isinstance(existing, dict):
                    raise ValueError("Existing configuration root must be an object.")
            atomic_write_json(self.config_path, config_dict, indent=4)
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration atomically: {e}")
            return False

    def get(self, key, default=None):
        """
        설정 키 값을 가져옵니다.
        보안 키인 경우 자동으로 DPAPI 복호화를 거쳐 평문으로 반환합니다.
        """
        with self.lock:
            val = self.config.get(key, default)
            if key in self.SECURE_KEYS and val:
                try:
                    return decrypt_data(val)
                except Exception as e:
                    logger.error(f"Failed to automatically decrypt secure key '{key}': {e}")
                    return ""
            return val

    def set(self, key, value):
        """
        설정 키 값을 세팅합니다.
        보안 키인 경우 자동으로 DPAPI 암호화를 거쳐 저장합니다.
        """
        with self.lock:
            draft = copy.deepcopy(self.config)
            if key in self.SECURE_KEYS and value:
                try:
                    encrypted_val = encrypt_data(value)
                    draft[key] = encrypted_val
                except Exception as e:
                    logger.error(f"Failed to automatically encrypt secure key '{key}': {e}")
                    # 보안 키는 암호화 실패 시 평문으로 저장하지 않습니다.
                    return False
            else:
                draft[key] = value
            
            # 설정 값 변경 시 세이브 자동 유도 가능하도록 구성
            # 실시간 안전 저장을 위해 즉시 save 호출
            if not self._save_config_raw(draft):
                return False
            self.config = draft
            return True

    def update(self, values: dict) -> bool:
        """Persist several non-sensitive runtime state values atomically."""
        if any(key in self.SECURE_KEYS for key in values):
            raise ValueError("ConfigManager.update does not accept secure keys.")
        with self.lock:
            draft = copy.deepcopy(self.config)
            draft.update(copy.deepcopy(values))
            if not self._save_config_raw(draft):
                return False
            self.config = draft
            return True

    def set_many(self, values: dict) -> bool:
        """Save a complete settings-dialog change, including encrypted credentials."""
        with self.lock:
            draft = copy.deepcopy(self.config)
            for key, value in values.items():
                if key in self.SECURE_KEYS and value:
                    try:
                        value = encrypt_data(value)
                    except Exception:
                        logger.error("Could not encrypt secure setting '%s'.", key)
                        return False
                draft[key] = copy.deepcopy(value)
            if not self._save_config_raw(draft):
                return False
            self.config = draft
            return True
            
    def remove(self, key):
        """설정에서 특정 키를 제거하고 즉시 저장합니다."""
        with self.lock:
            if key in self.config:
                draft = copy.deepcopy(self.config)
                del draft[key]
                if not self._save_config_raw(draft):
                    return False
                self.config = draft
            return True

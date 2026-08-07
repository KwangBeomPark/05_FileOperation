"""Small, dependency-free localization helpers shared by the Qt UI."""

from __future__ import annotations

import ctypes
import locale
import os
from typing import Any


SUPPORTED_LANGUAGES = ("en", "ko", "pl")
WINDOWS_LANGUAGE_IDS = {0x09: "en", 0x12: "ko", 0x15: "pl"}


MESSAGES = {
    "en": {
        "app_title": "FileOps Hub ({version})",
        "ready": "Ready",
        "file_menu": "File",
        "help_menu": "Help",
        "settings": "Settings",
        "exit": "Exit",
        "tray_open": "Open FileOps Hub",
        "tray_exit": "Exit FileOps Hub",
        "tray_tooltip": "FileOps Hub - running in the background",
        "tray_running_title": "FileOps Hub is still running",
        "tray_running_message": "The window was hidden. Scheduled tasks remain active in the notification area.",
        "check_updates": "Check for Updates...",
        "tab_tasks": "Run Tasks",
        "tab_sync": "Sync Folders",
        "tab_eml": "Convert EML",
        "tab_pdf": "Convert PDF",
        "tab_ocr": "Read Images",
        "tab_bypass": "Convert Files",
        "task_title": "Scheduled and Manual Tasks",
        "task_schedule": "Run every day",
        "task_auto_email": "Email the result when finished",
        "task_start": "Run Selected Tasks",
        "task_stop": "Stop Tasks",
        "task_run_header": "Run",
        "task_feature_header": "Feature",
        "task_status_header": "Status",
        "task_selection_hint": "Select only the features that should run manually or on schedule. Unselected features are not validated.",
        "task_step_sync": "Sync Folders",
        "task_step_eml": "Convert EML",
        "task_step_pdf": "Convert PDF",
        "task_step_ocr": "Read Images",
        "task_step_bypass": "Convert Files",
        "task_status_pending": "Waiting",
        "task_status_running": "Running",
        "task_status_completed": "Completed",
        "task_status_partial": "Partially failed",
        "task_status_failed": "Failed",
        "task_status_cancelled": "Cancelled",
        "task_status_skipped": "Not selected",
        "task_progress_format": "Overall progress: %p%",
        "task_waiting": "Waiting...",
        "task_log_title": "Live Task Log",
        "task_scheduled_prefix": "Scheduled run",
        "task_scheduled_start": "Starting the selected tasks at {timestamp}.",
        "task_scheduled_skipped": "The run was skipped because no selected task could be started.",
        "task_validation_title": "Check {feature} settings",
        "task_validation_body": "Feature: {feature}\n\nProblem:\n{problem}\n\nHow to fix:\nOpen the {feature} tab and correct the setting, or clear its Run checkbox on this page if it should not run.",
        "task_validation_unexpected": "The {feature} settings could not be checked.\n\nDetails: {detail}",
        "task_no_selection_title": "Select a task to run",
        "task_no_selection_body": "Select at least one feature in the Run column. Only selected features are checked and scheduled.",
        "task_no_config": "No runnable items are configured for this feature.",
        "sync_group_needs_two_folders": "Sync group '{name}' needs at least two folders.",
        "sync_group_duplicate_folder": "Sync group '{name}' contains the same folder more than once.",
        "sync_group_folder_missing": "A folder in sync group '{name}' does not exist or is not a folder:\n{path}",
        "eml_source_folder_empty": "EML task '{name}' has no source folder.",
        "eml_source_folder_missing": "The source folder for EML task '{name}' does not exist:\n{path}",
        "eml_target_folder_empty": "EML task '{name}' has no output folder.",
        "pdf_output_folder_empty": "No PDF output folder is selected.",
        "pdf_file_missing": "A PDF selected for conversion does not exist:\n{path}",
        "ocr_engine_missing": "No OCR engine is available. Install Tesseract or check the Windows OCR language pack.",
        "ocr_file_missing": "An image selected for OCR does not exist:\n{path}",
        "bypass_source_folder_missing": "The source folder does not exist:\n{path}",
        "bypass_scan_required": "Scan the source folder in Convert Files before running this task.",
        "bypass_target_folder_empty": "No output folder is selected.",
        "bypass_target_folder_missing": "The output folder does not exist:\n{path}",
        "bypass_source_file_missing": "A scanned source file no longer exists:\n{path}",
        "update_available": "A new version is available",
        "download": "Download",
        "view_release": "View release",
        "close_update_notice": "Dismiss this update notice",
        "checking_updates": "Checking for updates...",
        "update_check_finished": "Update check finished.",
        "update_check_failed": "Update check failed",
        "update_check_failed_body": "GitHub release information could not be checked.\nFor a private repository, verify the GitHub repository and access token in Settings.\n\nDetails: {detail}",
        "update_information": "Update information",
        "up_to_date": "You are using the latest version ({version}).",
        "update_available_status": "Version {version} is available",
        "update_banner_body": "You are using {current_version}. Download the latest installer to update.",
        "download_installer": "Download the latest installer.",
        "view_installer": "View the installer on the release page.",
        "update_verification_failed": "Update verification failed",
        "update_verification_failed_body": "Verified installer information was not found. Check the installer on the release page.",
        "downloading_update": "Downloading update...",
        "cancel": "Cancel",
        "update_download": "Update download",
        "downloading_progress": "Downloading... ({downloaded:.1f} MB / {total:.1f} MB)",
        "download_cancelled": "Download cancelled.",
        "download_complete": "Download complete",
        "download_complete_body": "The update installer is ready. Install it now?\n(The application closes automatically when installation starts.)",
        "run_error": "Launch error",
        "download_failed": "Download failed",
        "settings_saved": "Settings saved.",
        "language_changed": "Language updated.",
        "settings_title": "Settings",
        "language_group": "Language",
        "display_language": "Display language:",
        "language_auto": "Automatic (Windows language)",
        "language_en": "English",
        "language_ko": "Korean",
        "language_pl": "Polish",
        "ocr_settings": "OCR Settings",
        "tesseract_path": "Tesseract executable:",
        "optional_tesseract_path": "Optional: C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
        "browse": "Browse",
        "github_settings": "GitHub Auto-Update Settings",
        "github_repository": "GitHub repository:",
        "github_token": "GitHub access token:",
        "update_check": "Check for updates:",
        "on_start": "When FileOps Hub starts",
        "manual": "Manual only",
        "email_settings": "SMTP Email and Notification Settings",
        "conversion_settings": "General Conversion Settings",
        "eml_width": "EML output width (px):",
        "save": "Save",
        "input_error": "Input error",
        "eml_width_error": "EML output width must be a number from 300 to 4000.",
        "github_repo_error": "Enter the GitHub repository as owner/repository.",
        "smtp_port_error": "SMTP port must be a number from 1 to 65535.",
        "sender_email_error": "The sender email address is invalid.",
        "receiver_email_error": "The recipient email address is invalid: {email}",
    },
    "ko": {
        "app_title": "FileOps Hub ({version})",
        "ready": "준비됨",
        "file_menu": "파일",
        "help_menu": "도움말",
        "settings": "설정",
        "exit": "종료",
        "tray_open": "FileOps Hub 열기",
        "tray_exit": "FileOps Hub 종료",
        "tray_tooltip": "FileOps Hub - 백그라운드에서 실행 중",
        "tray_running_title": "FileOps Hub가 계속 실행 중입니다",
        "tray_running_message": "창을 숨겼습니다. 예약 작업은 알림 영역에서 계속 실행됩니다.",
        "check_updates": "업데이트 확인...",
        "tab_tasks": "작업 실행",
        "tab_sync": "폴더 동기화",
        "tab_eml": "EML 변환",
        "tab_pdf": "PDF 변환",
        "tab_ocr": "이미지 읽기",
        "tab_bypass": "파일 변환",
        "task_title": "예약 및 수동 작업 실행",
        "task_schedule": "매일 자동 실행",
        "task_auto_email": "완료 후 결과 이메일 발송",
        "task_start": "선택한 작업 시작",
        "task_stop": "작업 중지",
        "task_run_header": "실행",
        "task_feature_header": "기능",
        "task_status_header": "현재 상태",
        "task_selection_hint": "수동 또는 예약으로 실행할 기능만 선택하세요. 선택하지 않은 기능의 설정은 검사하지 않습니다.",
        "task_step_sync": "폴더 동기화",
        "task_step_eml": "EML 변환",
        "task_step_pdf": "PDF 변환",
        "task_step_ocr": "이미지 읽기",
        "task_step_bypass": "파일 변환",
        "task_status_pending": "대기 중",
        "task_status_running": "진행 중",
        "task_status_completed": "완료",
        "task_status_partial": "일부 실패",
        "task_status_failed": "실패",
        "task_status_cancelled": "취소됨",
        "task_status_skipped": "선택 안 함",
        "task_progress_format": "통합 진행률: %p%",
        "task_waiting": "대기 중...",
        "task_log_title": "실시간 작업 로그",
        "task_scheduled_prefix": "예약 실행",
        "task_scheduled_start": "{timestamp}에 선택한 작업을 시작합니다.",
        "task_scheduled_skipped": "선택한 작업을 시작할 수 없어 오늘 실행을 건너뜁니다.",
        "task_validation_title": "{feature} 설정을 확인해 주세요",
        "task_validation_body": "기능: {feature}\n\n문제:\n{problem}\n\n해결 방법:\n{feature} 탭에서 설정을 바로잡으세요. 이 기능을 실행하지 않을 경우 이 화면의 실행 체크를 해제하세요.",
        "task_validation_unexpected": "{feature} 설정을 검사하지 못했습니다.\n\n상세: {detail}",
        "task_no_selection_title": "실행할 작업을 선택해 주세요",
        "task_no_selection_body": "실행 열에서 기능을 하나 이상 선택하세요. 선택한 기능만 검사하고 예약 실행합니다.",
        "task_no_config": "이 기능에 실행 가능한 항목이 설정되어 있지 않습니다.",
        "sync_group_needs_two_folders": "동기화 그룹 '{name}'에는 폴더가 최소 2개 필요합니다.",
        "sync_group_duplicate_folder": "동기화 그룹 '{name}'에 같은 폴더가 중복 등록되어 있습니다.",
        "sync_group_folder_missing": "동기화 그룹 '{name}'의 폴더가 존재하지 않거나 폴더가 아닙니다:\n{path}",
        "eml_source_folder_empty": "EML 작업 '{name}'의 원본 폴더가 비어 있습니다.",
        "eml_source_folder_missing": "EML 작업 '{name}'의 원본 폴더가 존재하지 않습니다:\n{path}",
        "eml_target_folder_empty": "EML 작업 '{name}'의 저장 폴더가 비어 있습니다.",
        "pdf_output_folder_empty": "PDF 저장 폴더가 지정되지 않았습니다.",
        "pdf_file_missing": "변환할 PDF 파일이 존재하지 않습니다:\n{path}",
        "ocr_engine_missing": "사용 가능한 OCR 엔진이 없습니다. Tesseract 또는 Windows OCR 언어팩을 확인하세요.",
        "ocr_file_missing": "분석할 이미지 파일이 존재하지 않습니다:\n{path}",
        "bypass_source_folder_missing": "원본 폴더가 존재하지 않습니다:\n{path}",
        "bypass_scan_required": "파일 변환 탭에서 먼저 원본 폴더를 스캔하세요.",
        "bypass_target_folder_empty": "저장 폴더가 지정되지 않았습니다.",
        "bypass_target_folder_missing": "저장 폴더가 존재하지 않습니다:\n{path}",
        "bypass_source_file_missing": "스캔한 원본 파일이 더 이상 존재하지 않습니다:\n{path}",
        "update_available": "새 버전 사용 가능",
        "download": "다운로드",
        "view_release": "릴리스 보기",
        "close_update_notice": "이번 업데이트 알림 닫기",
        "checking_updates": "업데이트를 확인하는 중...",
        "update_check_finished": "업데이트 확인이 완료되었습니다.",
        "update_check_failed": "업데이트 확인 실패",
        "update_check_failed_body": "GitHub 릴리스 정보를 확인하지 못했습니다.\n비공개 저장소라면 설정에서 GitHub 저장소와 액세스 토큰을 확인해 주세요.\n\n상세: {detail}",
        "update_information": "업데이트 정보",
        "up_to_date": "현재 최신 버전({version})을 사용하고 있습니다.",
        "update_available_status": "새 버전 {version}을 사용할 수 있습니다",
        "update_banner_body": "현재 {current_version}을 사용 중입니다. 최신 설치 파일을 내려받아 업데이트할 수 있습니다.",
        "download_installer": "최신 설치 파일을 다운로드합니다.",
        "view_installer": "릴리스 페이지에서 설치 파일을 확인합니다.",
        "update_verification_failed": "업데이트 검증 실패",
        "update_verification_failed_body": "검증된 설치 파일 정보를 찾을 수 없습니다. 릴리스 페이지에서 설치 파일을 확인해 주세요.",
        "downloading_update": "업데이트를 다운로드하는 중...",
        "cancel": "취소",
        "update_download": "업데이트 다운로드",
        "downloading_progress": "다운로드 중... ({downloaded:.1f} MB / {total:.1f} MB)",
        "download_cancelled": "다운로드를 취소했습니다.",
        "download_complete": "다운로드 완료",
        "download_complete_body": "업데이트 설치 파일 다운로드가 완료되었습니다. 지금 설치하시겠습니까?\n(설치가 시작되면 프로그램이 자동으로 종료됩니다.)",
        "run_error": "실행 오류",
        "download_failed": "다운로드 실패",
        "settings_saved": "설정을 저장했습니다.",
        "language_changed": "언어를 변경했습니다.",
        "settings_title": "설정",
        "language_group": "언어",
        "display_language": "표시 언어:",
        "language_auto": "자동 (Windows 언어)",
        "language_en": "영어",
        "language_ko": "한국어",
        "language_pl": "폴란드어",
        "ocr_settings": "OCR 설정",
        "tesseract_path": "Tesseract 실행 파일:",
        "optional_tesseract_path": "선택 사항: C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
        "browse": "찾기",
        "github_settings": "GitHub 자동 업데이트 설정",
        "github_repository": "GitHub 저장소:",
        "github_token": "GitHub 액세스 토큰:",
        "update_check": "업데이트 확인:",
        "on_start": "FileOps Hub 시작 시",
        "manual": "수동 확인",
        "email_settings": "SMTP 이메일 및 알림 설정",
        "conversion_settings": "일반 변환 설정",
        "eml_width": "EML 출력 폭 (px):",
        "save": "저장",
        "input_error": "입력 오류",
        "eml_width_error": "EML 출력 폭은 300~4000 사이의 숫자여야 합니다.",
        "github_repo_error": "GitHub 저장소를 owner/repository 형식으로 입력해 주세요.",
        "smtp_port_error": "SMTP 포트는 1~65535 사이의 숫자여야 합니다.",
        "sender_email_error": "발신자 이메일 주소 형식이 올바르지 않습니다.",
        "receiver_email_error": "수신자 이메일 주소 형식이 올바르지 않습니다: {email}",
    },
    "pl": {
        "app_title": "FileOps Hub ({version})",
        "ready": "Gotowe",
        "file_menu": "Plik",
        "help_menu": "Pomoc",
        "settings": "Ustawienia",
        "exit": "Zamknij",
        "tray_open": "Otwórz FileOps Hub",
        "tray_exit": "Zakończ FileOps Hub",
        "tray_tooltip": "FileOps Hub - działa w tle",
        "tray_running_title": "FileOps Hub nadal działa",
        "tray_running_message": "Okno zostało ukryte. Zaplanowane zadania pozostają aktywne w obszarze powiadomień.",
        "check_updates": "Sprawdź aktualizacje...",
        "tab_tasks": "Uruchom zadania",
        "tab_sync": "Synchronizuj foldery",
        "tab_eml": "Konwertuj EML",
        "tab_pdf": "Konwertuj PDF",
        "tab_ocr": "Odczytaj obrazy",
        "tab_bypass": "Konwertuj pliki",
        "task_title": "Zadania zaplanowane i ręczne",
        "task_schedule": "Uruchamiaj codziennie",
        "task_auto_email": "Wyślij wynik e-mailem po zakończeniu",
        "task_start": "Uruchom wybrane zadania",
        "task_stop": "Zatrzymaj zadania",
        "task_run_header": "Uruchom",
        "task_feature_header": "Funkcja",
        "task_status_header": "Stan",
        "task_selection_hint": "Wybierz tylko funkcje uruchamiane ręcznie lub według harmonogramu. Pozostałe ustawienia nie będą sprawdzane.",
        "task_step_sync": "Synchronizuj foldery",
        "task_step_eml": "Konwertuj EML",
        "task_step_pdf": "Konwertuj PDF",
        "task_step_ocr": "Odczytaj obrazy",
        "task_step_bypass": "Konwertuj pliki",
        "task_status_pending": "Oczekiwanie",
        "task_status_running": "Uruchomione",
        "task_status_completed": "Zakończone",
        "task_status_partial": "Częściowe niepowodzenie",
        "task_status_failed": "Niepowodzenie",
        "task_status_cancelled": "Anulowane",
        "task_status_skipped": "Nie wybrano",
        "task_progress_format": "Postęp ogólny: %p%",
        "task_waiting": "Oczekiwanie...",
        "task_log_title": "Dziennik zadań na żywo",
        "task_scheduled_prefix": "Harmonogram",
        "task_scheduled_start": "Uruchamianie wybranych zadań o {timestamp}.",
        "task_scheduled_skipped": "Pominięto wykonanie, ponieważ nie można było uruchomić wybranych zadań.",
        "task_validation_title": "Sprawdź ustawienia: {feature}",
        "task_validation_body": "Funkcja: {feature}\n\nProblem:\n{problem}\n\nJak naprawić:\nPopraw ustawienie na karcie {feature} albo wyłącz pole Uruchom na tej stronie.",
        "task_validation_unexpected": "Nie można sprawdzić ustawień funkcji {feature}.\n\nSzczegóły: {detail}",
        "task_no_selection_title": "Wybierz zadanie",
        "task_no_selection_body": "Wybierz co najmniej jedną funkcję w kolumnie Uruchom. Tylko wybrane funkcje będą sprawdzane i planowane.",
        "task_no_config": "Dla tej funkcji nie skonfigurowano żadnych elementów do uruchomienia.",
        "sync_group_needs_two_folders": "Grupa synchronizacji '{name}' wymaga co najmniej dwóch folderów.",
        "sync_group_duplicate_folder": "Grupa synchronizacji '{name}' zawiera ten sam folder więcej niż raz.",
        "sync_group_folder_missing": "Folder w grupie synchronizacji '{name}' nie istnieje lub nie jest folderem:\n{path}",
        "eml_source_folder_empty": "Zadanie EML '{name}' nie ma folderu źródłowego.",
        "eml_source_folder_missing": "Folder źródłowy zadania EML '{name}' nie istnieje:\n{path}",
        "eml_target_folder_empty": "Zadanie EML '{name}' nie ma folderu docelowego.",
        "pdf_output_folder_empty": "Nie wybrano folderu wyjściowego PDF.",
        "pdf_file_missing": "Wybrany plik PDF nie istnieje:\n{path}",
        "ocr_engine_missing": "Brak dostępnego silnika OCR. Zainstaluj Tesseract lub sprawdź pakiet językowy Windows OCR.",
        "ocr_file_missing": "Wybrany obraz OCR nie istnieje:\n{path}",
        "bypass_source_folder_missing": "Folder źródłowy nie istnieje:\n{path}",
        "bypass_scan_required": "Najpierw przeskanuj folder źródłowy na karcie Konwertuj pliki.",
        "bypass_target_folder_empty": "Nie wybrano folderu wyjściowego.",
        "bypass_target_folder_missing": "Folder wyjściowy nie istnieje:\n{path}",
        "bypass_source_file_missing": "Przeskanowany plik źródłowy już nie istnieje:\n{path}",
        "update_available": "Dostępna jest nowa wersja",
        "download": "Pobierz",
        "view_release": "Zobacz wydanie",
        "close_update_notice": "Zamknij to powiadomienie o aktualizacji",
        "checking_updates": "Sprawdzanie aktualizacji...",
        "update_check_finished": "Sprawdzanie aktualizacji zakończone.",
        "update_check_failed": "Nie udało się sprawdzić aktualizacji",
        "update_check_failed_body": "Nie można sprawdzić informacji o wydaniu GitHub.\nDla prywatnego repozytorium sprawdź repozytorium GitHub i token dostępu w Ustawieniach.\n\nSzczegóły: {detail}",
        "update_information": "Informacje o aktualizacji",
        "up_to_date": "Używasz najnowszej wersji ({version}).",
        "update_available_status": "Dostępna jest wersja {version}",
        "update_banner_body": "Używasz wersji {current_version}. Pobierz najnowszy instalator, aby zaktualizować program.",
        "download_installer": "Pobierz najnowszy instalator.",
        "view_installer": "Zobacz instalator na stronie wydania.",
        "update_verification_failed": "Weryfikacja aktualizacji nie powiodła się",
        "update_verification_failed_body": "Nie znaleziono zweryfikowanych informacji o instalatorze. Sprawdź instalator na stronie wydania.",
        "downloading_update": "Pobieranie aktualizacji...",
        "cancel": "Anuluj",
        "update_download": "Pobieranie aktualizacji",
        "downloading_progress": "Pobieranie... ({downloaded:.1f} MB / {total:.1f} MB)",
        "download_cancelled": "Pobieranie anulowane.",
        "download_complete": "Pobieranie zakończone",
        "download_complete_body": "Instalator aktualizacji jest gotowy. Zainstalować go teraz?\n(Aplikacja zamknie się automatycznie po rozpoczęciu instalacji.)",
        "run_error": "Błąd uruchamiania",
        "download_failed": "Pobieranie nie powiodło się",
        "settings_saved": "Ustawienia zapisane.",
        "language_changed": "Język został zmieniony.",
        "settings_title": "Ustawienia",
        "language_group": "Język",
        "display_language": "Język wyświetlania:",
        "language_auto": "Automatycznie (język systemu Windows)",
        "language_en": "Angielski",
        "language_ko": "Koreański",
        "language_pl": "Polski",
        "ocr_settings": "Ustawienia OCR",
        "tesseract_path": "Plik wykonywalny Tesseract:",
        "optional_tesseract_path": "Opcjonalnie: C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
        "browse": "Przeglądaj",
        "github_settings": "Ustawienia automatycznej aktualizacji GitHub",
        "github_repository": "Repozytorium GitHub:",
        "github_token": "Token dostepu GitHub:",
        "update_check": "Sprawdzaj aktualizacje:",
        "on_start": "Przy uruchomieniu FileOps Hub",
        "manual": "Tylko recznie",
        "email_settings": "Ustawienia SMTP i powiadomien e-mail",
        "conversion_settings": "Ogólne ustawienia konwersji",
        "eml_width": "Szerokość wyjściowa EML (px):",
        "save": "Zapisz",
        "input_error": "Błąd danych",
        "eml_width_error": "Szerokość wyjściowa EML musi być liczbą od 300 do 4000.",
        "github_repo_error": "Podaj repozytorium GitHub w formacie owner/repository.",
        "smtp_port_error": "Port SMTP musi być liczbą od 1 do 65535.",
        "sender_email_error": "Adres e-mail nadawcy jest nieprawidłowy.",
        "receiver_email_error": "Adres e-mail odbiorcy jest nieprawidłowy: {email}",
    },
}


STATIC_TEXT = {
    "통합 태스크 실행 센터": {"en": "Task Center", "ko": "통합 작업 실행", "pl": "Centrum zadań"},
    "일괄 작업 시작": {"en": "Start All Tasks", "ko": "일괄 작업 시작", "pl": "Uruchom wszystkie zadania"},
    "작업 중지": {"en": "Stop Tasks", "ko": "작업 중지", "pl": "Zatrzymaj zadania"},
    "실시간 작업 로그": {"en": "Live Task Log", "ko": "실시간 작업 로그", "pl": "Dziennik zadań na żywo"},
    "대기 중...": {"en": "Waiting...", "ko": "대기 중...", "pl": "Oczekiwanie..."},
    "Sync Groups (동기화 그룹 관리)": {"en": "Sync Groups", "ko": "동기화 그룹", "pl": "Grupy synchronizacji"},
    "Synchronizing Directories (선택된 그룹의 폴더)": {"en": "Folders to Synchronize", "ko": "동기화할 폴더", "pl": "Foldery do synchronizacji"},
    "Sync Control Panel": {"en": "Sync Controls", "ko": "동기화 제어", "pl": "Sterowanie synchronizacją"},
    "Dry Run Sync Plan (전체 작업 계획 리스트)": {"en": "Sync Preview", "ko": "동기화 미리보기", "pl": "Podgląd synchronizacji"},
    "새 그룹 추가": {"en": "Add Group", "ko": "새 그룹 추가", "pl": "Dodaj grupę"},
    "이름 변경": {"en": "Rename", "ko": "이름 변경", "pl": "Zmień nazwę"},
    "그룹 삭제": {"en": "Delete Group", "ko": "그룹 삭제", "pl": "Usuń grupę"},
    "선택된 그룹:": {"en": "Selected group:", "ko": "선택된 그룹:", "pl": "Wybrana grupa:"},
    "등록 폴더: 0개": {"en": "Folders: 0", "ko": "등록 폴더: 0개", "pl": "Foldery: 0"},
    "폴더 추가": {"en": "Add Folder", "ko": "폴더 추가", "pl": "Dodaj folder"},
    "폴더 제거": {"en": "Remove Folder", "ko": "폴더 제거", "pl": "Usuń folder"},
    "현재 그룹 초기화": {"en": "Clear Group", "ko": "현재 그룹 초기화", "pl": "Wyczyść grupę"},
    "1. 전체 동기화 분석 (Dry Run)": {"en": "1. Preview Sync", "ko": "1. 동기화 미리보기", "pl": "1. Podgląd synchronizacji"},
    "2. 전체 일괄 동기화 (Sync ALL)": {"en": "2. Synchronize All", "ko": "2. 전체 동기화", "pl": "2. Synchronizuj wszystko"},
    "분석 전": {"en": "Not analyzed", "ko": "분석 전", "pl": "Nie przeanalizowano"},
    "EML 변환 배치 태스크 관리": {"en": "EML Batch Tasks", "ko": "EML 일괄 변환 작업", "pl": "Wsadowe zadania EML"},
    "태스크 추가": {"en": "Add Task", "ko": "작업 추가", "pl": "Dodaj zadanie"},
    "태스크 수정": {"en": "Edit Task", "ko": "작업 수정", "pl": "Edytuj zadanie"},
    "태스크 삭제": {"en": "Delete Task", "ko": "작업 삭제", "pl": "Usuń zadanie"},
    "일괄 변환 시작": {"en": "Start Batch Conversion", "ko": "일괄 변환 시작", "pl": "Rozpocznij konwersję wsadową"},
    "대기 중": {"en": "Waiting", "ko": "대기 중", "pl": "Oczekiwanie"},
    "상세 진행 로그": {"en": "Detailed Progress Log", "ko": "상세 진행 로그", "pl": "Szczegółowy dziennik postępu"},
    "PDF Input Files": {"en": "PDF Input Files", "ko": "PDF 입력 파일", "pl": "Pliki PDF"},
    "선택된 PDF: 0개": {"en": "Selected PDFs: 0", "ko": "선택된 PDF: 0개", "pl": "Wybrane PDF: 0"},
    "PDF 추가": {"en": "Add PDFs", "ko": "PDF 추가", "pl": "Dodaj PDF"},
    "목록 비우기": {"en": "Clear List", "ko": "목록 비우기", "pl": "Wyczysc liste"},
    "출력 폴더": {"en": "Output Folder", "ko": "출력 폴더", "pl": "Folder wyjsciowy"},
    "Conversion Results": {"en": "Conversion Results", "ko": "변환 결과", "pl": "Wyniki konwersji"},
    "생성 이미지: 0개": {"en": "Created Images: 0", "ko": "생성 이미지: 0개", "pl": "Utworzone obrazy: 0"},
    "변환 시작": {"en": "Start Conversion", "ko": "변환 시작", "pl": "Rozpocznij konwersje"},
    "중지": {"en": "Stop", "ko": "중지", "pl": "Zatrzymaj"},
    "Target Image Files": {"en": "Image Files", "ko": "이미지 파일", "pl": "Pliki obrazów"},
    "불러온 이미지: 0개 (선택됨: 0개)": {"en": "Images: 0 (selected: 0)", "ko": "불러온 이미지: 0개 (선택됨: 0개)", "pl": "Obrazy: 0 (wybrane: 0)"},
    "전체 선택": {"en": "Select All", "ko": "전체 선택", "pl": "Wybierz wszystkie"},
    "전체 해제": {"en": "Clear Selection", "ko": "전체 해제", "pl": "Wyczyść wybór"},
    "이미지 파일 추가": {"en": "Add Images", "ko": "이미지 파일 추가", "pl": "Dodaj obrazy"},
    "OCR & Rename Logs": {"en": "OCR and Rename Log", "ko": "OCR 및 이름 변경 로그", "pl": "Dziennik OCR i zmiany nazw"},
    "OCR 및 이름 변경 시작": {"en": "Start OCR and Rename", "ko": "OCR 및 이름 변경 시작", "pl": "Rozpocznij OCR i zmiane nazw"},
    "Directory Configuration": {"en": "Folder Setup", "ko": "폴더 설정", "pl": "Konfiguracja folderów"},
    "Source Folder:": {"en": "Source folder:", "ko": "원본 폴더:", "pl": "Folder źródłowy:"},
    "Target Folder:": {"en": "Target folder:", "ko": "대상 폴더:", "pl": "Folder docelowy:"},
    "드래그 앤 드롭 또는 우측 버튼으로 폴더를 선택하세요.": {"en": "Drag a folder here or choose one with the button.", "ko": "폴더를 끌어 놓거나 오른쪽 버튼으로 선택하세요.", "pl": "Przeciągnij folder tutaj lub wybierz go przyciskiem."},
    "저장할 우회 폴더를 선택하세요.": {"en": "Choose the folder where converted files are saved.", "ko": "변환 파일을 저장할 폴더를 선택하세요.", "pl": "Wybierz folder zapisu przekonwertowanych plików."},
    "폴더 선택": {"en": "Choose Folder", "ko": "폴더 선택", "pl": "Wybierz folder"},
    "Bypass Rules Mapping & Options": {"en": "File Conversion Rules", "ko": "파일 변환 규칙", "pl": "Reguły konwersji plików"},
    "Target Scan Files (Simulation)": {"en": "Files to Convert", "ko": "변환할 파일", "pl": "Pliki do konwersji"},
    "검색된 대상 파일: 0개": {"en": "Files found: 0", "ko": "검색된 대상 파일: 0개", "pl": "Znalezione pliki: 0"},
    "대상 파일 스캔": {"en": "Scan Files", "ko": "대상 파일 스캔", "pl": "Skanuj pliki"},
    "우회 변환 시작": {"en": "Start File Conversion", "ko": "파일 변환 시작", "pl": "Rozpocznij konwersję plików"},
    "Detailed Activity Log": {"en": "Activity Log", "ko": "작업 로그", "pl": "Dziennik aktywności"},
}


def normalize_language(value: str | None) -> str | None:
    """Return a supported language code for a locale-like value."""
    if not value:
        return None
    normalized = value.replace("_", "-").lower()
    for language in SUPPORTED_LANGUAGES:
        if normalized == language or normalized.startswith(f"{language}-"):
            return language
    return None


def detect_system_language(ui_language_id: int | None = None, locale_name: str | None = None) -> str:
    """Detect a supported Windows UI language and use English for every other case."""
    if ui_language_id is None and os.name == "nt":
        try:
            ui_language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        except Exception:
            ui_language_id = None
    language = WINDOWS_LANGUAGE_IDS.get((ui_language_id or 0) & 0x03FF)
    if language:
        return language
    if locale_name is None:
        try:
            locale_name = locale.getlocale()[0]
        except Exception:
            locale_name = None
    return normalize_language(locale_name) or "en"


def get_app_language(config_manager: Any) -> str:
    """Resolve the persisted choice, keeping automatic detection as the default."""
    saved_language = config_manager.get("ui_language", "auto")
    selected = normalize_language(saved_language)
    return selected or detect_system_language()


def tr(key: str, language: str = "en", **values: object) -> str:
    """Look up a UI message with English as the complete fallback catalog."""
    selected = normalize_language(language) or "en"
    template = MESSAGES.get(selected, MESSAGES["en"]).get(key, MESSAGES["en"].get(key, key))
    return template.format(**values)


def localize_static_text(text: str, language: str) -> str:
    """Translate static labels that originate in feature tabs without changing their behavior."""
    entry = STATIC_TEXT.get(text)
    if not entry:
        return text
    return entry.get(normalize_language(language) or "en", entry["en"])


def localize_widget_tree(root: Any, language: str) -> None:
    """Translate known static Qt labels while preserving each widget's original source text."""
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QTabWidget, QTableWidget
    from PyQt6.QtCore import Qt

    for widget_type in (QAbstractButton, QLabel):
        for widget in root.findChildren(widget_type):
            source = widget.property("_i18n_source_text")
            if source is None:
                source = widget.text()
                widget.setProperty("_i18n_source_text", source)
            elif widget.text() != widget.property("_i18n_last_text"):
                # A worker updated this label after the initial translation. Keep its live value.
                continue
            translated = localize_static_text(source, language)
            widget.setText(translated)
            widget.setProperty("_i18n_last_text", translated)

    for group_box in root.findChildren(QGroupBox):
        source = group_box.property("_i18n_source_title")
        if source is None:
            source = group_box.title()
            group_box.setProperty("_i18n_source_title", source)
        elif group_box.title() != group_box.property("_i18n_last_title"):
            continue
        translated = localize_static_text(source, language)
        group_box.setTitle(translated)
        group_box.setProperty("_i18n_last_title", translated)

    for line_edit in root.findChildren(QLineEdit):
        source = line_edit.property("_i18n_source_placeholder")
        if source is None:
            source = line_edit.placeholderText()
            line_edit.setProperty("_i18n_source_placeholder", source)
        line_edit.setPlaceholderText(localize_static_text(source, language))

    for combo in root.findChildren(QComboBox):
        for index in range(combo.count()):
            source = combo.itemData(index, int(Qt.ItemDataRole.UserRole) + 1000)
            if source is None:
                source = combo.itemText(index)
                combo.setItemData(index, source, int(Qt.ItemDataRole.UserRole) + 1000)
            combo.setItemText(index, localize_static_text(source, language))

    for table in root.findChildren(QTableWidget):
        for index in range(table.columnCount()):
            header = table.horizontalHeaderItem(index)
            if header is None:
                continue
            source = header.data(int(Qt.ItemDataRole.UserRole) + 1000)
            if source is None:
                source = header.text()
                header.setData(int(Qt.ItemDataRole.UserRole) + 1000, source)
            header.setText(localize_static_text(source, language))

    for tab_widget in root.findChildren(QTabWidget):
        for index in range(tab_widget.count()):
            widget = tab_widget.widget(index)
            source = widget.property("_i18n_source_tab_text")
            if source is None:
                source = tab_widget.tabText(index)
                widget.setProperty("_i18n_source_tab_text", source)
            tab_widget.setTabText(index, localize_static_text(source, language))

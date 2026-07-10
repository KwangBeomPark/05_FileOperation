# AI_CODE_MAP.md - 프로젝트 전용 코드 지도

본 문서는 FileOps Hub(Integrated Data & File Utility)의 목적, 아키텍처 계약, 핵심 모듈, 운영 리스크를 맞춰 보는 기준 문서입니다. 코드 구조가 바뀌면 이 파일도 함께 갱신합니다.

## 1. 목적과 실행 환경

- **목적**: 팀별 업무 자료를 공용 배포 폴더와 연결하고, 정산·검수에 필요한 PDF/EML 이미지화, OCR 리네임, Office 포맷 우회 변환을 한 Windows 데스크톱 앱에서 순차 실행합니다.
- **권한 경계**: 앱은 사용자 권한을 새로 부여하지 않습니다. Windows 네트워크 드라이브, OneDrive, SharePoint, 로컬 폴더의 기존 ACL과 현재 로그인 사용자의 권한 안에서만 동작합니다.
- **현재 경계**: 예약 실행은 앱이 켜져 있을 때만 동작합니다. 폴더 동기화는 등록 폴더의 최상위 파일만 처리하며 하위 폴더 재귀 동기화는 범위 밖입니다.
- **권장 환경**: Windows 10/11, Python 3.13 이상, PyQt6, PyMuPDF, Playwright, pywin32, PyInstaller, Inno Setup.

## 2. 현재 아키텍처

통합 실행 흐름은 PyQt 탭 객체의 raw dict를 직접 실행 엔진에 넘기지 않고, 명시적인 실행 계약을 통해 연결합니다.

```text
각 기능 탭 build_run_config()
        |
        v
src/core/task_contracts.py
        |
        v
RunPlan -> src/core/preflight.py -> src/core/task_runner.py
        |
        v
src/ui/task_worker.py(QThread 어댑터) -> src/ui/task_tab.py 진행 UI/메일/예약
```

- `src/core/task_contracts.py`: `TaskStep`, `StepStatus`, `RunPlan`, `RunReport`, 각 기능별 RunConfig, `TaskValidationError`, `DependencyError`를 정의합니다. 사용자 메시지와 상세 로그 메시지를 분리하는 기준입니다.
- `src/core/task_runner.py`: PyQt에 의존하지 않는 순수 순차 실행 엔진입니다. Sync, EML, PDF, OCR, Bypass 단계를 고정 순서로 실행하고 `RunReport`를 반환합니다.
- `src/ui/task_worker.py`: `TaskRunner`를 감싸는 QThread 어댑터입니다. Qt signal 방출만 담당합니다.
- `src/core/task_engine.py`: 과거 import 호환을 위한 shim입니다. 신규 코드는 `task_runner.py`와 `task_worker.py`를 직접 사용합니다.
- `src/core/preflight.py`: 활성 단계 기준으로 Tesseract, Playwright driver/Chromium, pywin32/Office COM, SMTP 설정을 공통 점검합니다. 차단 이슈와 경고를 구분합니다.
- 각 기능 탭의 `build_run_config()`: UI 상태를 타입이 있는 RunConfig로 변환합니다. `get_task_info()`는 임시 호환 래퍼입니다.

## 3. 주요 파일 역할

- `src/main.py`: QApplication 진입점.
- `src/ui/main_window.py`: 메인 윈도우, 탭 구성, 상단 업데이트 배너, 업데이트 체크 연결.
- `src/ui/task_tab.py`: 통합 실행 선택, 예약 실행, preflight 표시, 진행 상태, 결과 메일/로컬 보고서 저장을 담당합니다.
- `src/ui/sync_tab.py`: 동기화 그룹 UI와 `SyncRunConfig` 생성.
- `src/ui/eml_tab.py`: EML 변환 태스크 UI와 `EmlRunConfig` 생성.
- `src/ui/pdf_tab.py`: PDF 선택 UI와 `PdfRunConfig` 생성.
- `src/ui/ocr_tab.py`: 이미지 선택 UI와 `OcrRunConfig` 생성.
- `src/ui/bypass_tab.py`: 우회 변환 스캔 결과 UI와 `BypassRunConfig` 생성. 통합 실행용 config 생성 시 자동 스캔이나 메시지 박스 side effect를 만들지 않습니다.
- `src/core/sync_manager.py`: 다중 폴더 최신본 분석과 동기화 실행.
- `src/core/eml_converter.py`: EML 파싱, Playwright HTML 렌더링, frozen exe 환경의 driver 호출 방어.
- `src/core/pdf_converter.py`: PDF 페이지 이미지 렌더링.
- `src/core/ocr_processor.py`: Tesseract 우선 OCR, Windows 내장 OCR fallback, 프로모션 번호 추출.
- `src/core/bypass_converter.py`: Office COM 포맷 변환과 PDF zip 우회 변환.
- `src/core/email_sender.py`: ConfigManager에서 복호화된 SMTP 비밀번호를 받아 메일을 발송합니다. 암복호화는 직접 수행하지 않습니다.
- `src/core/updater.py`: GitHub Releases 업데이트 확인과 다운로드 방어.
- `src/utils/config_manager.py`: `%LOCALAPPDATA%\IntegratedDataTool\setting_integrated.json` 설정 로드/저장, 원자적 write, DPAPI 보안 키 처리, `config_version=2` 마이그레이션.
- `src/utils/security.py`: Windows DPAPI 암복호화 래퍼.

## 4. 설정과 보안 계약

- 설정 파일 위치: `%LOCALAPPDATA%\IntegratedDataTool\setting_integrated.json`
- 보안 키: `github_token`, `sender_password`
- 보안 키는 `ConfigManager.SECURE_KEYS`에서만 암복호화합니다. UI와 메일 전송 모듈은 수동 암복호화를 하지 않습니다.
- `config_version=1`의 기존 SMTP 비밀번호 암호문은 다시 암호화하지 않고 그대로 읽히도록 마이그레이션합니다.
- 설정 저장은 임시 파일 기록 후 `os.replace`로 교체해 손상 가능성을 줄입니다.

## 5. 외부 의존성 방어

- OCR: Tesseract가 있으면 우선 사용하고, 없으면 Windows 내장 OCR로 fallback합니다. 둘 다 사용할 수 없으면 OCR 단계가 차단됩니다.
- EML: Playwright Python 패키지와 driver가 필요합니다. 소스 실행 환경에서는 `python -m playwright install chromium`을 사용하고, 패키징된 exe는 bundled driver를 통해 Chromium 준비를 시도합니다.
- Bypass Office 변환: pywin32와 Microsoft Excel/Word/PowerPoint COM 설치 상태에 의존합니다.
- SMTP: 서버, 발신자, 수신자 설정이 없으면 작업은 계속 가능하지만 메일 발송 대신 로컬 보고서가 남을 수 있습니다.
- 설치/런타임 점검은 `tools/diagnose_install.py --check-browser`가 `src/core/preflight.py`를 재사용합니다.

## 6. 테스트와 검증 명령

현재 추적 중인 검증 파일:

- `tools/test_contracts.py`: 실행 계약과 legacy dict 호환성.
- `tools/test_tab_contracts.py`: 탭 `build_run_config()` 변환과 검증 실패.
- `tools/test_config_security.py`: `github_token`, `sender_password` 보안 키와 v1 마이그레이션.
- `tools/test_preflight.py`: OCR, Playwright/Office, SMTP preflight.
- `tools/test_ocr_processor.py`: Tesseract 실패 시 Windows OCR fallback 검증.
- `tools/test_task_runner.py`: 순수 실행 엔진 성공/부분 실패 report.
- `tools/test_updater.py`: 업데이트 버전 비교, 릴리스 asset 선택, HTTPS/domain 다운로드 방어, 불완전 다운로드 삭제.
- `tools/build_all.py`: compile, pip check, PyInstaller, Inno Setup 빌드.
- `tools/diagnose_install.py`: 설치/런타임 의존성 사전 진단.

표준 검증:

```powershell
python -m compileall -q src tools
python -m unittest discover -s tools -p "test_*.py" -v
python tools/diagnose_install.py --check-browser
python tools/build_all.py
```

## 7. 변경 이력

- 2026-06-21: 팀 자료 배포 허브, 정산 자료 전처리, 예약 실행·결과 통지 중심으로 목적과 운영 경계를 정리했습니다.
- 2026-06-26: 통합 실행 구조를 `task_contracts` + 순수 `task_runner` + UI `task_worker`로 분리했습니다. 각 탭은 `build_run_config()` 계약으로 연결하고, `TaskValidationError`와 공통 preflight로 검증 흐름을 통일했습니다.
- 2026-06-26: `sender_password`를 `ConfigManager.SECURE_KEYS`에 포함하고 SettingsDialog/email_sender의 중복 암복호화를 제거했습니다. 기존 암호화 SMTP 비밀번호를 유지하는 `config_version=2` 마이그레이션을 추가했습니다.
- 2026-06-26: 설치 방어를 위해 `tools/build_all.py`, `tools/diagnose_install.py`, Inno Setup 탐색 경로, Playwright frozen exe driver 호출 방어, 업데이트 다운로드 방어 테스트를 정리했습니다.
- 2026-06-27: Tesseract가 없을 때 Windows 내장 OCR fallback을 사용하도록 보강하고, Fusion 기반 전역 다크 팔레트를 추가했습니다.
- 2026-06-27: 신규 버전이 있으면 메인 화면 상단 배너에 표시하도록 업데이트 UX를 개선하고, 업데이트 확인 실패 상세를 UI와 진단 흐름에서 분리했습니다.

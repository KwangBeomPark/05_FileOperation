# FileOps Hub v1.4.1 (App05_FileOps)

## What changed

- **전사 제품군 명칭 표준화 (Enterprise Suite Naming Alignment)**:
  - 실행 파일 이름을 사내 소프트웨어 제품군 표준 규격에 맞추어 `IntegratedDataTool.exe`에서 `App05_FileOps.exe`로 전면 변경했습니다. (`App01_ClipOCR`, `App04_DataRefinery`, `App06_Stepwise` 등과 명명 체계 일원화)
  - 단일 배포 설치 프로그램 파일명을 `App05_FileOps_v1.4.1.exe`로 표준화했습니다.
  - 기본 설치 경로를 `%LOCALAPPDATA%\Programs\App05_FileOps`로 적용하며, 기존 설치본(`IntegratedDataTool`) 업그레이드 시 이전 경로를 감지하여 유실 없이 덮어씁니다.
  - 기존 설정, 로그, 예약 실행 이력(`%LOCALAPPDATA%\IntegratedDataTool`)은 완벽하게 승계 및 유지됩니다.

- **공식 디지털 코드 서명 적용 (Authenticode Code Signing)**:
  - 빌드 산출물(`App05_FileOps.exe`, `App05_FileOps_v1.4.1.exe`) 전체에 공인 CA 인증서(`CN=Open Source Developer KWANG BEOM PARK`) 기반의 SHA-256 Authenticode 전자 서명을 적용했습니다.
  - RFC 3161 규격의 공인 타임스탬프(DigiCert)를 날인하여 인증서 만료 후에도 영구적으로 서명 유효성이 보증됩니다.
  - Windows Defender SmartScreen 및 신뢰할 수 없는 게시자 경고 없이 안전하게 설치 및 실행 가능합니다.

- **하위 호환 자동 업데이트 및 런처 고도화**:
  - `AutoUpdater` 엔진에서 `v1.4.1` 이상의 `App05_FileOps_v*.exe`와 이전 버전(`IntegratedDataTool_Setup_v*.exe`)을 모두 인식하는 다중 에셋 해석 로직을 적용했습니다.
  - `App05_FileOps.pyw` 런처 및 진단 도구(`diagnose_install.py`)의 경로 탐색기가 신규 및 레거시 설치 위치를 자동으로 동시 탐색하도록 개선했습니다.

## Validation

- 총 187개 단위/통합 자동화 테스트 100% 통과 (`python -m unittest discover -s tools -p "test_*.py"`).
- Python 정적 컴파일(`compileall`), 의존성 무결성(`pip check`), Ruff 규칙(`E9,F,B`) 검사 완료.
- 3개 국어(한국어, 영어, 폴란드어) AST 다국어 리소스 누락/불일치 검증(`tools/test_i18n.py`) 통과.
- `signtool verify /pa /v`를 통한 Authenticode 전자 서명 검증 통과.

## System Requirements

- Windows 10 / 11 (64-bit)
- 관리자 권한 불필요 (사용자 로컬 `%LOCALAPPDATA%` 설치)

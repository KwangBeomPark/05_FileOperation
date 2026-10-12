# FileOps Hub v1.4.5 — App05_FileOps

## 주요 변경 사항

- **인스톨러 다국어 완전 유니코드 적용 및 한글 깨짐 원천 해결**:
  - `installer/setup.iss`에 `[LangOptions]` (`korean.LanguageCodePage=0`, `polish.LanguageCodePage=0` 및 Segoe UI 폰트)을 공식 명시하여, 비한국어 시스템 로캘(서유럽, 폴란드, 영문 Windows 등)에서도 설치 프로그램 대화상자와 메시지 박스의 한글이 깨지지 않고 선명하게 표시되도록 개선했습니다.
  - `#include` 파일(`legacy_migration.iss`, `legacy_shortcuts.iss`)을 UTF-8 with BOM으로 통일하여 인스톨러 전처리기/컴파일러 인코딩 정합성을 보장했습니다.
- **프로그램 잠김 감지 UX 개선 (영문 Runtime Error 헤더 제거)**:
  - 기존 실행 중인 프로세스나 트레이 아이콘으로 인해 실행 파일 교체가 불가능할 때, 흉측한 영문 `Runtime error (at xx:yy):` 시스템 예외 대신 정갈한 안내 대화상자(`MsgBox`)로 트레이 아이콘 종료를 친절하게 안내하도록 개선했습니다.
- **정상 업그레이드 설치 지원 및 레거시 충돌 방지**:
  - 기존 표준 설치 경로(`%LOCALAPPDATA%\Programs\FileOps\UserSetting`)에 이미 사용자의 최신 설정이 존재하는 경우, 과거 구버전 찌꺼기 폴더(`IntegratedDataTool` 등)가 감지되더라도 충돌 에러로 설치를 중단하지 않고 기존 설정을 온전히 보존한 채 원활하게 업그레이드를 완료하도록 마이그레이션 판정 로직을 보강했습니다.

## 업데이트 시 유의 사항

- 설치 전 실행 중인 FileOps Hub(트레이 아이콘 포함)를 완전히 종료해 주세요.
- 기존 설정, 동기화 그룹, 이력 및 스케줄 데이터는 `%LOCALAPPDATA%\Programs\FileOps\UserSetting`에서 무손실로 안전하게 유지됩니다.

## 배포 아티팩트

- `App05_FileOps_Setup_v1.4.5.exe` (SHA-256 및 Authenticode 디지털 서명)
- `SHA256SUMS.txt`
- `build-manifest.json`

# FileOps Hub v1.4.4 — App05_FileOps

## 주요 변경 사항

- **구버전 설치 환경 마이그레이션 및 방어 체계 통합 (`installer/legacy_migration.iss`)**:
  - 구버전 설치 경로(`App005_FileOps`, `IntegratedDataTool`, `FileOps Hub` 등)에서 신규 표준 경로(`%LOCALAPPDATA%\Programs\FileOps`)로 업그레이드 시 안전한 데이터 이전을 보장합니다.
  - 기존 `UserSetting` 및 레거시 설정 파일(`setting_integrated.json`)을 임시 스테이징 후 SHA-256 해시 검증을 거쳐 마이그레이션합니다.
  - 신규 설치 페이로드 검증이 완전히 완료된 후에만 구버전 정리 및 새 설정을 활성화하며, 심볼릭 링크/재분석 지점(Reparse Point) 및 알 수 없는 파일은 절대 삭제하지 않고 보존합니다.
- **윈도우 시작 시 자동 실행(트레이 모드) 런타임 제어 구축**:
  - 설정 창 및 트레이 메뉴에서 윈도우 부팅 시 자동 시작 여부를 실시간으로 켜고 끌 수 있는 런타임 토글 기능을 지원합니다.
  - 과거 구버전 찌꺼기 바로가기(`.lnk`)를 감지하고 안전하게 정리합니다.
- **설치 및 배포 파이프라인 정규화**:
  - 공식 단일 설치 파일명: `App05_FileOps_Setup_v1.4.4.exe`
  - 배포 무결성 검증을 위한 `SHA256SUMS.txt`, `build-manifest.json` 생성.
  - 엄격한 Authenticode 디지털 서명 및 RFC 3161 타임스탬프 검증 적용.

## 업데이트 시 유의 사항

- v1.4.2 이하 버전에서 업그레이드 시 설치 파일명이 변경되었으므로, GitHub 릴리즈 페이지에서 `App05_FileOps_Setup_v1.4.4.exe`를 직접 다운로드하여 설치하는 것을 권장합니다.
- 기존 설정 및 로그, 스케줄 이력은 마이그레이션 엔진을 통해 자동으로 안전하게 유지됩니다.
- 실행 중인 구버전 프로그램(`App05_FileOps.exe`, `App005_FileOps.exe`, `IntegratedDataTool.exe`, `FileOps.exe`)이 있을 경우 설치 프로그램에서 자동으로 안전하게 종료 안내를 진행합니다.

## 배포 아티팩트 및 품질 게이트

- 배포 아티팩트:
  - `App05_FileOps_Setup_v1.4.4.exe` (SHA-256 서명 및 Authenticode 인증서 서명)
  - `SHA256SUMS.txt`
  - `build-manifest.json`
- 품질 검증:
  - 전체 단위/통합 회귀 테스트 254+개 통과
  - 32개 사용자 데이터 무손실 및 백업 안전성 어설션 통과
  - Inno Setup 컴파일 및 마이그레이션 정적/동적 정책 검증 통과
  - Ruff 린트, pip 의존성 정합성 검사 통과

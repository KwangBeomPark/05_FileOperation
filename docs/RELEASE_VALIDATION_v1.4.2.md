# FileOps Hub v1.4.2 배포 검수 기록

## 범위와 판정

- 검수일: 2026-10-06 (Europe/Warsaw).
- 대상: Windows FileOps Hub, 제품 ID App005_FileOps, 기본 Programs/FileOps 설치 및 UserSetting 데이터 경로.
- 빌드 소스·릴리스 태그 커밋: `5f417c605fe31a30c6fea544627cca0aab8d9c41`.
- 판정: 자동 검증 및 서명·배포 게이트 통과. 아래 수동 검수 범위를 명시한 정식 릴리스로 게시.
- [GitHub v1.4.2](https://github.com/KwangBeomPark/05_FileOperation/releases/tag/v1.4.2): Latest, draft=false, prerelease=false.

## 직접 확인한 증거

| 구분 | 결과 | 검수 경계 |
| --- | --- | --- |
| 소스 검증 | 205개 테스트, compileall, pip check, Ruff E9/F/B 통과 | 실제 Office 설치/변환은 별도 확인 |
| 빌드 기록 | version=1.4.2, 위 소스 커밋, worktree_dirty=false, authenticode_verified=true | 검수 기록만 추가한 후속 문서 커밋은 바이너리를 변경하지 않음 |
| 코드 포함 | 서명된 앱의 49개 모듈·main 및 런처가 현재 소스와 일치 | 바이트코드 대조; 화면에서의 전체 사용자 여정 검수 아님 |
| 아이콘·개인 설정 | 아이콘 두 개는 원본과 동일, 사용자 설정 미포함 | Windows 셸 아이콘 캐시/배율은 별도 확인 |
| 디지털 서명 | 앱·런처·설치파일 모두 Authenticode Valid, 지정 게시자, DigiCert 타임스탬프 | SimplySign 인증은 사용자가 직접 수행 |
| SignTool | 세 파일 모두 verify /pa /all /v 성공, 경고 0·오류 0 | 다른 PC의 조직 정책·SmartScreen 경고 제거를 보장하지 않음 |
| GitHub | 메인·v1.4.2 태그 푸시, 정식 Latest 게시, 네 업로드 파일의 크기·SHA-256 일치 | 게시 후 API로 재확인 |
| 다운로드 선택 | 현재 updater·launcher가 공개된 정식 설치파일과 올바른 digest를 선택 | 다운로드/설치 실행은 수행하지 않음; 구버전 바이너리의 실제 업데이트 실행 검수 아님 |

## 서명 파일 SHA-256

| 파일 | SHA-256 |
| --- | --- |
| App005_FileOps.exe (설치 패키지 내부 앱) | `1427B764B315D3FBADED473CE0A8AD815488E7029927D4DF12FD7262B6356BAB` |
| App005_FileOps_Setup_v1.4.2.exe | `4969E5EC3C1C1129F101BEAF0C8FC18B72B241C1BE582B9E2170AAF912459161` |
| App005_FileOps_Launcher_v1.4.2.exe | `047D373D2F8A4273A7EB64DF318EB876B6AA74D1E3C10503187520A83B40345F` |

공개 파일은 설치파일·선택적 런처·SHA256SUMS.txt·build-manifest.json입니다.
서명자는 Open Source Developer KWANG BEOM PARK이며, thumbprint는
`E9C72CF5090840A1805296525D56BE680622A7FD`입니다.

## 발견 사항과 후속 검수

- 확인된 배포 차단 결함은 남아 있지 않습니다. 에이전트 세션의 개인키 접근 실패는
  사용자 직접 서명과 완성 파일의 독립 검증으로 해결했습니다. 인증서·보안 정책을 초기화하지 않았습니다.
- P2 검수 공백: 깨끗한 PC 설치, 기존/사용자 지정 설치 업그레이드, 바로가기·트레이 표시,
  Windows 자동 시작, 제거 후 UserSetting 보존을 별도 Windows 환경에서 확인해야 합니다.
- P2 검수 공백: 실제 Office 변환과 네트워크·OneDrive 경로의 장기 예약 실행은 이 배포 검수에서 수행하지 않았습니다.
- 유지할 방어: 새 설정의 예약 비활성 기본값, 구버전 실행 파일 탐색, 원자적 설정·이력 기록,
  쓰기 권한 오류 시 임의 우회 저장 금지, 서명 검증 실패 시 배포 성공 기록 생성 금지.
- 후속 순서: 설치·업그레이드 사용자 여정 확인 → 실제 Office/예약 실행 확인 → 남은 UX·호환성 마찰 개선.

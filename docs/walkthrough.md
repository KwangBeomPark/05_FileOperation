# FileOps Hub 범용화(Generalization) 완성 가이드 & 변경 내역서 (walkthrough.md)

> 아래 과거 기록의 이름·경로·검증 수는 당시 버전 기준입니다. 현재 규칙은
> [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md), 설치·데이터 경로는 README를 참조하세요.

## 2026-10-25: 상위 탭 4개와 SA Team 하위 탭

- 상위 탭 순서를 작업 실행 / 폴더 동기화 / 파일 변환 / SA Team으로 변경했습니다.
  EML 변환 / PDF 변환 / 이미지 읽기는 SA Team 안의 하위 탭으로 옮겼습니다.
  요청의 'DFF'는 기존 PDF 변환을 뜻하는 것으로 해석했으며 새 파일 형식을 추가하지 않았습니다.
- 기능 위젯은 기존 객체를 그대로 사용합니다. 상위 창 참조, 설정 키, 예약 선택과 처리 순서는 유지합니다.
  `select_feature_tab()`은 위젯으로 상·하위 화면을 함께 선택하며 진단 복구 이동에도 사용합니다.
- F1과 현재 화면 도움말은 SA Team 안에서 실제 선택한 기능의 매뉴얼을 엽니다.
  언어 변경 시 두 단계의 탭 이름을 함께 갱신하고 현재 선택을 유지합니다. SA Team 이름은 3개 언어에서 같습니다.
  통합 실행 중에는 상위·하위 탭바를 모두 잠그며 기존 개별 기능 잠금도 유지합니다.
- 전용 화면 검사 9개와 매뉴얼/언어/진단 연결 관련 검사 24개가 통과했습니다.
  전체 회귀 349개 OK(기존 미서명 설치 실행 fixture 클래스 한 건 제외), 백업 안전 검사 32개,
  Ruff·compileall·pip check·실제 Inno 컴파일도 통과했습니다.
- 실제 MainWindow를 메모리 설정으로 구성해 한국어 offscreen 렌더를 확인했습니다.
  렌더 중 업데이트·트레이·예약/감시·외부 진단 실행은 막았으며 실제 사용자 설정을 사용하지 않았습니다.
  설치 EXE·Office 변환·실제 예약 작업 실행은 이번 검수에 포함하지 않았습니다.
  버전업·서명·설치·GitHub 푸시·공개는 이번 UI 변경에서 하지 않았습니다.

## 2026-10-22: 실행 전 변경 요약

- 통합 실행과 동기화·EML·PDF·OCR·파일 변환의 수동 실행에 공통 확인창을 연결했습니다.
  복사·변환 입력·이름 변경·백업 이동·영구 삭제·TXT 덮어쓰기와 원본/저장 위치를 표시합니다.
- 기존 sync dry run을 재사용하는 순수 분석 모듈과 UI 모듈을 분리했습니다. 미리보기는 converter를
  실행하거나 작업 대상 폴더를 만들지 않습니다. 분석은 격리 프로세스에서 최대 30초이며 취소할 수 있습니다.
- 위험 항목은 빨간 경고와 매회 새 확인란으로 안내합니다. 변환 후 원본 백업과 휴지통/영구 삭제를 구분하고,
  OCR의 TXT 덮어쓰기도 표시합니다. PDF 이미지 수와 앞 단계 결과 기반 OCR 건수는 확정값으로 만들지 않습니다.
- 확인 후 전체 메타데이터를 재분석하며 달라졌으면 시작하지 않습니다. 내용 해시·파일 잠금·실행 계획 고정과는
  다릅니다. 여러 그룹/단계가 순차 실행되면서 후속 작업이 달라질 수 있다는 예상값 한계도 창에 표시합니다.
- 예약은 팝업 없이 집계·정책을 로그에 남깁니다. 요약 실패는 '변경 없음'으로 보이지 않게 기록하고 기존
  예약 사전점검/동의 기준으로 계속합니다. 수동 확인 중에는 예약 시작 시도 횟수를 소모하지 않습니다.
- 340개 회귀 검사 OK(기존 미서명 설치 실행 fixture 클래스 한 건 제외), 백업 검사 32개, Ruff·compileall·pip check,
  실제 Inno 컴파일이 통과했습니다. 전용 검사 40개는 원본 쓰기 금지·집계·취소·동의·변경 감지·6개 수동 진입점·
  승인 후 워커 시작·분석 시간 초과·창 닫기·예약 무팝업/횟수 보존을 포함합니다.
- 실제 Qt 확인창을 예시 데이터로 한국어·영어·폴란드어 offscreen 렌더해 확인했습니다. 렌더 도구는
  offscreen 폰트 열거 한계 때문에 설치된 Windows 폰트를 읽어서 사용하며 시스템 폰트/보안 정책은 바꾸지 않습니다.
- 실제 Office 작업·대규모 공유 폴더 성능·설치 EXE의 frozen 프로세스 동작은 이번 검수에서 실행하지 않았습니다.
  버전·서명·설치본·GitHub 공개는 변경하지 않았습니다. 사용자 안내는 [RUN_CHANGE_SUMMARY.md](RUN_CHANGE_SUMMARY.md)입니다.
- 추가 제안: OCR TXT의 고유 이름/백업 저장, 실행 계획 고정은 다음 단계에서 별도로 판단합니다.
  이번에는 기존 처리 정책을 바꾸지 않고 위험을 먼저 보이도록 했습니다.

## 2026-10-12: 예전 설치 정리와 설정 이전 (다음 설치 파일)

- 기본 설치 위치를 Programs/FileOps로 제시하고 예전 설치 등록 위치를 그대로 재사용하지 않도록 바꿨습니다.
- 중앙 호환 목록에 있는 예전 폴더를 탐색해 UserSetting만 복사합니다. v1.3의
  setting_integrated.json은 UserSetting/settings.json으로 이름을 바꾸며 암호화 값을 포함한 바이트를 유지합니다.
- 새 설정 충돌·복수 구형 폴더·폴더 연결·잠금·공간 부족은 원본을 지우지 않는 실패로 처리합니다.
  임시 사본 SHA-256 및 새 EXE 해시 확인 후 활성화하고, 내용이 그대로인 구형 프로그램/설정만 정리합니다.
  알 수 없는 파일은 남기고 빈 폴더만 제거합니다. 예전 제거 프로그램을 실행하지 않습니다.
- 이전 중에는 예전 바로가기도 사전 삭제하지 않으며 성공 후 실제로 구형 EXE를 가리키는 링크만 정리합니다.
- 설치 스크립트를 UTF-8 BOM으로 저장하고 한국어·영어·폴란드어 언어별 메시지를 추가했습니다.
  실제 사용자가 본 깨진 메시지의 원인은 화면 자료가 없어 확정하지 않았고 새 화면의 시각 검수도 남아 있습니다.
- 254개 회귀 테스트, 백업 안전 검사 32개, Ruff·컴파일·의존성 검사, 실제 Inno 스크립트 컴파일이 통과했습니다.
  Windows PowerShell의 Get-FileHash 자동 로딩 문제는 OS 기본 Utility 모듈을 명시적으로 불러 해결했습니다.
- 실제 Pascal 코드로 실행하는 시험 시나리오 15개를 추가했으나 Application Control(WinError 4551)이
  미서명 시험 EXE 실행을 차단했습니다. 이 클래스는 건너뛴 것으로 기록하며 실제 이전·삭제 검수를 통과한 것이 아닙니다.
  사용자 설치 폴더는 개발 중 이동/삭제하지 않았습니다. 공개된 v1.4.3과 GitHub 자산도 변경하지 않았습니다.
- 설치 실패·복사 실패·기존 설정 충돌·한글 경로·연결 폴더·잠금·변조 및 제거 후 설정 보존을
  정책 승인/서명된 격리 Windows 환경에서 확인하기 전 새 릴리즈를 배포하지 마세요.
  자세한 복구 계약은 [USER_DATA.md](USER_DATA.md), 남은 단계는 [task.md](task.md)를 확인하세요.

## 2026-10-07: v1.4.3 서명 배포 준비

- 사용자의 서명·푸시 요청에 따라 버전을 v1.4.3으로 올렸습니다. 이전 v1.4.2 공개 파일은 교체하지 않습니다.
- [RELEASE_NOTES_v1.4.3.md](RELEASE_NOTES_v1.4.3.md)에 App05 정규화, 사용자 데이터 보존,
  구형 업데이트 프로그램의 일회 수동 업데이트 및 작업표시줄 다시 고정 안내를 기록했습니다.
- 실제 서명·게시 완료 여부는 docs/task.md의 배포 단계 및 GitHub 릴리즈 검증 결과로 구분합니다.
  인증서가 보이는 것만으로 SimplySign 개인키 접근이나 배포 완료로 간주하지 않습니다.
- v1.4.3에서 229개 회귀 테스트, Ruff, 컴파일·의존성 및 PowerShell 문법 검사를 다시 통과했습니다.
  실제 서명 시도는 SCardSvr 중지/에이전트 세션 관리자 권한 부족으로 빌드 전에 중단되었습니다.
  SimplySign 로그인 상태의 사용자 관리자 PowerShell에서 서명을 실행한 뒤 최종 배포 검증이 필요합니다.

## 2026-10-06: App05 정규화와 표준 배포 파이프라인

- 공식 관리 번호는 05, 제품 ID는 `App05_FileOps`, 실행 파일은 `App05_FileOps.exe`로 수정했습니다.
  구형 이름은 중앙 호환 목록과 과거 기록에서만 유지합니다. Windows 설치/중복 실행 ID는 유지합니다.
- `scripts/build.ps1`, `scripts/sign.ps1`을 표준 진입점으로 추가했습니다. 기존 Python 구현과
  `sign_and_release.ps1` 호출은 호환 래퍼로 유지합니다. 서비스는 필요한 SCardSvr만 시작합니다.
- 모든 빌드는 고유 staging에서 준비합니다. 실제 서명·체크섬·동일 별칭·메타데이터 검증을
  통과한 세트만 release에 옮기고 실패 시 이전 세트를 보존/복원합니다. 공개는 별도 -Publish입니다.
- 과거 로컬 배포 파일 38개, 2,007,781,004바이트를 영구 삭제했습니다. 삭제 전 최신 파일의
  SHA-256·선택 게시자·타임스탬프를 검증했습니다. GitHub 이력과 UserSetting은 건드리지 않았습니다.
- 로컬 release는 최신 v1.4.2의 설치 파일 두 이름과 체크섬/메타데이터 네 파일로 정리했습니다.
  기존 서명 바이트의 **파일명 별칭**이며 내부 앱은 이전 공개본 그대로입니다. 원본 세트는
  tools/_local/published-v1.4.2-*에 보존하고 alias_only=true로 재공개를 차단합니다.
- 새 App05 소스의 실제 빌드 및 Opus 5.5 검수 결과는 [APP05_PIPELINE_VALIDATION.md](APP05_PIPELINE_VALIDATION.md)에 기록했습니다.
  229개 테스트·정적 검사·실제 앱/런처/Inno 빌드·패키지 소스/아이콘 비교가 통과했습니다.
  Opus 5.5는 2회 독립 검수했고, metadata 교체 실패·사용자 지정 폴더 업그레이드·Windows
  PowerShell 검증 경로·개발 빌드 격리 문제를 수정한 뒤 남은 코드 차단 오류를 발견하지 못했습니다.
  신규 설치만 Programs/FileOps 기본값을 쓰고 업그레이드는 기존 폴더/UserSetting을 유지합니다.
  아직 새로운 공개 버전·커밋·서명·설치 수동 검수를 완료한 것으로 간주하지 않습니다.

## 과거 기록: App005 이름·폴더·경로 정리

### v1.4.2 서명 배포 완료

- 버전을 v1.4.2로 올리고 전용 릴리스 노트를 추가했습니다.
- 서명 후 SignTool 전체 서명 검사, Windows Authenticode Valid, 선택한 게시자,
  타임스탬프 인증서까지 필수 검사합니다. 서명 실패 시 성공 메타데이터를 생성하지 않습니다.
- 테스트 사용자 데이터만 별도 프로세스로 격리하고 실제 서명 세션의 환경은 유지합니다.
- 자동 검증은 205개 테스트, 정적 컴파일, 의존성 검사, Ruff 통과입니다.
- 에이전트 세션의 SimplySign 개인키 접근 제한은 사용자가 로그인한 관리자 PowerShell에서
  표준 서명 래퍼를 직접 실행해 해결했습니다. 세 EXE 모두 서명·타임스탬프 재검증을 통과했습니다.
- 소스 커밋 `5f417c6`의 메인·태그를 푸시하고 [v1.4.2](https://github.com/KwangBeomPark/05_FileOperation/releases/tag/v1.4.2)를 최신 정식 릴리스로 공개했습니다.
  네 업로드 파일의 서버 크기·SHA-256이 로컬과 일치하고, 현재 업데이트·런처의 실제 공개
  메타데이터 선택도 확인했습니다. 상세 기록은 [RELEASE_VALIDATION_v1.4.2.md](RELEASE_VALIDATION_v1.4.2.md)에 있습니다.
- 별도 PC 설치·업그레이드·자동 시작·제거 및 실제 Office 변환 수동 검수는 여전히 잔여 범위입니다.

- 관리 번호 005와 제품 ID `App005_FileOps`를 적용했습니다. 화면 이름 `FileOps Hub`는 유지합니다.
- 기본 설치는 `%LOCALAPPDATA%\Programs\FileOps`, 데이터는 그 안의 `UserSetting`에 저장합니다.
  직접 설치 경로를 바꾸면 실행 파일 옆의 `UserSetting`을 사용합니다.
- 이전 `IntegratedDataTool`/`LocalAppData\FileOps` 설정·로그·예약 이력을 가져오지 않고 새 설정으로 시작합니다.
- 구버전 프로그램·설치 파일 감지는 유지하되, 이전 버전 런처를 설치 파일로 오인하지 않도록 수정했습니다.
- 설치 스크립트는 `installer/`, 빌드·서명·런처·스펙은 `scripts/`, 아이콘·설명 이미지는 `assets/`로 정리했습니다.
- 중복 아이콘과 오래된 로컬 레지스트리 명세 사본을 제거했습니다. Git으로 복구할 수 있습니다.
- 루트의 이전 빌드·QA·캐시 폴더는 `tools/_local/cleanup-*`에 보관했습니다. 공식 배포 이력은 유지합니다.
- 서명 스크립트의 버전·인증서·다른 프로젝트 경로 고정을 제거하고 단일 Python 파이프라인으로 통합했습니다.
- 서명 없는 개발 배포물은 `tools/_local/development-release`에, 공식 서명 배포물은 `release/`에 둡니다.
- 빌드 기록에 버전·커밋·미커밋 변경 여부·아티팩트 해시·서명 정보를 기록합니다.
- 설정·로그·대체 결과 보고서의 폴더 생성 실패 시 작업 폴더로 우회 저장하던 처리를 제거했습니다.
- 자동 회귀 검증 201개, Ruff 정적 분석, 의존성 검사, 서명 래퍼 문법 검사를 통과했습니다.
  원본 아이콘의 16px·32px 로딩도 확인했습니다. 이 검사는 실제 Windows 표시 검수를 대체하지 않습니다.
- 앱·런처·설치 프로그램의 개발 빌드를 완료했습니다. EXE 안의 경로 관련 모듈이 최신 소스와
  일치하고, 두 아이콘이 원본과 동일하며, 사용자 설정은 포함되지 않음을 확인했습니다.
  이 산출물은 서명 없는 개발 검증용이며 버전업·GitHub 푸시·공식 릴리스는 수행하지 않았습니다.
- 실제 설치·업그레이드·자동 시작·제거 검수는 격리된 Windows 환경에서 별도로 해야 합니다.

본 문서는 FileOps Hub가 특정 사내 전용 도구에서 **'누구나 범용적으로 사용할 수 있는 파일 및 업무 자동화 스튜디오(General-Purpose FileOps & Workflow Studio)'**로 완전히 탈바꿈한 내역과 사용 가이드를 기술합니다.

## 2026-10-05: v1.4.1 전사 제품군 명칭 통일 및 코드 서명 릴리즈

- 실행 파일명을 사내 제품군 표준 규격에 맞추어 `App05_FileOps.exe`로 전면 변경했습니다. (`App01_ClipOCR`, `App04_DataRefinery`, `App06_Stepwise` 등과 일원화)
- 단일 배포 설치 프로그램 파일명을 `App05_FileOps_v1.4.1.exe`로 표준화했습니다.
- 새 설치의 기본 경로를 `%LOCALAPPDATA%\Programs\App05_FileOps`로 적용하며, 기존 설치본 업데이트 시 등록된 이전 경로를 감지하여 유실 없이 덮어씁니다.
- 공인 CA 인증서(`CN=Open Source Developer KWANG BEOM PARK`) 및 DigiCert RFC 3161 공인 타임스탬프 기반 Authenticode 전자 서명을 실행 파일 및 설치 프로그램 전체에 적용했습니다.
- 자동 업데이트 엔진(`AutoUpdater`)과 런처에서 `v1.4.1+` 신규 명칭(`App05_FileOps_v*.exe`)과 레거시 명칭(`IntegratedDataTool_Setup_v*.exe`)을 모두 지원하도록 하위 호환성을 확보했습니다.
- 단위/통합 테스트 187개 100% 통과, 3개 국어(ko/en/pl) 다국어 AST 검증 통과, Ruff 정적 분석 통과.

---


## 🚀 1. 핵심 개요

Gemini(구현)와 Opus 5.5 / Codex Sol(단계별 교차 검수 및 최종 승인) 파이프라인을 통해 전 4단계 개편이 100% 무결점으로 완료되었습니다.
- **누적 단위/통합 테스트**: 총 **182개 전체 통과** (회귀 결함 0건)
- **다국어 지원(i18n)**: 한국어 / 영어 / 폴란드어 3개 국어 AST 무결성 통과
- **보안 및 안전성**: DPAPI 암호화 및 프리셋 내보내기 시 민감 정보(비밀번호, 토큰, API 키) 원천 배제, 원본 보존/대피 원칙 고수

---

## 🛠️ 2. 단계별 주요 개선 기능 및 사용법

### 1단계: 도메인 종속성 탈피 및 범용 설정 (Phase 1)
- **OCR 범용 규칙 프리셋 및 정규식 엔진**
  - 기존 프로모션 번호 외에도 `송장 번호(Invoice)`, `날짜(YYYY-MM-DD)`, `숫자 시퀀스(Digits)`, `첫 줄 텍스트(First Line)`, `커스텀 정규식(Custom Regex)`, `전문 텍스트 파일 저장(Full Text .txt)` 지원.
- **동적 리네이밍 템플릿**
  - `{date}_{match}_{seq}`, `{match}_{original_name}` 등 템플릿 변수를 지원하여 추출된 텍스트와 원본 파일명을 조합해 자유롭게 파일명을 변경 가능.
- **폴더 동기화 유연성**
  - 제외 패턴(`exclude_patterns`: `*.tmp, ~$*, *.log` 등 와일드카드 필터링).
  - 백업 폴더명 커스터마이징(`archive_folder_name`: 경로 탈출 방지 적용).

### 2단계: 파이프라인 유연화 및 동기화 모드 고도화 (Phase 2)
- **단방향 배포 및 양방향 동기화**
  - `two_way`: 모든 등록 폴더 간 최신본 상호 동기화.
  - `one_way`: 첫 번째 마스터 폴더에서 대상 폴더들로의 일방향 배포(타겟의 임의 수정 덮어쓰기).
- **하위 폴더 재귀 동기화 (`include_subfolders`)**
  - 하위 디렉터리 트리 구조를 그대로 유지하며 재귀적으로 동기화 수행.
- **파이프라인 출력 자동 연계 (Step Chaining)**
  - EML 또는 PDF에서 추출/변환된 이미지를 별도 수동 지정 없이 즉시 다음 단계인 OCR 처리의 입력으로 자동 전달하는 체이닝 옵션(`task_chain_outputs`) 제공.

### 3단계: 차세대 스케줄링, 이벤트 트리거(Watchdog) 및 무인 CLI (Phase 3)
- **유연한 스케줄 엔진 (`evaluate_flexible_schedule`)**
  - 특정 시각 일일 실행(`daily`) 외에 N분 단위 주기 실행(`interval`), 요일 필터(`weekdays`: 월~금 등) 지원.
- **실시간 폴더 감시 트리거 (`FolderWatcher`)**
  - 파일 복사/생성 완료 시까지 대기하는 2중 안전 검증(`is_file_ready`: 파일 크기 안정화 + 읽기 락 해제).
  - 디바운스 쿨다운(`debounce_seconds`) 타이머를 통해 파일 쓰기가 완전히 끝난 후 파이프라인을 자동 구동.
- **CLI 무인 실행 모드 (`--headless-run`)**
  - GUI 윈도우 생성 없이 콘솔에서 즉시 설정된 통합 작업을 실행하고 종료 코드(`0`: 성공, `1`: 실패)를 반환.
  - Windows 작업 스케줄러, 백그라운드 서비스, CI/CD 스크립트에 즉시 연동 가능.
  ```powershell
  python src/main.py --headless-run
  ```

### 4단계: 워크플로우 프리셋 & 멀티 채널 알림 (Phase 4)
- **안전한 워크플로우 프리셋 매니저 (`preset_manager.py`)**
  - 현재 설정된 파이프라인 및 업무 구성을 `workflow_preset.json`으로 내보내고 타인에게 공유 가능.
  - **심층 방어 보안**: `SECURE_KEYS`, 비밀번호, GitHub 토큰, Webhook URL, API 키 등 민감 정보 및 런타임 기록값을 자동 정제하여 누출 위험을 원천 차단.
  - 카테고리별(`sync`, `ocr`, `pdf`, `eml`, `bypass`, `schedule`) 선택 적용 지원.
- **멀티 채널 알림 디스패처 (`notifier.py`)**
  - 기존 SMTP 이메일 외에 **Slack, Microsoft Teams, Discord, Generic JSON Webhook** 지원.
  - 플랫폼별 마크다운/이모지 서식 및 글자 수 제한 자동 방어, 5초 타임아웃 경량화.
  - `설정(SettingsDialog)` 및 `통합 실행(TaskTab)`에서 설정 가능.

---

## 🏆 3. 전문 서브에이전트 검수 이력 및 최종 승인

| 단계 | 검수 에이전트 | 판정 | 주요 평가 요약 |
| :--- | :--- | :---: | :--- |
| **Phase 1** | **Opus 5.5** | **PASS** | 도메인 하드코딩 제거 및 템플릿 리네이밍의 범용성 우수 |
| **Phase 2** | **Opus 5.5** | **PASS** | 단방향/양방향 모드 분리 및 EML/PDF -> OCR 자동 체이닝 완성도 높음 |
| **Phase 3** | **Codex Sol** | **PASS** | 스케줄러 요일/주기 분기 및 FolderWatcher의 2중 락 안정성, 무인 CLI 설계 우수 |
| **Phase 4** | **Opus 5.5** | **PASS** | 프리셋의 정규식 기반 보안 정제(심층 방어) 및 멀티 채널 웹훅 킬러 피쳐 확인 |
| **종합 검수**| **Codex Sol** | **FINAL APPROVAL** | 전체 아키텍처, 시스템 보안, 무인 수명주기, 182개 테스트 무결함 정식 릴리스 승인 |

---

## 🧪 4. 전체 회귀 테스트 검증 결과

```text
Ran 182 tests in 4.428s

OK
```
- 모든 182개 단위/통합 테스트 100% 통과
- `tools/test_generalization_phase1_2.py`: 통과
- `tools/test_generalization_phase3.py`: 통과
- `tools/test_generalization_phase4.py`: 통과
- `tools/test_i18n.py`: 통과 (한국어, 영어, 폴란드어 무결성)


## Suite standardization phase 1 (2026-10-07)

Added the common six-app baseline and current exceptions, linked from README. Kept UserSetting protection and added local environment/private-key exclusions. Tracked private-data paths and known private references passed the source audit. Installer flow was inspected without executing installation; running-app shutdown, old EXE cleanup timing, and failure recovery remain required checks in the next release phase. See [phase 1 review](STANDARDIZATION_PHASE1_REVIEW.md). No App05 runtime or published artifacts were changed.
# Suite standardization phase 2 (2026-10-07)

Obsolete EXEs are retained before the new payload is installed. The installer
captures previous registration/location and file hashes, requests normal closure,
blocks locked executable replacement, and only removes proven unchanged legacy
leaves at successful completion after checking the replacement hash. Central
identity/compatibility lists and UserSetting are preserved. Isolated regression
gates passed 230 tests and actual Inno compilation. See
[phase 2 review](STANDARDIZATION_PHASE2_REVIEW.md) for remaining signed/native checks.

## Suite standardization phases 3–5 (2026-10-08)

Settings now use a unique sibling temporary file and replace the original only after flush, fsync and close. ConfigManager commits memory after disk success. The dialog validates all fields before one secure-key-aware batch save and displays failures without accepting the dialog. Permission errors do not trigger corruption recovery; invalid content is copied to a unique backup before recovery.

The canonical application spec is installer/App05_FileOps.spec. Its scripts/ compatibility entry point resolves identical sources, icon, product identity and version resource. Public roles and backup boundaries are documented in CODE_MAP.md and USER_DATA.md; isolated backup checks run with the build's test gate. See STANDARDIZATION_PHASE3_5_REVIEW.md for regression evidence and native/manual limits. Actual settings, signed release files and publication are untouched.
Final cross-review also blocked writes over externally corrupted running settings, verified corruption-recovery copies, and propagated preset persistence failure to the existing import-error UI. The final isolated regression suite passed 244 tests.


## Single installer preparation — 2026-10-09

Current preparation generates only App05_FileOps_Setup_v<version>.exe and validates a three-file official set with manifest/checksums. Historical installer names remain reader compatibility. Existing user build_all.py changes were retained while checksum generation was aligned with verification. Version 1.4.3 had no local/remote tag or GitHub release at inspection. Current isolated regressions: 250 passed; backup safety: 32 passed; lint/diff checks passed. Signing, native startup/DPAPI/install checks, committing and publication were not performed by this preparation task. See [release checklist](../RELEASE_CHECKLIST.md).

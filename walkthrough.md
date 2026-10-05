# FileOps Hub 범용화(Generalization) 완성 가이드 & 변경 내역서 (walkthrough.md)

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

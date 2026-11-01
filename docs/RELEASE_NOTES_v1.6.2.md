# FileOps Hub v1.6.2 — App05_FileOps

## 주요 신규 기능 및 개선 사항

### 1. 사용자 경험(UX) 및 직관적 넛지(Nudge) 강화
- **양방향 상태 브릿지 (State Bridge)**:
  - 2번 폴더 동기화(`SyncTab`) 및 3번 수집 동기화(`CollectSyncTab`) 탭 상단에 현재 그룹의 1번 `작업 실행` 포함 여부와 예약 상태(`매일 18:00`, `월~금 09:30`, `15분 간격` 등)를 실시간 안내.
  - `[작업 실행 열기]` 원클릭 버튼을 제공하여 1번 탭으로 즉시 점프 지원.
  - 설정 저장 실패(`_save_failed`) 시 경고 표시 및 버튼 숨김으로 안전한 UI 방어.
- **작업 안전성 안내 (Empty State Safety Hint)**:
  - 파일 수집 결과 테이블의 빈 화면에 "미리보기는 파일을 복사하거나 변경하지 않습니다" 안전 멘트를 표출하여 사용자가 안심하고 실행해볼 수 있도록 유도.
  - 실제 파일 복사 실행 시작 시에는 안전 팁을 즉시 소거하여 실행 상태와 메시지 혼동 방지.
- **인라인 실행 이유 안내 (SyncTab Action Reason Hints)**:
  - 기존 툴팁에 숨겨져 있던 비활성화 원인을 버튼 바로 아래 `action_hint_label`로 인라인 표출(1단계 폴더 구성, 2단계 미리보기 실행 힌트 등).
- **작업 실행 탭 더블클릭 힌트**:
  - 1번 통합 작업 상태 테이블 상단에 행 더블클릭 시 해당 작업 상세 설정 탭으로 바로 이동한다는 팁 라벨 제공.

### 2. 다국어(KO, EN, PL) 및 스케줄러 정밀화
- **공통 스케줄 포맷터 일원화 (`format_task_schedule_description`)**:
  - 평일(`월~금` / `Mon-Fri` / `Pn-Pt`), 주말(`토·일` / `Sat-Sun` / `So-Nd`), 개별 요일, 매일, 간격(`15분 간격` / `every 15 min` / `co 15 min`) 모드를 한국어, 영어, 폴란드어로 100% 다국어 지원.
  - 실제 탭 명칭(`Run Tasks` / `작업 실행` / `Uruchom zadania`)과 브릿지/안내문 용어 완전 일치화.
  - 간격 설정 경계값(음수 보정, 0/None fallback 60분)을 실제 실행 엔진(`schedule.py`) 정책과 완벽히 동기화.

### 3. 아키텍처 예외 안전성 & 트랜잭션 격리
- 브릿지 UI 표시 예외가 설정 저장(`save_data()`) 트랜잭션에 영향을 주지 않도록 `_refresh_task_bridge_impl` 내부로 완전 격리.
- 실제 파일 복사 실행 시작 시 미리보기 안전 팁 잔류 차단 및 관련 회귀 테스트 추가.

### 4. 외부 AI 릴레이 교차 감사 완료
- **Claude Opus 5.5 CLI** 및 **OpenAI Codex CLI (`gpt-6.1-sol`)** 양측 수석 아키텍트 전원 최종 승인(Approved) 획득.
- 전체 548개 단위 테스트 100% 통과 (548 passed, 0 failed, 1 skipped).
- `ruff check` 코드 린트 무결점 통과 (`All checks passed!`).

---

## 배포 아티팩트

- `App05_FileOps_Setup_v1.6.2.exe` (SHA-256 및 Authenticode 디지털 서명)
- `SHA256SUMS.txt`
- `build-manifest.json`

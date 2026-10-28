# FileOps Hub v1.6.0 — App05_FileOps

## 주요 신규 기능 및 개선 사항

### 1. 신규 탭: 파일 수집 동기화 (Collect Sync) 📁 탑재
- **다중 소스 폴더 와일드카드 수집**: 여러 개(N개)의 소스 폴더에서 파일명 패턴(예: `*2026*`, `*보고서*.xlsx`, `INV-*.pdf` 등)에 일치하는 파일들을 감지하여 단일 타깃 폴더로 자동 단방향 복사/수집.
- **수집 전용 UI 및 미리보기**: 수집 대상 파일 목록 및 용량 사전 분석, 드라이 런(Dry Run) 미리보기, 단독 실행 및 스케줄러 연동 지원.
- **안전 복구 시스템 (`CollectRecoveryDialog`)**: 복사 중단 또는 예외 발생 시 안전한 롤백 및 복구 기능 탑재.
- **스마트 작업 충돌 방어**: 통합 작업(`TaskTab`) 실행 중이거나 수집 중일 때 상호 간섭이 발생하지 않도록 상호 배타적 잠금 적용.

### 2. 탭 레이아웃 재배치 및 워크플로우 최적화
- **사용자 중심 직관적 탭 순서 개편**:
  - 1번 탭: **통합 작업 (`TaskTab`)** 🚀 (오케스트레이션 / 일괄 실행)
  - 2번 탭: **폴더 동기화 (`SyncTab`)** 🔄 (양방향/단방향 동기화)
  - 3번 탭: **파일 수집 (`CollectSyncTab`)** 📁 (신규: 와일드카드 다중 소스 수집)
  - 4번 탭: **파일 변환 (`BypassTab`)** 🛠️ (DRM 보안 우회 / 오프라인 HTML 뷰어)
  - 5번 탭: **SA Team 전용 (`sa_team_tabs`)** 👥 (문서 파이프라인 서브탭: EML, PDF, OCR)

### 3. 클린 아키텍처 4단계 전면 리팩토링 완료
- **Phase 1: 숨은 버그 및 동작 불일치 교정**:
  - `TaskRunner.cancel()` 시 동기화 엔진(`SyncManager.cancel()`)으로의 취소 전파 일원화.
  - `TaskTab` 계약 수집 체계 단일화 (`_collect_step_configs`) 및 OCR 체이닝 예외 로직 통일.
  - Headless 스케줄러 실행 시 비활성화된 단계 필터링 방어.
  - `ConfigManager.get()` 가변 객체 반환 시 `deepcopy` 방어 복사로 내부 메모리 오염 원천 차단.
- **Phase 2: 코어 비즈니스 로직 분리 & 데드코드 정리**:
  - `BypassTab`에 뒤엉켜 있던 파일 스캔/필터링/타깃 경로 산출/충돌 회피 로직을 순수 코어 `src/core/bypass_planner.py`로 분리 (UI 160줄 슬림화).
  - OCR 규칙 추출 정규식 로직 단일 진실 공급원(SSOT) 일원화 (`_resolve_rule_pattern`).
  - 미사용 `FileManager` 잔재 및 파라미터 완전 제거.
- **Phase 3: 비동기 결과 보고 및 TaskTab 슬림화**:
  - 결과 보고서 이메일(SMTP) 및 웹훅 발송을 `src/core/task_notifier.py`로 분리.
  - `NotificationWorker(QThread)` 도입으로 SMTP 네트워크 지연에 따른 메인 UI 프리징 원천 방지.
- **Phase 4: 다국어(i18n) 안전화 및 최종 클린업**:
  - 레거시 미참조 `file_manager.py` 영구 삭제.
  - 다국어 런타임 치환 로직을 `replace_phrases` 헬퍼로 일원화하고, **긴 문구 우선 매칭(`longest first`)** 알고리즘을 적용하여 복합 문구 번역 깨짐 현상 완벽 해결.

### 4. 사전 진단 및 실행 변경 요약 (Run Summary) 강화
- 실행 전 변경 영향도(생성, 수정, 삭제 파일 수 및 용량)를 모달 다이얼로그로 명확히 사전 확인(`confirm_run_summary`).
- 사전 안전 점검(Preflight) 정책과의 매끄러운 연동.

---

## 배포 아티팩트

- `App05_FileOps_Setup_v1.6.0.exe` (SHA-256 및 Authenticode 디지털 서명)
- `SHA256SUMS.txt`
- `build-manifest.json`

## 품질 검증

- 단위 회귀 테스트 전체 통과 (총 505개: 504 passed, 1 skipped, 실패 0).
- Claude Opus 5.5 CLI 및 Gemini (Argon) 릴레이 교차 감사 및 100% 정밀 검수 완료.

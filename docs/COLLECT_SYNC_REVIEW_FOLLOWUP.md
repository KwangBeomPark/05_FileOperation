# 자동 수집 동기화: Opus 지적 보완 결과

2026-10-27 · `feature/collect-sync` · 사용자 요청으로 SMTP 비밀번호 저장 정책 변경은 제외.

## 이번에 변경한 동작

- 읽지 못하는 하위 폴더/개별 엔트리는 경로별 ERROR로 기록하고 다른 파일 수집을 계속한다.
  소스 루트에 접근할 수 없으면 해당 그룹 오류로 유지한다.
- 타겟 이름 예약에 파일뿐 아니라 디렉터리·링크 등 모든 엔트리와 보관 폴더 이름을 포함한다.
- ‘중단 작업 복구’ 화면을 추가한다. 점검·해시·백업·상태 저장은 QThread에서 처리한다.
- 복구는 원본/타겟 파일을 수정·삭제하지 않는다. 상태 파일만, 검증된 고유 백업 후 원자 저장한다.
- 내용이 같아도 자동으로 소유권을 인정하지 않는다. ‘내 수집 사본으로 연결’에는
  일반 동의 외에 사본 소유권 확인 체크가 별도로 필요하다.
- 파일을 그대로 보존하며 미연결 상태로 풀 수도 있다. 이 경우 다음 수집이 별도 이름의 사본을
  만들 수 있음을 화면과 3개 언어 도움말에 알린다. 원본이 오프라인이면 이 보존 방식만 허용한다.
- 확인 이후 상태/파일이 바뀌면 복구를 막는다. 타겟에 안전하게 접근할 수 없으면 추측하지 않는다.
- 다른 탭의 실제 모달 확인창 중에는 수집 예약을 시작하지 않는다. 시도 횟수를 소비하지 않고
  확인창이 닫힌 다음 예정된 실행을 다시 판단한다.
- 네이티브 워커 시작 실패는 이전 결과 카운트와 예약 시작/종료 이력을 보존한다.
  되돌린 이력을 즉시 저장하며 그 저장마저 실패하면 예약을 차단하고 저장 오류를 표시한다.
- 이전 실행이 running 상태로 남아 재시작한 경우 interrupted로 표시한다. 실제 종료 시각을 만들지 않는다.
- 설치 프로그램 실행이 실패하면 이전 예약 타이머 활성 상태를 되돌린다.

## Opus 5.5 교차검수와 판정

원본: `tools/_local/collect-sync/opus-recovery-review-20261027.jsonl`의 result 이벤트.
실제 모델 `claude-opus-5-5`, CLI exit 0, is_error=false, terminal_reason=completed.
Read/Grep으로 소스/일부 테스트 본문을 읽은 정적 검수이며 앱/테스트/Ruff 실행 검증이 아니다.

| 지적 | 처리 |
|---|---|
| H1 중단 후 복구 경로 부재 | 명시적 사용자 복구와 상태 백업 추가. Opus는 해결로 판정했으며 접근/경쟁의 한계는 별도로 남김 |
| M1 하위 폴더 오류 시 전체 수집 누락 | 폴더/엔트리별 오류 후 계속 처리. 회귀 테스트 추가 |
| M2 폴더 이름과 충돌 반복 | 모든 타겟 엔트리 및 보관 폴더 이름 예약. 반복 실행 검증 |
| M3 다른 탭 모달 중 중복 시작 | 실제 모달 게이트, SyncTab 확인창 재현, 닫힌 뒤 실행 테스트 추가 |
| L1 시작 실패가 과거 결과를 지움 | start_failed는 새 결과로 기록하지 않음. 이전 카운트 보존 검증 |
| L2 설치 실패 후 예약 중단 | 실행 예외 시 이전 타이머 상태 복원. stop_all 거부 시에도 타이머 활성 유지 검증 |
| L3 비정상 종료 후 running 표시 | interrupted 표시, 알려지지 않은 종료 시각은 빈 값 유지 |
| 재검수 P2-1 시작 실패의 디스크 이력 복원 | 직접 `_start(scheduled=True)` 실패 경로에서도 즉시 저장하도록 보완. 저장 실패 시 예약 차단 테스트 |
| 재검수 P2-2 stop_all 거부 시 타이머 중단 | **오탐으로 분리.** 검수자가 stop_all 후반부를 읽지 않았다고 명시함. 이미 wait 실패 시 타이머를 다시 켜는 코드가 있었고, 실제 False 반환을 주입해 타이머 활성/설치 미실행을 확인 |

재검수에서 복구 core의 데이터 파일 미변경, 오래된 지문 차단, 기본 취소, 워커 종료 전 닫기 방지를
확인받았다. 이후 소유권 전용 체크/원본 오프라인 보존/디스크 이력 복원은 Codex 테스트로 추가 검증했다.
이 마지막 소규모 변경까지 Opus가 다시 승인했다고 주장하지 않는다.

## 실제 검증 출력

`tools/_local/collect-sync/review-fixes-full-final.log`:

```text
----------------------------------------------------------------------
Ran 396 tests in 8.860s

OK (skipped=1)
```

skip은 기존 네이티브 설치 fixture다. 실제 Office 처리, 설치 EXE, 장시간 SMB 중단은 실행하지 않았다.
변경한 수집/복구 파일은 전체 Ruff 규칙 검사를 통과했다. 전체 저장소 명령은 여전히 exit 1이다.
`review-fixes-ruff-final.json`과 기준 비교 도구 출력:

```text
Baseline Ruff diagnostics: 324
Current Ruff diagnostics: 198
New diagnostics: 0
PASS: no added diagnostics
```

`git diff --check` 통과. ko/en/pl 실제 위젯을 임시 예제 파일로 렌더링해 검수했다.
렌더링은 복구를 적용하지 않으며 사용자 실제 파일을 수집하지 않는다.

## 변경 파일

- 엔진: `src/core/collect_sync.py`, 신규 `src/core/collect_recovery.py`
- 화면/연결: `src/ui/collect_sync_tab.py`, 신규 `src/ui/collect_recovery_dialog.py`,
  `src/ui/collect_sync_text.py`, `src/ui/main_window.py`
- 누적 검사: `tools/test_collect_sync.py`, `tools/test_collect_sync_ui.py`, 신규
  `tools/test_collect_recovery.py`, `tools/test_collect_recovery_ui.py`, `tools/render_collect_sync_preview.py`
- 문서: 이 파일, `docs/task.md`, `docs/walkthrough.md`, `docs/COLLECT_SYNC_LINT_PLAN.md`,
  `docs/COLLECT_SYNC_VALIDATION.md`

## 남은 한계와 다음 단계

- 전체 Ruff 198건 및 기존 예외/시간 정리는 별도 단계로 남아 있다. SMTP/DPAPI 정책은 변경하지 않았다.
- Opus의 L4 일반 예외의 부분 결과 보고, L5 보관/rollback 경쟁, L6 그룹 간 순환 소스/타겟 경고는
  이번 묶음에서 닫지 않았다. 후속 최소 변경과 실패 주입 검증이 필요하다.
- 복구는 앱 내부 실행 게이트와 해시/메타데이터 재검사를 사용하며 외부 프로세스의 동시 편집까지
  파일시스템 트랜잭션으로 막지는 않는다.
- 네트워크 OS 호출 자체가 멈추면 취소가 지연될 수 있다. 타겟에 접근하지 못하거나 상위 경로가
  링크/정션이면 자동으로 따라가거나 상태를 초기화하지 않고 접근 복구를 요구한다.
- 백업 후 취소하면 안전한 상태 백업이 남을 수 있다. 백업 자동 보관 기간/삭제는 제공하지 않는다.
- 드라이브 문자/UNC 별칭, 이전 버전 보관 기간, 사용자가 직접 넣은 동일 파일 중복 보존의 기존 한계는 유지한다.
- 새 의존성/레지스트리/버전 변경/서명/푸시/태그/릴리스/main 병합은 하지 않았다.

## AI_CODE_MAP.md 후속 반영 (main 파일은 수정하지 않음)

- `collect_recovery.py`: pending 검증, 읽기 전용 점검, 파일·상태 지문, 고유 백업 및 명시적 복구.
- `collect_recovery_dialog.py`: worker 수명/취소, 일반 동의와 사본 소유권 동의 분리.
- 데이터: 기존 UserSetting에 `collect_sync_state.json.recovery-<uuid>.bak` 보존.
- 모달 게이트, interrupted 표시, native start 이력 복원과 새 누적 회귀 파일을 코드 지도에 추가할 것.

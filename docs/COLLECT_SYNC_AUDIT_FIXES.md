# 자동 수집 동기화: 경계 오류 수정 및 Opus 교차검수

2026-10-27 · `feature/collect-sync` · 수정 전 기준 `d434c46`.

## 판정과 작업 경계

합의한 5개 개선 묶음과 검수 후속 F1–F4를 구현하고 회귀 테스트에 누적했다.
최종 Opus 재검수는 새 확정 결함을 찾지 못했다. 이는 오류 부재의 증명이나 릴리스 승인이 아니다.
전체 저장소의 기존 Ruff 198건은 아직 남아 있으므로 전체 정비 완료로 판정하지 않는다.

- 작업 경로: `C:\Dev\GitHub\05_FileOperation_collect_sync`만 수정.
- 원본 `C:\Dev\GitHub\05_FileOperation` 및 그 안의 `AI_CODE_MAP.md`는 읽기 전용.
- SMTP/DPAPI 보안 동작은 제외했다. 공통 JSON 함수의 기존 기본 동작도 유지했다.
- 실제 사용자 설정·원본·타겟·설치 EXE에 실패를 주입하지 않았다. 테스트는 임시 폴더와 격리된 앱 데이터, Qt offscreen을 사용했다.
- 새 의존성·레지스트리·버전 변경·서명·푸시·태그·릴리스·main 병합 없음. 앱 버전은 1.5.0 그대로다.

## 구현한 동작

1. **보관 파일 비덮어쓰기**
   - 보관, 새 사본 배치, 롤백에 배타적 이동을 사용한다.
   - 보관 이름에 경쟁 파일이 생기면 다음 번호를 다시 할당한다(최대 100회).
   - 롤백 위치에도 다른 파일이 생겼다면 덮어쓰지 않고 이전 보관본과 새 타겟을 모두 남기며 오류를 보고한다.
   - 임시 파일의 읽기 전용 속성 복구·정리는 유지한다.
2. **불필요한 전역 차단 예방과 명시적 복구**
   - pending 저장 전에 출력 이름의 UTF-16 255단위 한도, 구분자, 제어 문자, Windows 예약 장치명 등을 검증한다.
   - 잘못되거나 긴 이름은 원본을 변경하거나 임의 축약하지 않고 해당 파일의 ERROR로 표시한다.
   - UNC 공유 루트는 구분자를 포함하지 않는 공유 폴더명 라벨을 사용한다.
   - 실행과 복구가 상위 심볼릭 링크·정션에 같은 정책을 사용한다. 속성 조회 권한 오류를 안전한 경로로 간주하지 않는다.
   - 접근 불가·잘못된 이전 이름 때문에 일반 복구가 막히면 상태만 점검한 별도 화면을 제공한다.
   - 이 화면은 원본/타겟을 열지 않는다. 추가 동의 후, 원본 상태 바이트의 고유 백업을 검증하고 중단 기록만 해제한다.
   - 자동 해제·소유권 추정은 하지 않는다. 일시적 잠금/접근 복구 후에는 ‘다시 확인’으로 일반 파일 점검을 다시 할 수 있다.
3. **순환 그룹 차단**
   - 전체 설정을 기준으로 A→B→A, A→B→C→A와 같은 순환을 막는다.
   - 수동/예약으로 한 그룹만 실행해도 다른 설정 그룹과의 순환을 확인한다.
   - A→B→C처럼 순환하지 않는 연결과 관계없는 정상 그룹은 허용한다.
4. **부분 결과 보존**
   - 예상 밖 예외도 이미 완료한 파일의 결과와 실패한 파일 경로를 전달한다.
   - 불확실한 pending은 그대로 남겨 자동 중복 복사를 막는다.
   - 상태·보고서의 JSON 쓰기 오류를 처리한다. 수집 파일만 ASCII escape 옵션을 사용하며 다른 설정의 기본 UTF-8 동작은 바꾸지 않는다.
   - 복구 전 재시도/상태 손상으로 실행 전에 차단되면 기존 `<id>.json`과 마지막 완료 카운트·시각을 덮어쓰지 않는다.
   - 차단된 시도의 보고서는 `<id>.blocked.json`, 예약 시작·종료·실패 이력은 실제 시도 기준으로 기록한다.
5. **전체 미리보기와 안내**
   - 2,000행은 페이지 크기이며 이후 결과도 이전/다음 페이지로 모두 볼 수 있다.
   - 그룹 변경·편집·새 실행에서 표와 페이지 정보를 함께 초기화한다.
   - 드라이런은 보고서·상태·타겟 파일을 쓰지 않는다. 화면도 이를 명확히 안내한다.
   - ko/en/pl 문구·도움말, 복구 버튼 안내와 추가 동의를 보완했다. 긴 폴란드어 동의 문구는 실제 렌더링 후 축약했다.

## Opus 교차검수와 후속 판정

실제 CLI 반환 모델은 세 번 모두 `claude-opus-5-5`.
모두 exit 0, `subtype=success`, `is_error=false`, `terminal_reason=completed`를 확인했다.
허용 도구는 Read/Glob/Grep뿐이며 소스 수정·테스트/앱 실행은 하지 않았다.
진행 중인 소스 대신 고정된 `tools/_local/collect-sync/fix-checkpoint1/2/3`를 제공했다.

| 회차 | 원문 로그 (tools/_local/collect-sync/) | 판정 및 반영 |
| --- | --- | --- |
| 단계 1/2 | opus-fix-stage12.json | 중대 덮어쓰기/동의 우회는 지적되지 않음. 속성 조회 fail-open, 예약명, 재점검 UX와 메타데이터 경로 테스트를 보완 |
| 전체 수정 | opus-fix-final.jsonl | F1 완료 보고서 덮어쓰기, F2 복구 안내, F3 페이지 초기화, F4 복합 스캔 오류의 다른 그룹 중단을 지적. 모두 수정·회귀 테스트 추가 |
| 후속 재검수 | opus-fix-followup.jsonl | F1/F2/F3 fixed, F4 fixed(같은 그룹 전체 스캔 실패의 가용성 한계는 mitigated), 신규 확정 결함 없음 |

최종 고정 소스 검수 후에는 설명 Docstring, 확인 문구 정확화·축약 및 테스트 단언만 보강했다.
아래 테스트는 Codex의 실제 실행 증거이며 Opus가 실행한 것으로 표현하지 않는다.

## 실제 검증 출력

전체 로그: `tools/_local/collect-sync/fix-full-final.log`.
환경: `QT_QPA_PLATFORM=offscreen`, LOCALAPPDATA/APPDATA는 `tools/_local/collect-sync` 아래 격리 경로.

```text
----------------------------------------------------------------------
Ran 424 tests in 12.332s

OK (skipped=1)
```

기준 396건에서 28개 테스트를 추가했다. 1건은 기존 네이티브 인스톨러 fixture skip이다.
경쟁·실패 주입과 실제 임시 파일 작업을 구분한다. 실제 Windows 정션, 실제 2,001개 파일 드라이런,
실제 QThread/위젯 클릭을 포함하지만 실제 NAS, Office, 설치 EXE의 검증은 아니다.

변경한 소스/테스트/렌더 도구 11개에 대한 Ruff (`fix-changed-ruff.log`):

```text
All checks passed!
```

전체 `python -m ruff check src tools --output-format json`은 여전히 exit 1.
기준 비교 도구 출력:

```text
Baseline Ruff diagnostics: 198
Current Ruff diagnostics: 198
New diagnostics: 0
PASS: no added diagnostics
```

`git diff --check` exit 0. CRLF 전환 안내는 공백 오류로 보고하지 않는다.
단계별 원문은 `fix-stage1.log`(32 OK), `fix-stage2.log`(81 OK), `fix-stage3.log`(77 OK),
`fix-stage4.log`(88 OK), `fix-stage5.log`(53 OK), `fix-opus-followup.log`(120 OK),
`fix-final-review-followup.log`(130 OK), `fix-release-followup.log`(33 OK)에 남겼다.

오프스크린 실제 위젯 렌더:

- `fix-preview-ko.png`, `fix-preview-pl.png`: 두 번째 페이지 포함.
- `fix-recovery-ko.png`, `fix-recovery-en.png`, `fix-recovery-pl.png`: 접근 불가 시 추가 동의/다시 확인.
- 렌더 도구는 반복 실행 가능한 `tools/render_collect_sync_preview.py`로 유지한다.

## 변경 파일 목록

- `src/core/collect_sync.py`: 배타 이동, 이름/경로 검증, 순환 검사, 부분 보고 예외, pending 차단 구분.
- `src/core/collect_recovery.py`: 비접촉 상태 점검 및 명시적 pending 해제.
- `src/ui/collect_recovery_dialog.py`: 추가 동의·다시 확인·상태별 안내.
- `src/ui/collect_sync_tab.py`: 전체 설정 워커 스냅샷, 보고서/완료 이력 보존, 페이지 탐색/초기화.
- `src/ui/collect_sync_text.py`: ko/en/pl UI 및 도움말.
- `src/utils/atomic_write.py`: 기존 기본값을 보존하는 선택적 `ensure_ascii` 인자.
- `tools/test_collect_sync.py`: 경쟁/롤백, 이름/권한/정션, 순환, 복합 스캔 오류, 직렬화 회귀.
- `tools/test_collect_recovery.py`: 손상 매핑 차단, 원본/타겟 비접촉 spy, 명시적 해제의 실패·취소·stale 회귀.
- `tools/test_collect_recovery_ui.py`: 추가 동의, 잠금 후 재점검, 잘못된 이전 이름, 손상 매핑 UI.
- `tools/test_collect_sync_ui.py`: 수동/예약 순환, 부분 결과, 차단 보고서·완료 시각 보존, 전체 페이지/다국어 초기화.
- `tools/render_collect_sync_preview.py`: 페이지/접근 불가 복구 렌더 옵션.
- `docs/task.md`, `docs/walkthrough.md`: 끝에만 이번 단계/결과 추가.
- `docs/COLLECT_SYNC_AUDIT_FIXES.md`: 이 보고서.

## AI_CODE_MAP.md 반영 제안 (수정하지 않음)

- 수집 엔진의 공개 계약과 역할: CollectGroup/CollectReport, 선택적 진행·취소/전체 설정 스냅샷,
  CollectRunError의 부분 보고 및 CollectRecoveryRequired의 실행 전 차단.
- 순환 그룹 정적 검사, 안전한 Windows 출력 이름, 상위 링크 정책과 배타 보관 이동.
- 일반 파일 점검 복구와 비접촉 명시적 중단 기록 해제의 차이, 백업·지문·추가 동의 계약.
- collect_sync_groups, collect_sync_state.json, `<id>.json` 완료/부분 보고서와 `<id>.blocked.json` 최근 차단 시도.
- 독립 최상위 수집 탭/QThread/그룹별 예약, 페이지 미리보기, 별도 3개 언어 카탈로그와 도움말.
- 위 누적 회귀 테스트와 렌더 도구. 새 의존성은 없다.

## 남은 한계와 사용자 결정

- 같은 공유의 Z:와 UNC/IP/호스트명 별칭을 같은 위치로 인식하지 못한다. 매핑뿐 아니라 순환 검사도 같은 표기를 사용해야 한다.
- 보관 기간·개수 정리는 범위 밖이며 자동 삭제를 추가하지 않았다.
- 사용자가 넣은 동일 파일은 안전을 위해 별도 사본으로 남을 수 있다. 명시적 미연결 해제 후에도 마찬가지다.
- 한 그룹의 소스 루트 스캔이 실패하면 그 그룹의 다른 정상 소스 후보도 적용하지 않고 다음 그룹으로 간다. 원본 보존 우선의 기존 그룹 단위 정책이다.
- 복사 예약 뒤 권한이 바뀌고 결과 확인도 실패하면 불확실한 pending으로 안전하게 차단할 수 있다. 자동 해제하지 않는다.
- 일부 NAS에서 조상 속성 조회 권한이 없으면 새 사전검증이 그룹을 차단할 수 있다. 실제 회사 공유에서 확인해야 한다.
- OS/SMB 호출이 막히면 취소는 지연된다. 강제 스레드 종료로 우회하지 않는다.
- `.blocked.json`은 과거 차단 시도의 기록으로 남으며 이후 성공 보고서와 구분해야 한다. 자동 정리하지 않는다.
- 실제 설치/Office/장기간 네트워크 단절/Windows 세션 종료는 미검증. 전체 Ruff 198건은 별도 정리가 필요하다.

이번 합의 범위에서 새 정책 결정을 요구하는 차단 사항은 없다. 위 남은 한계를 바꾸는 구조 변경이나
자동 삭제/자동 상태 해제/별칭 해석은 별도 합의 없이 진행하지 않는다.

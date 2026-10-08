# 공통 정비 3–5단계 검수 (2026-10-08)

## 변경과 보호

- 설정·워크플로우 프리셋 내보내기·실행 이력은 고유 sibling 임시 파일을 완전히 쓰고 flush/fsync/닫은 후 교체합니다. 실패 시 원본에 직접 쓰거나 다른 작성자의 임시 파일을 삭제하지 않습니다.
- ConfigManager는 설정 쓰기/암호화 성공 후 메모리를 반영합니다. `set_many`는 대화상자의 보안 키를 포함한 전체 변경을 한 번에 저장합니다. 입력을 모두 검증한 다음 저장하며 실패하면 창을 유지하고 세 언어 오류를 표시합니다.
- 읽기 권한/잠금 실패를 설정 손상으로 처리하지 않습니다. 손상 콘텐츠는 기존 백업을 덮어쓰지 않는 고유 사본으로 보존한 후 복구합니다. 스키마 버전/변환 선택에 잘못된 타입이 있어도 유효한 다른 사용자 값은 유지합니다.
- 앱 실행 중 설정 파일이 외부에서 손상된 경우에도 모든 정상 저장은 기존 JSON object를 확인하고 실패를 반환해 원본·메모리를 유지합니다. 초기 손상 복구는 고유 사본의 bytes가 원본과 일치한 뒤에만 실행합니다. 프리셋 적용은 update(False)를 성공 개수로 반환하지 않고 기존 화면 오류 경로로 전달합니다.
- 공통 백업은 활성 UserSetting 전체(설정·logs/sync_YYYYMMDD.log·reports·손상 설정 백업)를 포함합니다. 외부 원본·변환 결과·동기화 폴더·내보낸 프리셋은 별도 보관합니다. DPAPI 값은 같은 Windows 사용자/PC에서 확인해야 합니다. 상세 계약은 [USER_DATA](USER_DATA.md)에 있습니다.
- canonical spec는 `installer/App05_FileOps.spec`로 옮겼으며 `scripts/App05_FileOps.spec`은 단일 원본을 실행하는 호환 wrapper입니다. 추적 제외 예외, 빌드 입력, 구조 문서와 공개 [CODE_MAP](CODE_MAP.md), README, 로컬 지도·작업 기록을 수정했습니다.
- 빌드 회귀에서 LOCALAPPDATA와 APPDATA를 검사 폴더로 격리하고 공통 백업 검사를 연결했습니다. 제품·설치 식별자·구형 호환 이름·UserSetting 위치는 유지합니다.

## 검증

- 전체 Python 회귀 **244개 통과**. 선행 설정·spec·빌드 입력 집중 검사 **25개 통과**.
- 파일 교체/fsync 실패, 암호화 실패, 메모리·디스크 보존, 명시 SMTP 25/빈 값 유지, 읽기 오류와 손상 복구 구분, 이전 백업 보존, 대화상자 실패·입력 오류를 검사했습니다.
- canonical/호환 spec를 실제 Python 실행하고 PyInstaller 생성기만 대역으로 바꿔 동일 소스·제품명·아이콘·버전 리소스를 확인했습니다. 전체 제품 패키징 실행으로 취급하지 않습니다.
- Windows PowerShell 5.1 공통 백업 최종 **32개 safety assertion** 통과. 실제 설정을 읽지 않는 격리 사본 검사입니다. 공통 도구의 settings-only 범위 불일치를 독립 검수에서 보고했고 총괄이 수정·회귀를 추가한 최종본을 확인했습니다.
- 변경 Python에 Ruff E9/F/B 통과, src/scripts/tools/installer 구문 컴파일 통과. 기존 설치 정책은 격리 더미 페이로드 Inno 컴파일 회귀를 유지합니다.
- 최종 전체 근거: `build/standardization/final-7fd86b57979c4853a0edc38005bc1ac2/unittest.log`. 집중 근거: `build/standardization/final-b37d306d755b4f88924574e44b8e87c7/`. git diff --check도 통과했습니다.

## Gemini 활용과 독립 판단

Antigravity CLI `gemini-3.8-flash-high`, effort high의 짧은 도구 없는 구현 초안 요청은 **59.24초에 비어 있지 않은 코드 응답으로 완료**됐습니다. `build/standardization/agy/atomic-settings-draft.json`에 응답·UTC·상태를 기록했습니다. 원자 저장 패턴을 참고했고 실제 코드에 없는 `_encrypt` 제안은 기존 encrypt_data 계약으로 대체했습니다. 직접 검수·수정 후 회귀 검사를 수행했습니다. 시간 초과·빈 응답은 완료로 세지 않습니다.

별도 담당이 ConfigManager 저장 후 메모리 반영, 대화상자 실패 처리와 canonical/호환 spec 입력을 읽기 교차 검수했고 이 변경의 치명 회귀를 찾지 못했습니다.

담당 회귀 이후 총괄은 canonical `installer/App05_FileOps.spec`로 실제 전체 PyInstaller 미서명 빌드를 수행했습니다. exitCode=0, sourceStable=true, officialPromoted=false이며 `build/standardization/canonical-package-result.json`에 기록했습니다. 결과는 소유한 `build/standardization/canonical-package-d1d7b48afeb74a5c931a2e1b8a19a55b`에 있고 공식 폴더에 반영하지 않았습니다.

실제 서명·설치/업그레이드/제거·게시는 실행하지 않았습니다. 기존 release ACL·서명물·키·실제 사용자 자료를 변경하지 않았습니다. 실제 배포 전 같은 사용자 DPAPI, 쓰기 잠금·공간 부족, 새 폴더 복원 후 대표 동기화/변환 작업, 예약·외부 서비스 동작과 설치 실패·취소를 확인해야 합니다.

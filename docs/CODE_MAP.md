# FileOps Hub 공개 코드 안내

파일 동기화, PDF·EML·Office 변환과 OCR 작업을 실행하고 결과를 기록하는 앱입니다. 이메일 열람 앱과 제품 역할을 합치지 않습니다.

| 역할 | 진입점 |
| --- | --- |
| 실행·무인 작업 | `src/main.py` |
| 화면·설정 대화상자 | `src/ui/`, `src/ui/settings_dialog.py` |
| 작업 실행·프리셋·이력 | `src/core/`, `src/core/preset_manager.py`, `src/core/run_journal.py` |
| 제품 식별자·호환 이름·활성 저장소 | `src/app_identity.py` |
| 설정 우선순위·암호화 | `src/utils/config_manager.py`, `src/utils/security.py` |
| 완전한 파일 저장 후 교체 | `src/utils/atomic_write.py` |
| 진단 로그 | `src/utils/logger.py` |
| 버전·번들 | `src/version.py`, `assets/` |
| 설치·패키징 설계 | `installer/setup.iss`, `installer/App05_FileOps.spec` |
| 빌드·서명·검증·선택 게시 | `scripts/build.ps1`, `scripts/sign.ps1`, `scripts/build_all.py`, `scripts/publish_release.py` |
| 사용자 자료 백업·검증·새 폴더 복원 | `scripts/Manage-UserData.ps1`, `scripts/user-data-profile.json` |
| 회귀 검사 | `tools/test_*.py`, `scripts/test_user_data_backup.ps1` |

`scripts/App05_FileOps.spec`는 기존 호출의 호환 진입점이며 설계 원본은 `installer/`에 한 번만 둡니다. `build/`·`dist/`는 임시·검증 출력, `release/`는 검증한 공식 서명 파일입니다. `UserSetting/`과 개인 작업 메모·인증 자료는 공개 저장소에 넣지 않습니다.

설정 대화상자는 모든 입력을 확인하고 한 번에 저장합니다. 실패하면 기존 디스크·메모리 값을 유지하고 대화상자에서 실패를 표시합니다. 비밀번호·토큰은 Windows 사용자에게 연결된 암호화 값입니다.

[백업·복원 안내](USER_DATA.md)는 설정·로그·실행 이력과 외부 업무 파일의 차이를 설명합니다. [이번 검수](STANDARDIZATION_PHASE3_5_REVIEW.md)는 자동 검사와 남은 실제 환경 검수를 구분합니다.

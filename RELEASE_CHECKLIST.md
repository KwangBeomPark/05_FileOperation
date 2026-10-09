# FileOps Hub 다음 릴리스 체크리스트

2026-10-09 사용자 요청의 서명 릴리스 준비를 반영했습니다. HEAD `cc3bc72` 이후 사용자 `scripts/build_all.py` 변경을 보존하며 이름/체크섬/검증 계약의 최소 수정과 회귀 검수를 진행했습니다. 실제 서명·설치·게시·커밋·push·태그는 실행하지 않았고 `release/` ACL은 변경하지 않았습니다. 사용자 KSP 로그인 통보는 실제 서명 성공의 증거와 구분합니다.

## 서명 전 확인

- [x] 새 설치 파일은 `App05_FileOps_Setup_v<version>.exe` 한 개로 통일했습니다. 생성 계약은 단일 이름이며 updater/launcher는 과거 `-Setup`·공개 별칭을 계속 인식합니다.
- [x] 체크섬은 설치 파일과 `build-manifest.json` 두 항목을 생성하며 검증·게시 요구와 일치시켰습니다. 별칭 생성은 공식 경로에서 사용하지 않습니다.
- [x] 현재 소스 버전 `1.4.3`을 유지했습니다. 변경 전 로컬/원격 `v1.4.3` 태그가 없고 GitHub 릴리스 목록에도 없었습니다. 서명 직전에 재확인하며 기존 공개 v1.4.2와 장부·서명물은 보존합니다.
- [ ] 수정 내용을 검토·커밋한 clean `main`에서 사용자 서명 세션으로 전체 빌드합니다. 아래 명령은 이 선행 게이트 이후 실행합니다.

## 이름 변경 영향

| 확인 대상 | 현재 의존성과 다음 작업 |
| --- | --- |
| `src/app_identity.py` | `installer_filenames`는 새 `_Setup` 이름 한 개를 반환합니다. `installer_names_for_tag`는 canonical을 우선하고 과거 `-Setup`·공개 별칭·known legacy 읽기 호환을 유지합니다. 앱 EXE `App05_FileOps.exe`, 설치 AppId·Windows AppId·UserSetting 위치는 유지합니다. |
| `scripts/build_all.py`, `scripts/publish_release.py` | 현재 공식 폴더는 설치 EXE 하나·`build-manifest.json`·`SHA256SUMS.txt` 정확히 세 파일을 요구합니다. manifest는 내부 앱 EXE와 설치 EXE를 기록하고 실제 서명도 둘을 검증합니다. 체크섬 writer/validator는 설치 파일과 manifest 두 항목으로 맞췄습니다. 기존 두 이름 세트나 alias-only 세트는 새 계약으로 재게시하지 않습니다. |
| `src/core/updater.py`, `scripts/App05_FileOps_Launcher.pyw` | 현재 installer_names_for_tag의 과거 호환 목록은 제안한 `_Setup` 이름도 허용합니다. 현재 소스의 정적 호환이며 이미 설치된 과거 EXE의 실제 다운로드 성공을 보장하지 않습니다. 구버전 앱/런처를 검수합니다. |
| spec 위치 | `installer/App05_FileOps.spec`이 원본이고 `scripts/App05_FileOps.spec`은 기존 호출 호환 wrapper입니다. 둘을 중복으로 판단해 삭제하지 않습니다. canonical spec과 이 체크리스트는 현재 이미 Git 추적 파일입니다. |
| VBA·공유 배포 | 읽은 Finance Add-in CSV의 설치 패턴 `App05*`는 제안 이름과 호환입니다. 같은 CSV의 ProcessName은 `App05.exe`로 실제 `App05_FileOps.exe`와 다릅니다. 배포된 워크시트·설치 경로·기존 런처 연결 검수가 필요하며 이번에 수정하지 않았습니다. |
| 기존 공개 버전 | 과거 설치 이름·서명물·장부·published/previous-release 보관본은 유지합니다. 새 버전 단일 설치 파일 정책 때문에 과거 자산을 삭제하지 않습니다. |

## 사용자 할 일

- [ ] HEAD `cc3bc72` 이후 별도 미커밋 `scripts/build_all.py` 변경을 작성자의 작업으로 보존하며 검토합니다. 새로 들어간 시작 시 트레이 자동 실행 기능도 실제 시작/종료·설정 저장 검수에 포함합니다. 단일 이름·체크섬 계약·버전·릴리스 노트·이 체크리스트를 검토한 뒤 clean `main`을 확정합니다. 전날 244개 검사와 미서명 spec 빌드 성공은 오늘 HEAD 및 미커밋 변경의 검증 결과가 아닙니다.
- [ ] 앱·예약·폴더 감시 작업을 종료하고 활성 UserSetting을 백업·검증합니다. 설정·logs·reports·손상 설정 사본이 대상입니다. 외부 동기화/변환 파일·사용자가 내보낸 프리셋은 별도 보관합니다. DPAPI 비밀번호/토큰은 같은 Windows 사용자/PC에서 복원 후 확인합니다. [백업 안내](docs/USER_DATA.md).
- [ ] 현재 빌드 의존성, Inno Setup와 유효한 Microsoft SignTool을 준비합니다. SimplySign 로그인·인증서 선택·PIN/OTP는 사용자 세션에서 처리합니다. 제한된 `release/`를 사용자가 승인한 정상 배포 세션에서 접근할 수 있는지 확인하며 권한을 임의로 완화하지 않습니다.
- [ ] 아래 선행 게이트 해결 후 사용자 직접 실행 관리자 PowerShell에서 서명 빌드를 실행합니다. 실제 옵션은 `Python`, `CertificateThumbprint`, `SignToolPath`, 선택적 `BuildLauncher`, `Publish`, `Overwrite`, `SkipSmartCardService`입니다. 현재 `BuildLauncher`는 생성/서명은 하지만 새 공식 세 파일에 포함하지 않으므로 기본 경로에서는 추가하지 않습니다. `Overwrite`로 기존 버전 보호를 우회하지 않습니다. 아래 호출은 게시를 포함하지 않습니다. 앱을 닫고 테스트·재빌드를 생략하지 않습니다.

```powershell
# 승인 커밋·사용자 서명 세션 준비 후 전체 검사/서명 실행
.\scripts\sign.ps1 -Python python -CertificateThumbprint '<선택한 공개 인증서 지문>' -SignToolPath '<Microsoft SignTool 전체 경로>'
python scripts/publish_release.py --verify-only
```

- [ ] 실행 파일·설치 파일의 게시자·유효한 서명·타임스탬프·SignTool 결과·manifest/checksum·소스 커밋 일치를 확인합니다. 내부 앱은 `dist/App05_FileOps.exe`의 실제 파일/해시도 검증하므로 검증 전에 해당 build 입력을 삭제하지 않습니다. `--verify-only`는 clean 소스와 공식 로컬 세트의 서명을 검증하고 게시하지 않습니다. 접근 제한 등으로 실패하면 검증 완료로 취급하지 않습니다.
- [ ] 격리된 실제 Windows 환경에서 구버전 실행 중 정상 종료, 종료 거부/파일 잠금 시 복사 차단, 기존 설치 경로 유지, 성공 후 확인된 구형 EXE 정리, 실패·취소 시 구버전과 UserSetting 보존, 제거와 동기화·PDF/EML/OCR·설정 복원을 검수합니다. Office·SMTP·네트워크·예약 동작은 해당 환경에서 확인합니다. [실제 설치 검수](docs/INSTALL_UPGRADE_ACCEPTANCE.md).
- [ ] 같은 커밋·서명·실제 설치 검수가 끝나면 명시적으로 게시합니다. 기존 서명 세트를 재빌드 없이 게시할 때 필요한 실제 선택값은 `FILEOPS_SIGN_CERT_SHA1`입니다. `scripts/sign.ps1 -Publish`는 다시 빌드/서명 후 게시하는 별도 흐름입니다.

```powershell
$env:FILEOPS_SIGN_CERT_SHA1 = '<같은 공개 인증서 지문>'
python scripts/publish_release.py
```

- [ ] 새 태그/커밋, draft 해제·stable/latest, 설치 파일 한 개와 두 메타데이터의 이름·크기·SHA-256을 대조하고 구버전 updater/launcher 다운로드를 검수합니다. `publish_release.py`는 기존 GitHub 릴리스가 있으면 거부하며, 현재 스크립트에는 이미 생성된 draft 업로드를 복구하는 전용 옵션이 없습니다. 실패 시 같은 태그 재실행을 복구 완료로 간주하거나 기존 자산을 덮어쓰지 않습니다.

## 정리 검토

아래는 사용자와 검토할 후보이며 삭제 승인이 아닙니다. 개별 내용과 사용 여부를 확인한 뒤 선택합니다.

| 후보 | 이유와 삭제 조건 |
| --- | --- |
| `.ruff_cache/`, 확인된 `__pycache__/`·`.pyc` | 재생성 가능한 캐시입니다. 앱·검사가 실행 중이지 않고 필요한 진단 근거가 별도 보존된 경우 개별 삭제를 검토합니다. |
| `build/standardization/` 내부의 확인된 오래된 QA fixture·추출 사본 | 마지막 성공/실패 근거와 해시를 보존하고 원본이 확인된 재생성 가능 사본만 후보입니다. `published-v142-*`는 이전 공식 배포 검증 근거로 별도 보존합니다. |
| `dist/packaging/` 내부 실패/미서명 staging | 현재 입력인지, 복구 대상인지, 마지막 진단 기록인지 확인한 개별 사본만 후보입니다. 일부 접근 제한 경로 내용은 이번에 확인하지 못했으므로 크기만 보고 삭제하지 않습니다. |

`tools/`에는 Git 추적 검사 도구가 있어 통째로 정리하지 않습니다. 전체 `build/`·`dist/`·가상환경도 삭제하지 않습니다. `tools/_local/previous-release-*`, `published-v1.4.2-*`, `build/standardization/published-v142-*`, 서명 도구·기록·기존 공식본·개인 인증 자료·UserSetting·DB·`reports/`와 사용자 수정은 보존합니다. `scripts/build_all.py`의 호출되지 않는 별칭 보조 함수도 updater/옛 버전 검사와 연결을 확인하기 전에는 삭제 대상으로 확정하지 않습니다.

10월 8일 Antigravity Gemini 3.8 Flash High/effort high 읽기 검토는 47.56초에 내용 있는 응답으로 완료했습니다. 이번 준비 변경의 최신 검사와 Gemini 응답 여부는 아래 기록을 따릅니다. 전날 결과를 현재 HEAD의 검증으로 재사용하지 않습니다.

[폴더 정리와 이름 제안 종합 검토](../04_DataRefinery/docs/CLEANUP_AND_RELEASE_REVIEW.md) — 실제 삭제는 사용자 검토 후 진행합니다.


## 2026-10-09 준비 검수 결과

- 현재 HEAD cc3bc72와 이번 준비 변경에서 격리된 전체 회귀 검사 **250개 통과**. 로그는 `build/standardization/release-readiness-final-059d11715f31422c84cf37548b2cf323/unittest.log`입니다. AppData/LocalAppData와 Qt offscreen 환경을 분리했습니다.
- 실제 Inno fixture 컴파일·단일 생성 이름·구형 updater/launcher 읽기 호환·설치+manifest 체크섬·세 파일 공식 세트·서명 실패 시 이전 공식 세트 보존을 확인했습니다. mock 서명 결과는 실제 디지털 서명 완료의 증거가 아닙니다.
- 백업 안전성 32개, Ruff, git diff --check 통과. 실제 자동 시작/트레이, DPAPI 같은 사용자/PC 복원, 잠금·Office 변환·실제 업그레이드/제거는 남은 수동 게이트입니다.
- 04·05 공통 계약의 agy Gemini 3.8 Flash High/effort high 검토는 65.60초에 내용 있는 SUCCESS로 완료했습니다. 응답은 `build/standardization/agy-release-contract-91334ce3ffe446b5aceeb1a51f5966fe/response.json`이며 대화 ID는 af351618-6c49-4972-9a9e-4adf7a8f89f1입니다. 내부 앱 서명 검증과 공식 다운로드 세트를 혼동한 제안은 채택하지 않았고 구버전 updater 실제 호환과 설치 실패 복구 검수를 유지했습니다. 크레딧 차감은 미확인입니다.

초기 검사에서는 회귀 자체 성공 후 콘솔 cp1252 로그 출력이 실패했습니다. 위 최종 실행에서는 출력 인코딩도 분리해 종료 코드 0을 확인했습니다. 실제 서명·설치·게시·태그 변경과 release/ 권한 변경은 이번 검수에서 실행하지 않았습니다.

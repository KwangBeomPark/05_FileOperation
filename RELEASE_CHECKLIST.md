# FileOps Hub 다음 릴리스 체크리스트

2026-10-08 읽기 검토 기준입니다. 이 문서를 작성하면서 소스·빌드·서명·설치·게시·정리를 실행하지 않았습니다. `release/`의 접근 제한을 그대로 유지하며 기존 공식 파일의 로컬 실물은 이번에 검증하지 못했습니다.

## 먼저 결정할 사항

- [ ] 다음 버전 설치 파일을 **앱 번호 접두부 이름 하나**로 확정합니다. 제안은 `App05_FileOps_Setup_v<version>.exe`이며 최종 철자 선택을 기다립니다.
- [ ] 현재 출력은 `App05_FileOps-Setup_v<version>.exe`와 `FileOps-Setup.v<version>.exe`입니다. 제안의 `_Setup`은 현재 `-Setup`과 다릅니다. **단일 이름 변경은 아직 구현하지 않았으며 현재 스크립트를 실행하면 기존 두 이름 계약을 사용합니다.**
- [ ] 새 버전과 승인 커밋을 정합니다. 현재 소스 버전은 `1.4.3`입니다. 기존 공개 `v1.4.2`와 alias-only 로컬 사본은 새 빌드로 취급하거나 재게시하지 않습니다. 이미 사용한 버전·태그를 다른 커밋으로 바꾸지 않습니다.

## 이름 변경 영향

| 확인 대상 | 현재 의존성과 다음 작업 |
| --- | --- |
| `src/app_identity.py` | 현재 installer_filenames는 두 이름을 반환합니다. 단일 생성 이름을 확정하고 과거 버전 읽기 호환은 유지해야 합니다. 앱 EXE `App05_FileOps.exe`, 설치 AppId·Windows AppId·UserSetting 위치는 별개이며 유지합니다. |
| `scripts/build_all.py`, `scripts/publish_release.py` | 별칭 복사·필수 두 파일·같은 바이트 검사·manifest·checksum·GitHub 자산 개수 검증을 한 설치 파일 계약으로 함께 맞춰야 합니다. |
| `src/core/updater.py`, `scripts/App05_FileOps_Launcher.pyw` | 현재 installer_names_for_tag의 과거 호환 목록은 제안한 `_Setup` 이름도 허용합니다. 현재 소스의 정적 호환이며 이미 설치된 과거 EXE의 실제 다운로드 성공을 보장하지 않습니다. 구버전 앱/런처를 검수합니다. |
| spec 위치 | `installer/App05_FileOps.spec`이 원본이고 `scripts/App05_FileOps.spec`은 기존 호출 호환 wrapper입니다. 둘을 중복으로 판단해 삭제하지 않습니다. 새 원본 파일을 승인 커밋에 포함해야 합니다. |
| VBA·공유 배포 | 읽은 Finance Add-in CSV의 설치 패턴 `App05*`는 제안 이름과 호환입니다. 같은 CSV의 ProcessName은 `App05.exe`로 실제 `App05_FileOps.exe`와 다릅니다. 배포된 워크시트·설치 경로·기존 런처 연결 검수가 필요하며 이번에 수정하지 않았습니다. |
| 기존 공개 버전 | 과거 설치 이름·서명물·장부·published/previous-release 보관본은 유지합니다. 새 버전 단일 설치 파일 정책 때문에 과거 자산을 삭제하지 않습니다. |

## 사용자 할 일

- [ ] 미커밋 변경, 새 canonical spec·공개 문서·실패주입 검사를 검토합니다. 이름 변경 구현·버전·릴리스 노트·이 체크리스트를 승인 커밋에 포함하고 clean `main`을 확정합니다.
- [ ] 앱·예약·폴더 감시 작업을 종료하고 활성 UserSetting을 백업·검증합니다. 설정·logs·reports·손상 설정 사본이 대상입니다. 외부 동기화/변환 파일·사용자가 내보낸 프리셋은 별도 보관합니다. DPAPI 비밀번호/토큰은 같은 Windows 사용자/PC에서 복원 후 확인합니다. [백업 안내](docs/USER_DATA.md).
- [ ] 현재 빌드 의존성, Inno Setup와 유효한 Microsoft SignTool을 준비합니다. SimplySign 로그인·인증서 선택·PIN/OTP는 사용자 세션에서 처리합니다. 제한된 `release/`를 사용자가 승인한 정상 배포 세션에서 접근할 수 있는지 확인하며 권한을 임의로 완화하지 않습니다.
- [ ] 사용자 직접 실행 관리자 PowerShell에서 서명 빌드를 실행합니다. 실제 옵션은 `Python`, `CertificateThumbprint`, `SignToolPath`, 선택적 `BuildLauncher`, `Publish` 등입니다. 아래는 게시를 포함하지 않습니다. 현재 실행 중 앱을 닫고 테스트·재빌드를 생략하지 않습니다.

```powershell
# 단일 이름 구현·새 버전·승인 커밋 확정 후, 저장소 루트에서 실행
.\scripts\sign.ps1 -Python python -CertificateThumbprint '<선택한 공개 인증서 지문>' -SignToolPath '<Microsoft SignTool 전체 경로>'
# 이번 버전에 별도 런처도 필요하면 위 호출에 -BuildLauncher를 추가
python scripts/publish_release.py --verify-only
```

- [ ] 실행 파일·설치 파일과 생성한 런처의 게시자·유효한 서명·타임스탬프·SignTool 결과·manifest/checksum·소스 커밋 일치를 확인합니다. `--verify-only`는 clean 소스와 공식 로컬 세트의 서명을 검증하고 게시하지 않습니다. 접근 제한으로 실행이 실패하면 검증 완료로 취급하지 않습니다.
- [ ] 격리된 실제 Windows 환경에서 구버전 실행 중 정상 종료, 종료 거부/파일 잠금 시 복사 차단, 기존 설치 경로 유지, 성공 후 확인된 구형 EXE 정리, 실패·취소 시 구버전과 UserSetting 보존, 제거와 동기화·PDF/EML/OCR·설정 복원을 검수합니다. Office·SMTP·네트워크·예약 동작은 해당 환경에서 확인합니다. [실제 설치 검수](docs/INSTALL_UPGRADE_ACCEPTANCE.md).
- [ ] 같은 커밋·서명·실제 설치 검수가 끝나면 명시적으로 게시합니다. 기존 서명 세트를 재빌드 없이 게시할 때 필요한 실제 선택값은 `FILEOPS_SIGN_CERT_SHA1`입니다. `scripts/sign.ps1 -Publish`는 다시 빌드/서명 후 게시하는 별도 흐름입니다.

```powershell
$env:FILEOPS_SIGN_CERT_SHA1 = '<같은 공개 인증서 지문>'
python scripts/publish_release.py
```

- [ ] 새 태그/커밋, draft 해제·stable/latest, 설치 파일 한 개와 필요한 메타데이터/선택 런처의 이름·크기·SHA-256을 대조하고 구버전 updater/launcher 다운로드를 검수합니다. 같은 태그가 이미 있으면 기존 자산 덮어쓰기를 시도하지 않습니다.

## 정리 검토

삭제 후보와 이유는 총괄 검토 문서에서 사용자와 결정합니다. 이 문서는 삭제 승인이 아닙니다. `tools/`에는 Git 추적 검사 도구가 있어 통째로 정리하지 않습니다. `tools/_local/previous-release-*`, `published-v1.4.2-*`, `build/standardization/published-v142-*`, 서명 도구·기록·기존 공식본·개인 인증 자료·UserSetting·DB와 사용자 수정은 보존합니다. 접근 불가능한 `release/`와 일부 `dist/packaging/`의 크기·내용은 미확인입니다.

Antigravity Gemini 3.8 Flash High/effort high 읽기 검토는 47.56초에 내용 있는 응답으로 완료했습니다. 새 버전에서도 두 별칭을 병행하라는 제안은 사용자 요청과 달라 채택하지 않았고, 과거 버전 보존과 의존성 검수만 반영했습니다. 실제 서명·설치·게시 완료의 근거로 사용하지 않습니다.

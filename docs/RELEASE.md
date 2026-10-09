# FileOps Hub 배포 절차

제품 ID는 `App05_FileOps`, 표시명은 `FileOps Hub`입니다. 이름·호환 목록은
`src/app_identity.py`, 버전은 `src/version.py`에서만 정의합니다.

## 빌드와 서명

1. 변경을 검수하고 새 `APP_VERSION` 및 변경 내용을 기록합니다. 이미 공개한 버전은 재사용하지 않습니다.
2. `main`에 변경을 커밋합니다. 기존 앱을 완전히 종료하고 SimplySign Desktop에 직접 로그인합니다.
3. 로그인한 사용자의 관리자 PowerShell에서 아래 명령을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

기본 동작은 검사 → 앱 빌드·서명 → Inno Setup 컴파일·서명 → 단일 설치 파일 검증 →
무결성/메타데이터 생성 → `release/` 반영입니다. `scripts/sign.ps1`을 직접 실행해도 같은 경로입니다.
`-BuildLauncher`는 선택적 런처도 빌드·서명합니다. `-Overwrite`는 로컬 산출물 교체만 허용하며
GitHub의 기존 버전을 덮어쓰지 않습니다. 이전 로컬 세트는 `tools/_local/previous-release-*`에 보존합니다.

서명 없이 개발 빌드만 확인하려면 `scripts/build.ps1 -Unsigned`를 사용합니다.
각 빌드는 독립적인 `dist/packaging/vX.Y.Z-<고유번호>/`에서 준비하므로 이전 파일이 섞이지 않습니다.
미서명 앱도 이 고유 폴더 안에 저장해 `dist/App05_FileOps.exe`의 기존 서명 앱을 덮어쓰지 않습니다.
미서명 결과는 `release/`에 반영하지 않으며 공개도 차단합니다.

서명 스크립트는 `SCardSvr`가 중지되어 있을 때만 시작하고 15초 이내 실행 여부를 확인합니다.
다른 서비스·시작 유형·인증서 저장소는 변경하지 않고 자동 관리자 재실행도 하지 않습니다.
기존 서비스가 실행 중이면 관리자 권한을 추가 요구하지 않습니다. 서비스를 직접 관리하는
환경에서는 `sign.ps1 -SkipSmartCardService`를 선택할 수 있습니다.

`-CertificateThumbprint`, `-SignToolPath` 또는 환경변수 `FILEOPS_SIGN_CERT_SHA1`,
`FILEOPS_SIGNTOOL_PATH`로 공개 인증서와 Microsoft SignTool을 명시할 수 있습니다.
기본 선택은 유효한 코드 서명용 개인키 인증서가 정확히 하나일 때만 가능합니다.
PIN·OTP는 사용자가 직접 입력하며 저장하지 않습니다. 환경변수는 종료 시 복원합니다.
공개할 때는 `-CertificateThumbprint` 또는 환경변수로 의도한 공개 인증서를 반드시 지정합니다.
`FILEOPS_TIMESTAMP_URL`은 RFC3161 타임스탬프 서버를 지정합니다.
KSP 개인키 접근 실패 시 로그인한 동일 사용자의 관리자 PowerShell에서 직접 실행하세요.

Python `scripts/build_all.py`는 공통 구현이고 `scripts/sign_and_release.ps1`은 이전 호출을 위한
호환 진입점입니다. 공개 서명 빌드는 현재 소스 재빌드와 회귀 테스트를 건너뛰지 못합니다.

## 필수 배포 세트

- `App05_FileOps_Setup_vX.Y.Z.exe`
- `SHA256SUMS.txt`
- `build-manifest.json`

새 공식 폴더는 위 세 파일만 허용합니다. 과거 `App05_FileOps-Setup_v...`,
`FileOps-Setup.v...` 이름은 updater/launcher 읽기 호환으로 유지하며 새 별칭은 생성하지 않습니다.
내부 앱은 `dist/App05_FileOps.exe`이고 manifest에 내부 앱과 설치 파일을 기록합니다.
체크섬은 설치 파일과 `build-manifest.json`을 포함하고 체크섬 자신은 제외합니다.
`-BuildLauncher`는 선택 런처를 생성/서명하지만 공식 세트에는 추가하지 않습니다.
기존 공개 v1.4.2와 이전 서명 장부는 보존합니다.
실제 앱과 배포 EXE는 SignTool `/pa /all /v`, Authenticode `Valid`, 타임스탬프 및 지정 서명자를
모두 통과해야 합니다. 플래그만 있는 메타데이터는 서명 증거로 인정하지 않습니다.

## 설치 검수와 명시적 공개

Windows Sandbox 또는 별도 PC에서 설치·업그레이드·바로가기·트레이 자동 시작·제거·Office/OCR/EML을
확인합니다. 기본 설치 경로는 `%LOCALAPPDATA%\Programs\FileOps`, 데이터는 그 안의 `UserSetting`입니다.
기존 `UserSetting`은 업그레이드와 제거 시 보존하며 다른 외부 구형 데이터는 자동 가져오지 않습니다.
업그레이드는 기존 설치 폴더를 기본값으로 유지합니다. 신규 설치의 기본값만 Programs/FileOps입니다.
이름이 바뀐 이전 EXE와 옛 바로가기는 현재 설치 폴더에서만 정리합니다. 오래된 작업표시줄
고정 아이콘은 새 FileOps Hub 바로가기로 다시 고정해 주세요.
단위 테스트와 컴파일 성공만으로 이 수동 검수를 완료했다고 표현하지 않습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -Publish -CertificateThumbprint "YOUR_PUBLIC_CERTIFICATE_THUMBPRINT"
```

`-Publish`가 없으면 Git 변경·푸시·태그·업로드를 하지 않습니다. 공개 요청 시에는 깨끗한
`main`, 허용된 `origin`, 현재 커밋에 일치하는 서명 파일·버전·완전한 체크섬을 재검사합니다.
기존 GitHub 버전이 있으면 실패하며 `--clobber`나 강제 푸시를 사용하지 않습니다.
태그/메인은 원자적으로 푸시하고, 파일 목록을 명시하여 Draft 업로드 후 GitHub 크기·SHA-256을
확인한 뒤 공개·Latest 상태를 재확인합니다. 실패한 Draft는 삭제하거나 덮어쓰지 않습니다.
복구는 실패 원인을 확인한 후 수동으로 결정합니다.

## 이미 공개된 v1.4.2와 로컬 정리

기존 v1.4.2 공개본은 역사 기록으로 유지합니다. 현재 `release/`의 v1.4.2 두 설치 파일은
그 공개본의 **로컬 파일명 별칭**이며, 내부 앱은 기존 이름 그대로입니다.
메타데이터에 `alias_only=true`, `binary_product_id`, 원본 메타데이터 해시를 기록하고
원본 세트는 `tools/_local/published-v1.4.2-*`에 보존합니다. 이 세트의 재공개는 차단합니다.
새 App05 앱을 배포하려면 새 버전 확정 → 커밋 → 재빌드·서명 → 설치 검수 → 공개가 필요합니다.

기존 v1.4.2 업데이터는 새 듀얼 파일명을 알지 못합니다. 새 표준 릴리즈로 처음 넘어갈 때는
앱의 릴리즈 페이지 버튼에서 설치 파일을 직접 다운로드하여 기존 설치 폴더에 업그레이드합니다.
한 번 새 App05 앱으로 업그레이드하면 이후 두 자리 듀얼 파일명 자동 업데이트를 지원합니다.
구형 파일명 배포물을 새로 만들어 App005 명칭을 재도입하지 않습니다.

`scripts/clean_release.ps1 -WhatIf`로 정리 대상을 확인할 수 있습니다. 실제 실행은 서명된 최신
파일의 해시와 서명을 먼저 확인한 뒤 이름이 명확한 과거 최상위 파일만 영구 삭제합니다.
GitHub 파일·설치 폴더·UserSetting·하위 폴더는 건드리지 않습니다. 공개된 과거 파일은 GitHub에서
다시 받을 수 있지만 미공개 로컬 빌드는 복구할 수 없을 수 있습니다.

## Windows 신뢰 정책

Smart App Control을 끄거나 사내 전용/자체 서명 인증서를 공개 신뢰의 대체로 사용하지 않습니다.
공개 CA 서명도 모든 PC의 SmartScreen 및 회사 정책 경고가 없음을 보장하지는 않습니다.

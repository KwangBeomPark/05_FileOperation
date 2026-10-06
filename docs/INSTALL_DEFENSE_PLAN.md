# 설치·실행 문제 점검

현재 제품 ID는 App005_FileOps입니다. 이름·폴더·데이터 규칙은
[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md), 배포 절차는 [RELEASE.md](RELEASE.md)를 참조하세요.

## 위치와 첫 설정

- 기본 설치 폴더: `%LOCALAPPDATA%\Programs\FileOps`
- 실행 파일: `App005_FileOps.exe`
- 설정: 설치 폴더의 `UserSetting\settings.json`
- 로그·예약 이력: `UserSetting\logs`, `UserSetting\reports`
- 설치 폴더를 직접 바꾸면 해당 폴더의 UserSetting을 사용합니다.
- 이전 IntegratedDataTool 또는 LocalAppData/FileOps 데이터를 자동으로 가져오지 않습니다.
  언어·작업 그룹·예약·메일 설정을 다시 지정하고 수동 실행부터 확인하세요.
- UserSetting은 설치 패키지에 넣지 않으며 프로그램 제거 시에도 남습니다.

## 배포와 개발 빌드

Git clone이나 소스 ZIP에는 설치 파일이 없습니다. 사용자는 GitHub Releases의
`App005_FileOps_Setup_vX.Y.Z.exe`를 받습니다. 개발자는 다음 순서로 확인합니다.

```powershell
python -m pip install -r requirements.txt
python scripts/build_all.py
```

서명 없는 개발 설치 파일은 `tools/_local/development-release/`에 생성합니다.
공식 배포는 `FILEOPS_SIGN_CERT_SHA1`과 signtool을 준비한 뒤
`python scripts/build_all.py --require-signature`로 만듭니다.
선택적 런처가 필요하면 `--build-launcher`를 추가합니다.
런처 이름은 `App005_FileOps_Launcher_vX.Y.Z.exe`이며 설치 파일과 다릅니다.

빌드는 Python/의존성/테스트/정적 검사를 먼저 수행하고, 같은 버전의 출력 교체는 기본 차단합니다.
제품명·실행 파일명은 `src/app_identity.py`, 버전은 `src/version.py`가 기준입니다.
서명 도구를 다른 프로젝트에서 가져오지 않습니다.

## PC별 진단

```powershell
python tools/diagnose_install.py --check-browser
python tools/diagnose_install.py --check-browser --check-office
```

- EML: Playwright driver와 Chromium 상태를 확인합니다.
- OCR: Tesseract를 설정하거나 Windows OCR fallback이 가능한지 확인합니다.
- Office: 해당 Excel/Word/PowerPoint 설치·라이선스·COM 권한을 확인합니다.
- 설치 파일 없음: 소스만 받은 상태인지, 개발 빌드와 공식 release 경로를 혼동했는지 확인합니다.
- signtool 없음: Windows SDK를 설치하거나 FILEOPS_SIGNTOOL_PATH로 지정합니다.
- 구버전 앱 감지: 런처는 App005_FileOps.exe, App05_FileOps.exe, IntegratedDataTool.exe를 인식합니다.
  같은 버전의 설치 파일과 런처를 짝지어 사용하세요.

## 실제 Windows 검수

격리된 PC에서 신규 설치와 이전/사용자 지정 설치로부터의 업데이트를 확인합니다.
경로 화면의 기본값, 바탕화면·시작 메뉴, 트레이·중복 실행, 자동 시작, 언어·매뉴얼,
작업 수동 실행, 예약 시작·종료 이력, 제거 후 UserSetting 보존을 확인하세요.
설치 프로그램 컴파일 성공은 실제 설치·업데이트 성공을 증명하지 않습니다.

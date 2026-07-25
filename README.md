# FileOps Hub

회사 내 여러 팀이 따로 관리하는 최신 매뉴얼과 업무 자료를 공용 배포 폴더로 모으고, 정산·분석에 필요한 문서 변환 작업을 자동화하는 Windows 데스크톱 도구입니다.

## 운영 목적

1. **팀 자료 배포 허브**: 유관부서 폴더와 영업/관리자 공용 폴더 사이에서 최신 파일을 양방향으로 동기화합니다.
2. **저장소 호환 포맷 변환**: Excel, PowerPoint, Word, PDF를 대상 저장소가 허용하는 형식으로 변환하면서 파일 시간을 보존합니다.
3. **정산 자료 전처리**: PDF와 EML을 이미지로 변환하고, 이미지 OCR로 프로모션 번호를 추출해 파일명을 정리합니다.
4. **예약 실행과 결과 통지**: 앱이 실행 중이면 지정 시각 이후 하루 한 번 통합 작업을 실행하고, 성공·부분 실패 내역을 담당자 이메일로 보냅니다. 메일 실패 시 로컬 보고서를 남깁니다.

이 앱은 사내 접근 권한 자체를 부여하지 않습니다. 실제 권한은 Windows 네트워크 드라이브, OneDrive 또는 SharePoint 폴더 ACL에서 관리하고, 앱은 현재 Windows 사용자가 접근 가능한 경로만 처리합니다.

## 주요 기능

- `Folder Sync`: 여러 폴더의 최상위 파일을 비교해 최신본을 배포하고 구버전·충돌본을 `to be deleted`에 보존
- `EML Image`: 등록한 소스 폴더의 EML을 PNG로 일괄 변환하고 변경 없는 파일은 건너뜀
- `PDF Image`: 선택한 PDF의 각 페이지를 JPG로 렌더링
- `Image OCR`: 이미지 텍스트에서 프로모션 번호를 찾아 충돌 없는 이름으로 변경
- `Bypass Convert`: Office COM을 사용한 Excel/PowerPoint/Word 변환과 PDF ZIP 패키징
- `Task Runner`: 활성 작업 순차 실행, 매일 예약 실행, SMTP 결과 보고, 실패 시 로컬 보고서 저장

통합 실행은 각 기능 탭의 `build_run_config()`가 만든 명시적 실행 계약을 `RunPlan`으로 묶고, 공통 preflight 후 PyQt 없는 core 실행 엔진에서 순차 처리합니다. UI 스레드는 진행 상태와 취소 신호만 연결합니다.

## 실행 환경

- Windows 10/11, Python 3.13 이상 권장
- Office 변환: 해당 PC에 Microsoft Excel/Word/PowerPoint 설치 및 COM 실행 권한 필요. Office 파일이 포함된 작업은 사전 점검에서 실행 가능 여부를 확인하고, 실패하면 시작하지 않습니다.
- OCR: Tesseract가 있으면 우선 사용하고, 없으면 Windows 내장 OCR로 자동 fallback합니다. Tesseract를 쓰려면 `Settings`에서 `tesseract.exe`를 지정할 수 있습니다.
- EML 이미지: 소스 실행 시 `python -m playwright install chromium`으로 Chromium 준비. 패키징된 EXE는 Playwright driver를 포함하며, Chromium이 없으면 최초 변환 시 설치를 시도합니다.

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python src/main.py
```

## 기본 사용 순서

1. `Settings`에서 Tesseract, SMTP, 수신자 목록을 설정합니다.
2. `Folder Sync`와 `EML Image`에 반복 사용할 폴더 작업을 등록합니다.
3. 필요한 PDF/OCR 파일과 포맷 변환 원본 폴더를 선택합니다.
4. `Task Runner`에서 이메일 자동 발송과 매일 실행 시각을 지정합니다.
5. 첫 실행은 수동으로 수행해 결과 보고서와 대상 폴더를 확인한 뒤 예약 실행을 사용합니다.

## 검증과 빌드

```powershell
python -m compileall -q src tools
python -m unittest discover -s tools -p "test_*.py" -v
python tools/build_all.py
```

`ruff`는 선택 검증입니다. 설치된 경우 `python -m ruff check src tools --select E9,F,B`를 추가로 실행합니다.

앱 버전은 `src/version.py`만 수정합니다. `tools/build_all.py`는 테스트를 포함해 실행하고 같은 버전의 설치 파일 덮어쓰기를 기본 차단합니다. 설치 파일은 Git 소스 zip/clone에 포함되지 않습니다. 배포 대상 PC는 GitHub Releases의 `IntegratedDataTool_Setup_vX.Y.Z.exe`를 받아야 합니다. 설치 장애 대응 절차는 `INSTALL_DEFENSE_PLAN.md`와 `docs/RELEASE.md`를 확인합니다.

`App05_FileOps_vX.Y.Z.exe`는 별도 Python 설치 없이 실행되는 버전형 런처입니다. 설치된 FileOps Hub를 열고, 없으면 GitHub Release의 정식 설치 파일과 SHA-256 digest를 검증한 뒤 설치를 시작합니다. 이 런처도 Release 자산으로 함께 배포합니다.

설치/런타임 사전 점검:

```powershell
python tools/diagnose_install.py --check-browser
```

Office 변환까지 사용할 PC에서는 다음 명령이 성공해야 합니다.

```powershell
python tools/diagnose_install.py --check-browser --check-office
```

설정과 로그는 `%LOCALAPPDATA%\IntegratedDataTool`에 저장됩니다. GitHub 토큰과 SMTP 비밀번호는 Windows DPAPI로 암호화합니다.

## 현재 경계

- 예약 실행은 앱이 실행 중일 때만 동작합니다. 로그아웃 상태의 무인 실행은 Windows 작업 스케줄러 또는 서비스 구성이 별도로 필요합니다.
- 폴더 동기화는 등록 폴더의 **최상위 파일만** 처리하며 하위 폴더 트리는 재귀 동기화하지 않습니다.
- PDF/OCR 대상은 현재 GUI에서 선택한 파일 기준입니다. 반복 감시 폴더 방식은 아직 제공하지 않습니다.
- 실제 네트워크 드라이브, SharePoint 동기화 지연, Office COM, SMTP 계정은 해당 회사 환경에서 별도 수동 검증이 필요합니다.

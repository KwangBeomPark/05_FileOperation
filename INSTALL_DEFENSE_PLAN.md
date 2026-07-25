# 설치 오류 방어계획

## 현재 확인된 위험

1. GitHub에서 소스만 clone/download 하면 `dist/` 산출물은 포함되지 않는다.
   - `.gitignore`가 `dist/`를 제외하므로 `IntegratedDataTool_Setup_vX.Y.Z.exe`는 Git 소스에 없다.
   - 설치 대상 PC에는 GitHub Releases의 설치 파일을 내려받거나, 해당 PC에서 빌드를 먼저 해야 한다.

2. 문서에는 `python tools/build_all.py`가 있었지만 실제 Git 추적 파일에는 없었다.
   - 새 PC에서 문서대로 빌드하면 `tools/build_all.py` 없음 오류가 발생한다.
   - 이제 `tools/build_all.py`를 추적 파일로 추가했다.

3. 단일 exe 내부에서 Playwright Chromium 자동 설치가 실패할 수 있었다.
   - frozen exe에서는 `sys.executable`이 Python이 아니라 앱 exe다.
   - `src/core/eml_converter.py`를 수정해 bundled Playwright driver를 직접 호출한다.

4. EML, OCR, Office 변환은 설치 파일만으로 모든 외부 런타임이 해결되지 않는다.
   - Playwright Chromium, Tesseract OCR, Microsoft Office COM은 PC 환경 영향을 받는다.
   - `tools/diagnose_install.py`로 사전 점검한다.

## 정상 배포 절차

개발 PC에서:

```powershell
python -m pip install -r requirements.txt
python tools/build_all.py
```

`tools/build_all.py`는 `src/version.py` 버전을 Inno Setup과 EXE 메타데이터에 함께 적용하고, 같은 버전 설치 파일의 덮어쓰기를 차단한다. 정식 외부 배포는 코드 서명 인증서를 설정한 뒤 `--require-signature`로 수행한다.

배포할 때:

- 사용자는 GitHub 소스 zip이 아니라 GitHub Releases의 `IntegratedDataTool_Setup_vX.Y.Z.exe`를 받는다.
- Release에 setup EXE와 생성된 `.sha256` manifest를 함께 올린다. 앱과 `App05_FileOps.exe`는 GitHub API digest를 검증한 뒤에만 설치 파일을 실행한다.
- `App05_FileOps.exe`도 Release 자산으로 함께 배포한다. 이 파일은 설치된 앱을 열거나, 없으면 정식 Setup EXE를 내려받아 실행한다.
- 설치 전 기존 앱을 종료한다.

새 PC에서 장애가 나면:

```powershell
python tools/diagnose_install.py --check-browser
```

Office 변환까지 확인해야 하면 다음 명령이 성공해야 한다. 실패한 PC에서는 Office 파일을 포함한 Bypass 작업을 실행하지 않는다.

```powershell
python tools/diagnose_install.py --check-browser --check-office
```

## 릴리즈 전 체크리스트

- `python -m compileall -q src` 통과
- `python -m pip check` 통과
- `python tools/build_all.py` 통과
- `dist/IntegratedDataTool.exe` 생성 확인
- `dist/IntegratedDataTool_Setup_vX.Y.Z.exe` 생성 확인
- 설치 파일을 테스트 PC에 복사해 설치와 최초 실행 확인
- EML 변환을 한 번 실행해 Playwright Chromium 설치/실행 확인
- OCR PC에서는 Tesseract 경로가 Settings에 잡히는지 확인
- Office 변환 PC에서는 Excel/Word/PowerPoint COM 실행 확인

## 장애별 1차 대응

- `dist\IntegratedDataTool.exe`를 찾을 수 없음: 소스만 받은 상태다. `python tools/build_all.py`로 빌드하거나 Release 설치 파일을 받는다.
- `iscc`를 찾을 수 없음: Inno Setup이 설치되어 있지 않거나 기본 설치 경로/PATH에서 찾을 수 없다. Inno Setup 설치 후 새 터미널에서 다시 빌드한다.
- 설치 후 EML 변환 실패: `tools/diagnose_install.py --check-browser`로 Playwright driver/Chromium 상태를 확인한다.
- OCR 실패: Tesseract 설치 여부와 Settings의 `tesseract.exe` 경로를 확인한다.
- Office 변환 실패: 해당 PC의 Microsoft Office 설치와 COM 자동화 권한을 확인한다.

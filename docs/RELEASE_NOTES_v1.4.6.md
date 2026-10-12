# FileOps Hub v1.4.6 — App05_FileOps

## 주요 변경 사항

- **업데이트 설치 후 자동 재실행 실패 수정 (`Failed to load Python DLL ... python3xx.dll`)**:
  - 원인: 앱은 PyInstaller 단일 실행 파일로, 실행 시 임시 폴더(`_MEIxxxxx`)를 만들고 숨은 `_PYI_*` 환경변수로 그 위치를 기록합니다. 업데이트 설치 프로그램을 띄운 뒤 앱이 종료되면서 이 임시 폴더가 삭제되는데, 설치 완료 후 새 앱을 실행할 때 물려받은 환경변수 때문에 이미 삭제된 폴더의 DLL을 찾다가 실패했습니다.
  - 앱: 설치 프로그램을 실행하기 전에 `_PYI_*` 환경변수를 정리하고 `PYINSTALLER_RESET_ENVIRONMENT=1`을 설정합니다 (`src/core/updater.py`의 `launch_installer`).
  - 설치 프로그램: 설치가 시작될 때 같은 리셋 값을 설정해, 설치 마지막 단계에서 실행되는 새 앱이 이전 임시 폴더를 참조하지 않도록 했습니다 (`installer/setup.iss`).

## 업데이트 시 유의 사항

- 1.4.5 이하에서 업데이트한 뒤 "Failed to load Python DLL" 오류 창이 떴다면, 설치 자체는 완료된 상태입니다. 오류 창을 닫고 시작 메뉴나 바탕화면 아이콘으로 앱을 실행하면 됩니다. 설정·동기화 그룹·이력·스케줄 데이터는 그대로 유지됩니다.
- 설치 전 실행 중인 FileOps Hub(트레이 아이콘 포함)를 완전히 종료해 주세요.
- 기존 설정, 동기화 그룹, 이력 및 스케줄 데이터는 `%LOCALAPPDATA%\Programs\FileOps\UserSetting`에서 무손실로 안전하게 유지됩니다.

## 배포 아티팩트

- `App05_FileOps_Setup_v1.4.6.exe` (SHA-256 및 Authenticode 디지털 서명)
- `SHA256SUMS.txt`
- `build-manifest.json`

## 품질 검증

- 단위 회귀 테스트 전체 통과 (`python -m unittest discover -s tools -p "test_*.py"`). 업데이터 재실행 환경 회귀 테스트 2건 추가.
- 실제 서명된 설치 파일과 실제 업그레이드 설치(1.4.5 → 1.4.6) 검수는 배포 전 별도로 수행합니다.

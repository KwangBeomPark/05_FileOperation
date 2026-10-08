# FileOps Hub: 이름·폴더·경로 규칙

관리 번호는 **05**, 제품 ID는 **App05_FileOps**, 화면 표시명은 **FileOps Hub**입니다.
저장소와 GitHub 이름 `05_FileOperation`은 기존 링크를 위해 유지합니다.

## 설치 폴더와 데이터 폴더

| 구분 | 위치 |
| --- | --- |
| 기본 설치 폴더 | `%LOCALAPPDATA%\Programs\FileOps` |
| 설치된 실행 파일 | `%LOCALAPPDATA%\Programs\FileOps\App05_FileOps.exe` |
| 새 설정 파일 | `%LOCALAPPDATA%\Programs\FileOps\UserSetting\settings.json` |
| 로그 | `%LOCALAPPDATA%\Programs\FileOps\UserSetting\logs` |
| 수동·예약 실행 이력 | `%LOCALAPPDATA%\Programs\FileOps\UserSetting\reports` |

프로그램 폴더 안의 `UserSetting`에 데이터만 모읍니다. 직접 설치 경로를 바꾸면 실행 파일 옆의
`UserSetting`을 사용합니다. 소스 실행은 기본 설치 폴더의 `UserSetting`을 사용합니다.
신규 설치의 경로 선택 화면에는 `Programs\FileOps`가 기본값입니다.
업그레이드는 기존 설치 폴더를 유지하여 그 안의 UserSetting을 계속 사용합니다.
사용자가 직접 다른 경로를 지정할 수 있으나 기본값은 위 위치입니다.

사용자 요청에 따라 이전 `IntegratedDataTool` 또는 `%LOCALAPPDATA%\FileOps`의 설정·로그·예약 이력을 자동으로 가져오지 않습니다.
현재 UserSetting을 처음 만드는 경우 언어·작업 그룹·예약·메일 설정을 지정하며 예약은 꺼져 있습니다.
기존 UserSetting이 있으면 설정·작업 그룹·예약·이력을 그대로 사용합니다.
구버전 프로그램 감지와 외부 구형 데이터 이전은 별개입니다. 런처는 구버전 프로그램도 찾지만
외부 구형 데이터 폴더를 자동 가져오지는 않습니다. 설치 및 Windows 중복 실행 식별자는 유지합니다.
기존 설치 폴더를 통째로 삭제하거나 이동하지 않습니다.

`UserSetting`은 설치 패키지에 넣지 않고, 제거 시에도 보존합니다. 깨끗한 초기화가 필요하면
앱을 완전히 종료한 뒤 `UserSetting`만 별도로 정리합니다. 프로그램 실행 파일과 혼동하지 마세요.

이 폴더의 쓰기 권한이 없으면 다른 작업 폴더에 몰래 저장하지 않습니다. 설정 폴더 생성은
경로와 권한 확인 오류를 알리고, 로그·대체 결과 보고서 저장 실패도 알립니다. 사용자 지정
설치 경로 역시 현재 사용자에게 쓰기 권한이 있는 위치로 선택해야 합니다.

## 파일 이름

| 역할 | 이름 |
| --- | --- |
| 설치된 앱 | `App05_FileOps.exe` |
| 사내 설치 프로그램 | `App05_FileOps-Setup_vX.Y.Z.exe` |
| 공개 설치 프로그램 (동일 바이트·서명) | `FileOps-Setup.vX.Y.Z.exe` |
| 선택적 설치 확인·실행 런처 | `App05_FileOps_Launcher_vX.Y.Z.exe` |
| 공식 배포 체크섬 | `SHA256SUMS.txt` |
| 빌드 기록 | `build-manifest.json` |

이름·경로는 `src/app_identity.py`, 버전은 `src/version.py`가 기준입니다.
업데이트와 런처가 같은 설치 파일 목록을 사용합니다. `App05_FileOps_v*`는 v1.4.1 이전에는
런처였으므로, 이전 버전에서 설치 파일로 선택하지 않습니다. 이전 이름은 호환 코드와
과거 릴리스 기록에서만 유지합니다.

## 개발 폴더

| 폴더 | 역할 | Git 추적 |
| --- | --- | --- |
| `src/` | 앱 코드·제품 ID·버전 | 포함 |
| `assets/` | 아이콘·설명 이미지의 유일한 원본 | 포함 |
| `installer/` | Inno Setup 설치 설계와 PyInstaller spec | 포함 |
| `scripts/` | 빌드·서명·런처·PyInstaller 설계 | 포함 |
| `tools/` | 재사용 가능한 진단·검증·개발 도구 | 포함 |
| `tools/_local/` | 개발 빌드·임시 작업·정리 중 보관 자료 | 제외 |
| `docs/` | 사용·구조·배포·검증·과거 기록 | 포함 |
| `dist/` | 서명 앱 및 격리된 개발 staging | 제외 |
| `release/` | 현재 버전의 검증된 서명 배포물 | 제외 |

검증 파일이 들어 있는 `tools/` 전체를 Git에서 제외하지 않습니다. 임시 자료만 `_local/`로
격리합니다. 캐시·중간 파일은 다시 생성할 수 있습니다. 명확한 과거 로컬 배포 파일은 최신 파일의 서명·해시를 검증한 뒤 정리하며 GitHub 공개 이력은 유지합니다.
상세 문서와 인포그래픽은 `docs/`, `assets/`에 둡니다.

사내 공용 레지스트리의 기준은 이 프로젝트의 복제 문서가 아니라 상위 `00_Registry` 프로젝트입니다.
내부 설정이나 개인 PC 경로는 제품 코드에 넣지 않습니다. 외부 VBA/배포 도구가 프로세스 이름을
직접 지정한다면 새 배포를 적용할 때 `App05_FileOps.exe`로 설정해야 합니다.

## 검수

구버전 실행 파일·설치 파일 감지, 제품명·버전 주입, 아이콘 번들, 새 설정 초기화,
예약 비활성 기본값, 중복 실행 방지, 트레이를 검사합니다. 실제 Windows 설치·업그레이드·
자동 시작·제거는 격리된 PC에서 별도 확인해야 합니다.

기존 `Programs/FileOps/UserSetting`은 이번 이름 변경으로 초기화하지 않습니다.
현재 로컬 v1.4.2 설치 파일은 공개본의 파일명 별칭이며 내부 앱을 새로 빌드한 결과가 아닙니다.
`alias_only=true`를 기록하고 재공개를 차단합니다. 새 소스의 서명·설치 검수는 별도 진행해야 합니다.

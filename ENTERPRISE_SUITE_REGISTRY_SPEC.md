# 사내 업무 도구(GitHub 전 프로젝트) 통합 레지스트리 표준 명세서
> **문서 코드:** `PL-REG-ARCH-2026`  
> **문서 버전:** 2.0.0 (Enterprise Unified Edition)  
> **적용 대상:** `C:\Dev\GitHub` 내 모든 프로젝트 (VBA, AutoHotkey, Python 등)

---

## 1. 개요 및 통합 배경

현재 `C:\Dev\GitHub`에는 사내 업무 생산성을 극대화하기 위한 여러 독립 애플리케이션이 구축되어 있습니다:
- **오피스 애드인 (VBA):** PPT 애드인 (`03_vba_PPT_Addin`), 재무 결산 애드인 (`10_vba_FinanceAddin`), 전략 분석 (`vba_SA_Tool`)
- **화면 캡처 / 자동화 (AutoHotkey):** 캡처 및 OCR (`01_ClipOCR-Pro`), 아웃룩 결재 템플릿 (`08_OutLook_Template`)
- **데이터 / 시스템 유틸리티 (Python):** 폴더 및 파일 관리 (`05_FileOperation`), 메일 뷰어 (`07_eml-viewer`), 정제 (`04_DataRefinery`), 데이터마트 (`06_LocalDataMart`)

### 기존 문제점
1. **설정의 파편화**: 회사 메일 서버나 기본 폰트, 경로 등이 바뀔 때마다 PPT, 엑셀, 캡처앱, 파일관리앱 설정을 각각 수정해야 했습니다.
2. **언어별 저장소 불일치**: VBA는 Registry, AHK는 `.ini`, Python은 `.json`/환경변수 등을 혼용하여 도구 간 데이터 연동(예: 캡처앱이 저장한 이미지를 PPT 애드인이 바로 읽는 등)이 어려웠습니다.

### 통합 목표
- **단일 원클릭 배포**: `Setup-EnterpriseSuiteSettings.bat` 1회 실행으로 **모든 사내 도구의 환경설정을 동시에 완료**합니다.
- **다국어 표준 호환**: VBA, AutoHotkey, Python 모두에서 단 2~3줄의 코드로 레지스트리를 읽고 쓸 수 있는 표준 모듈을 제공합니다.

---

## 2. 전체 프로젝트 포트폴리오 매핑

| 프로젝트 폴더 | 기술 스택 | 주요 기능 | 레지스트리 활용 방안 |
| :--- | :---: | :--- | :--- |
| **`01_ClipOCR-Pro`** | AutoHotkey | 화면 캡처, OCR 텍스트 인식 | 캡처 기본 저장 경로, OCR 언어, 기본 폰트 연동 |
| **`02_SwiftDeck`** | Python/Web | 슬라이드/발표자료 자동화 | 공통 폰트, 템플릿 경로, 테마 설정 |
| **`03_vba_PPT_Addin`** | PowerPoint VBA | 슬라이드 서식, 쪽번호, 메일 전송 | 사내 폰트, SMTP 서버, 도메인, 표지 스킵 |
| **`04_DataRefinery`** | Python | 데이터 정제 및 ETL | 공통 로컬 작업 폴더, 사내 코드 매핑 |
| **`05_FileOperation`** | Python | 대량 폴더/파일 정리 및 관리 | 공통 작업 루트, 백업/아카이브 대상 경로 |
| **`06_LocalDataMart`** | Python/DuckDB | 사내 로컬 분석 데이터마트 | 로컬 DB 저장 경로, 데이터 수집 주기 |
| **`07_eml-viewer`** | Python / PyQt | EML 사내 메일 뷰어 | 첨부파일 다운로드 경로, 발신 도메인 필터 |
| **`08_OutLook_Template`** | AutoHotkey | 아웃룩 결재 및 회신 템플릿 | 사용자 기본 서명, 사내 결재선, 메일 도메인 |
| **`09_Market_Retail_Intelligence`** | Python | 리테일 시장 데이터 수집 | 시장 분석 리포트 저장 폴더 |
| **`10_vba_FinanceAddin`** | Excel VBA | 재무제표, 결산, 대량 메일 | 사내 SMTP, 발신자 이메일, 법인코드, 폰트 |
| **`vba_SA_Tool`** | Excel VBA | 영업/전략 분석 도구 | 공통 폰트, 데이터 출력 경로, 회사 정보 |

---

## 3. 통합 레지스트리 네임스페이스 및 구조

Windows의 VBA 내장 함수(`GetSetting`/`SaveSetting`)와 호환되면서, AHK(`RegRead`)와 Python(`winreg`)에서도 네이티브로 직접 접근할 수 있는 최적의 루트를 정의합니다.

- **표준 레지스트리 루트 경로**:  
  `HKCU\Software\VB and VBA Program Settings\PL_Suite\`

```text
HKEY_CURRENT_USER\Software\VB and VBA Program Settings\PL_Suite\
│
├── Common\                        <-- [1. 전사 공용 설정 (모든 도구 공통 참조)]
│   ├── CompanyName                : 회사명 (예: "MyCompany")
│   ├── EmailDomain                : 사내 기본 이메일 도메인 (예: "@company.com")
│   ├── SMTPServer                 : 사내 SMTP 서버 (예: "smtp.company.com")
│   ├── SMTPPort                   : SMTP 포트 (기본: "25")
│   ├── KoreanFont                 : 사내 표준 한글 폰트 (예: "Malgun Gothic")
│   ├── EnglishFont                : 사내 표준 영문/숫자 폰트 (예: "Arial Narrow")
│   ├── SecurityStampDefault       : 표준 보안 라벨 (기본: "Internal Use Only")
│   ├── WorkRootDir                : 사내 공통 작업 루트 (예: "%USERPROFILE%\Documents\PL_Workspace")
│   └── CaptureOutputDir           : 캡처/이미지 공통 저장소 (예: "%USERPROFILE%\Pictures\PL_Captures")
│
├── ClipOCR\                       <-- [2. 캡처/OCR 앱 전용 (01_ClipOCR-Pro)]
│   ├── HotKeyCapture              : 캡처 실행 단축키 (기본: "PrintScreen")
│   ├── OcrLanguage                : OCR 기본 언어 ("kor+eng")
│   └── AutoClipboard              : 텍스트 인식 후 자동 클립보드 복사 ("True")
│
├── FileOps\                       <-- [3. 폴더/파일 관리 앱 전용 (05_FileOperation)]
│   ├── DefaultSourceFolder        : 기본 정리 대상 폴더 (기본: "%USERPROFILE%\Downloads")
│   ├── DefaultArchiveFolder       : 기본 보관/아카이브 폴더
│   └── LogLevel                   : 로깅 수준 ("INFO")
│
├── App_PPT\                       <-- [4. 파워포인트 도구 전용 (03_vba_PPT_Addin, 02_SwiftDeck)]
│   ├── SkipCoverPageNumber        : 표지 쪽번호 제외 ("True"/"False")
│   ├── AdditionalRecipients       : 메일 발송 시 상시 추가 수신자
│   ├── SecurityStampOverride      : PPT 전용 보안라벨 (비어있으면 Common 사용)
│   └── ExportImageWidth           : 슬라이드 내보내기 기본 가로 너비 (기본: "1280")
│
├── App_Finance\                   <-- [5. 엑셀 재무 애드인 전용 (10_vba_FinanceAddin)]
│   ├── SenderEmail                : 사용자 개인 발신 메일 주소
│   ├── EmailMaxTotalMB            : 대량 메일 첨부파일 제한 (기본: "20")
│   └── LocalDataOutputDir         : 분석 결과 출력 하위 폴더명 ("DataOutput")
│
├── EmlViewer\                     <-- [6. 메일 뷰어 전용 (07_eml-viewer)]
│   ├── AutoPreview                : EML 파일 열기 시 즉시 본문 렌더링 ("True")
│   └── SaveAttachmentsFolder      : 첨부파일 기본 저장 폴더
│
├── OutlookTemplate\               <-- [7. 아웃룩 템플릿 전용 (08_OutLook_Template)]
│   ├── DefaultSignerName          : 기본 기안자 성명
│   └── TemplatePath               : 서식 HTML 템플릿 저장 폴더
│
└── App_Corp\                      <-- [8. 법인 결산 파일 전용 (향후 추가될 법인 파일)]
    ├── CompanyCode                : 기본 작업 법인 코드 ("1000")
    └── FiscalYear                 : 기본 회계연도 ("2026")
```

---

## 4. 언어별 표준 클라이언트 구현체 (즉시 복사하여 사용)

각 프로젝트는 자신의 언어에 맞는 표준 헬퍼 파일 하나만 포함하면 즉시 레지스트리를 읽고 쓸 수 있습니다.

### 4.1 VBA 표준 모듈 (`Mod_SuiteRegistry.bas`)
> **적용 대상:** `03_vba_PPT_Addin`, `10_vba_FinanceAddin`, `vba_SA_Tool`, 기타 법인 엑셀 파일

```vba
Attribute VB_Name = "Mod_SuiteRegistry"
Option Explicit

Private Const C_APP As String = "PL_Suite"
Private Const C_SEC_COMMON As String = "Common"

' 1. 공용 설정 읽기 / 쓰기
Public Function Suite_GetCommon(ByVal sKey As String, Optional ByVal sDefault As String = "") As String
    Dim sVal As String
    sVal = Trim$(GetSetting(C_APP, C_SEC_COMMON, sKey, ""))
    If sVal = "" Then sVal = sDefault
    Suite_GetCommon = sVal
End Function

Public Sub Suite_SaveCommon(ByVal sKey As String, ByVal sValue As String)
    SaveSetting C_APP, C_SEC_COMMON, sKey, Trim$(sValue)
End Sub

' 2. 앱 전용 설정 읽기 / 쓰기 (sSection: "App_PPT", "App_Finance", "App_Corp" 등)
Public Function Suite_GetApp(ByVal sSection As String, ByVal sKey As String, Optional ByVal sDefault As String = "") As String
    Dim sVal As String
    sVal = Trim$(GetSetting(C_APP, sSection, sKey, ""))
    If sVal = "" Then sVal = sDefault
    Suite_GetApp = sVal
End Function

Public Sub Suite_SaveApp(ByVal sSection As String, ByVal sKey As String, ByVal sValue As String)
    SaveSetting C_APP, sSection, sKey, Trim$(sValue)
End Sub

' 3. 주요 단축 함수
Public Function Suite_KoreanFont() As String: Suite_KoreanFont = Suite_GetCommon("KoreanFont", "Malgun Gothic"): End Function
Public Function Suite_EnglishFont() As String: Suite_EnglishFont = Suite_GetCommon("EnglishFont", "Arial Narrow"): End Function
Public Function Suite_SmtpServer() As String: Suite_SmtpServer = Suite_GetCommon("SMTPServer", "smtp.company.com"): End Function
Public Function Suite_SmtpPort() As Long: Suite_SmtpPort = CLng(Suite_GetCommon("SMTPPort", "25")): End Function
Public Function Suite_WorkRootDir() As String: Suite_WorkRootDir = Suite_GetCommon("WorkRootDir", Environ$("USERPROFILE") & "\Documents\PL_Workspace"): End Function
```

---

### 4.2 AutoHotkey 표준 모듈 (`SuiteRegistry.ahk`)
> **적용 대상:** `01_ClipOCR-Pro`, `08_OutLook_Template`

```ahk
; =====================================================================
; File: SuiteRegistry.ahk (AutoHotkey v1/v2 호환 레지스트리 헬퍼)
; =====================================================================

global SUITE_REG_ROOT := "HKEY_CURRENT_USER\Software\VB and VBA Program Settings\PL_Suite"

; 공용 설정 읽기
Suite_GetCommon(key, defaultValue := "") {
    RegRead, val, %SUITE_REG_ROOT%\Common, %key%
    if (ErrorLevel || val = "")
        return defaultValue
    return val
}

; 공용 설정 쓰기
Suite_SaveCommon(key, value) {
    RegWrite, REG_SZ, %SUITE_REG_ROOT%\Common, %key%, %value%
}

; 앱 전용 설정 읽기 (section: "ClipOCR", "OutlookTemplate" 등)
Suite_GetApp(section, key, defaultValue := "") {
    RegRead, val, %SUITE_REG_ROOT%\%section%, %key%
    if (ErrorLevel || val = "")
        return defaultValue
    return val
}

; 앱 전용 설정 쓰기
Suite_SaveApp(section, key, value) {
    RegWrite, REG_SZ, %SUITE_REG_ROOT%\%section%, %key%, %value%
}

; 주요 편의 함수
Suite_GetCaptureFolder() {
    folder := Suite_GetCommon("CaptureOutputDir", "")
    if (folder = "") {
        EnvGet, userProfile, USERPROFILE
        folder := userProfile . "\Pictures\PL_Captures"
    }
    return folder
}
```

---

### 4.3 Python 표준 모듈 (`suite_registry.py`)
> **적용 대상:** `05_FileOperation`, `07_eml-viewer`, `04_DataRefinery`, `06_LocalDataMart`

```python
"""
suite_registry.py - PL Tools Enterprise Registry Accessor for Python
Supports Windows winreg with automatic environment variable expansion.
"""
import os
import winreg

ROOT_KEY_PATH = r"Software\VB and VBA Program Settings\PL_Suite"

def _get_value(sub_section: str, key_name: str, default: str = "") -> str:
    full_path = f"{ROOT_KEY_PATH}\\{sub_section}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, full_path, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, key_name)
            if val is not None and str(val).strip() != "":
                # Expand environment variables like %USERPROFILE%
                return os.path.expandvars(str(val).strip())
    except (FileNotFoundError, OSError):
        pass
    return os.path.expandvars(default)

def _set_value(sub_section: str, key_name: str, value: str) -> bool:
    full_path = f"{ROOT_KEY_PATH}\\{sub_section}"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, full_path) as key:
            winreg.SetValueEx(key, key_name, 0, winreg.REG_SZ, str(value).strip())
            return True
    except OSError:
        return False

# 1. Common Settings
def get_common(key: str, default: str = "") -> str:
    return _get_value("Common", key, default)

def save_common(key: str, value: str) -> bool:
    return _set_value("Common", key, value)

# 2. App-Specific Settings
def get_app(app_section: str, key: str, default: str = "") -> str:
    return _get_value(app_section, key, default)

def save_app(app_section: str, key: str, value: str) -> bool:
    return _set_value(app_section, key, value)

# 3. Convenience Shortcuts
def get_work_root() -> str:
    default_root = os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "PL_Workspace")
    return get_common("WorkRootDir", default_root)

def get_capture_dir() -> str:
    default_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Pictures", "PL_Captures")
    return get_common("CaptureOutputDir", default_dir)

def get_smtp_info() -> tuple[str, int]:
    server = get_common("SMTPServer", "smtp.company.com")
    port = int(get_common("SMTPPort", "25"))
    return server, port
```

---

## 5. 원클릭 통합 배포 도구 (`Setup-EnterpriseSuiteSettings.bat`)

신규 PC를 세팅하거나 전사 환경이 변경되었을 때, 팀원에게 이 스크립트 하나만 실행시키면 **모든 프로젝트 전체의 환경이 3초 만에 구성**됩니다.

```bat
@echo off
chcp 65001 >nul
title PL Enterprise Suite - 전사 통합 환경설정 배포 도구

:: ====================================================================
:: [사내 관리자 기본값 설정 영역]
:: ====================================================================
set "COMPANY_NAME=MyCompany"
set "EMAIL_DOMAIN=@company.com"
set "SMTP_SERVER=smtp.company.com"
set "SMTP_PORT=25"
set "FONT_KOREAN=Malgun Gothic"
set "FONT_ENGLISH=Arial Narrow"
set "SECURITY_STAMP=Internal Use Only"
set "WORK_ROOT=%USERPROFILE%\Documents\PL_Workspace"
set "CAPTURE_ROOT=%USERPROFILE%\Pictures\PL_Captures"

:: ====================================================================
echo ====================================================================
echo       PL Enterprise Suite Configuration (사내 통합 환경설정)
echo ====================================================================
echo.
echo  모든 사내 도구(PPT, 엑셀, 캡처앱, 파일관리앱, 메일뷰어)의 설정을 적용합니다.
echo  * 관리자 권한 불필요 (HKCU 사용자 레지스트리 자동 구성)
echo.

:: 1. 전사 공용 설정 (Common)
set "KEY_COMM=HKCU\Software\VB and VBA Program Settings\PL_Suite\Common"
reg add "%KEY_COMM%" /v "CompanyName" /t REG_SZ /d "%COMPANY_NAME%" /f >nul
reg add "%KEY_COMM%" /v "EmailDomain" /t REG_SZ /d "%EMAIL_DOMAIN%" /f >nul
reg add "%KEY_COMM%" /v "SMTPServer" /t REG_SZ /d "%SMTP_SERVER%" /f >nul
reg add "%KEY_COMM%" /v "SMTPPort" /t REG_SZ /d "%SMTP_PORT%" /f >nul
reg add "%KEY_COMM%" /v "KoreanFont" /t REG_SZ /d "%FONT_KOREAN%" /f >nul
reg add "%KEY_COMM%" /v "EnglishFont" /t REG_SZ /d "%FONT_ENGLISH%" /f >nul
reg add "%KEY_COMM%" /v "SecurityStampDefault" /t REG_SZ /d "%SECURITY_STAMP%" /f >nul
reg add "%KEY_COMM%" /v "WorkRootDir" /t REG_SZ /d "%WORK_ROOT%" /f >nul
reg add "%KEY_COMM%" /v "CaptureOutputDir" /t REG_SZ /d "%CAPTURE_ROOT%" /f >nul
echo  [OK] 1. 전사 공용 설정 등록 완료 (폰트, 메일서버, 워크스페이스)

:: 2. 01_ClipOCR-Pro (캡처/OCR)
set "KEY_OCR=HKCU\Software\VB and VBA Program Settings\PL_Suite\ClipOCR"
reg add "%KEY_OCR%" /v "HotKeyCapture" /t REG_SZ /d "PrintScreen" /f >nul
reg add "%KEY_OCR%" /v "OcrLanguage" /t REG_SZ /d "kor+eng" /f >nul
reg add "%KEY_OCR%" /v "AutoClipboard" /t REG_SZ /d "True" /f >nul
echo  [OK] 2. 캡처/OCR 앱 설정 등록 완료

:: 3. 05_FileOperation (폴더/파일 관리)
set "KEY_FO=HKCU\Software\VB and VBA Program Settings\PL_Suite\FileOps"
reg add "%KEY_FO%" /v "DefaultSourceFolder" /t REG_SZ /d "%USERPROFILE%\Downloads" /f >nul
reg add "%KEY_FO%" /v "DefaultArchiveFolder" /t REG_SZ /d "%WORK_ROOT%\Archive" /f >nul
reg add "%KEY_FO%" /v "LogLevel" /t REG_SZ /d "INFO" /f >nul
echo  [OK] 3. 파일/폴더 관리 앱 설정 등록 완료

:: 4. 03_vba_PPT_Addin (파워포인트 애드인)
set "KEY_PPT=HKCU\Software\VB and VBA Program Settings\PL_Suite\App_PPT"
reg add "%KEY_PPT%" /v "SkipCoverPageNumber" /t REG_SZ /d "False" /f >nul
reg add "%KEY_PPT%" /v "ExportImageWidth" /t REG_SZ /d "1280" /f >nul
reg add "%KEY_PPT%" /v "AdditionalRecipients" /t REG_SZ /d "" /f >nul
echo  [OK] 4. 파워포인트 애드인 설정 등록 완료

:: 5. 10_vba_FinanceAddin (엑셀 재무 애드인)
set "KEY_FIN=HKCU\Software\VB and VBA Program Settings\PL_Suite\App_Finance"
reg add "%KEY_FIN%" /v "EmailMaxTotalMB" /t REG_SZ /d "20" /f >nul
reg add "%KEY_FIN%" /v "LocalDataOutputDir" /t REG_SZ /d "DataOutput" /f >nul
echo  [OK] 5. 엑셀 재무 애드인 설정 등록 완료

:: 6. 구버전 레거시 호환 레이어 (기존 실행 보장)
set "KEY_LEG_PPT=HKCU\Software\VB and VBA Program Settings\PLToolsPPTAddin\Settings"
reg add "%KEY_LEG_PPT%" /v "KoreanFont" /t REG_SZ /d "%FONT_KOREAN%" /f >nul
reg add "%KEY_LEG_PPT%" /v "EnglishFont" /t REG_SZ /d "%FONT_ENGLISH%" /f >nul
reg add "%KEY_LEG_PPT%" /v "EmailDomain" /t REG_SZ /d "%EMAIL_DOMAIN%" /f >nul
reg add "%KEY_LEG_PPT%" /v "SMTPServer" /t REG_SZ /d "%SMTP_SERVER%" /f >nul
reg add "%KEY_LEG_PPT%" /v "SMTPPort" /t REG_SZ /d "%SMTP_PORT%" /f >nul
reg add "%KEY_LEG_PPT%" /v "SecurityStampText" /t REG_SZ /d "%SECURITY_STAMP%" /f >nul
reg add "%KEY_LEG_PPT%" /v "SkipCoverPageNumber" /t REG_SZ /d "False" /f >nul
echo  [OK] 6. 구버전 하위 호환성 동기화 완료

:: 작업 디렉터리 자동 생성
if not exist "%WORK_ROOT%" mkdir "%WORK_ROOT%"
if not exist "%CAPTURE_ROOT%" mkdir "%CAPTURE_ROOT%"

echo.
echo ====================================================================
echo  [SUCCESS] 모든 사내 도구의 환경설정이 완료되었습니다!
echo ====================================================================
echo.
pause
```

---

## 6. 도구 간 상호 연동 시나리오 (Synergy Example)

레지스트리를 통합하면 사내 도구들이 서로 완벽히 연동됩니다:

1. **ClipOCR(캡처) ➔ PPT 애드인 연동**:
   - `01_ClipOCR-Pro`에서 캡처한 이미지가 `Common\CaptureOutputDir`에 자동 저장됩니다.
   - `03_vba_PPT_Addin`이나 `02_SwiftDeck`에서 "최근 캡처 이미지 삽입" 버튼을 누르면 이 레지스트리 경로를 바로 읽어 즉시 슬라이드에 삽입합니다.
2. **FileOperation(폴더관리) ➔ FinanceAddin(재무) 연동**:
   - `05_FileOperation`이 사내 메일이나 다운로드 폴더의 엑셀 파일들을 `Common\WorkRootDir`로 자동 분류합니다.
   - `10_vba_FinanceAddin`의 결산 매크로가 동일한 작업 경로를 읽어 원클릭으로 취합합니다.
3. **회사 정보 변경 시(서버 이전, 폰트 변경)**:
   - `Setup-EnterpriseSuiteSettings.bat` 변수 2개만 바꾸고 실행하면, **10개 앱 전체가 즉시 새 서버와 새 폰트를 인식**합니다.

# FileOps Hub (App05_FileOps) v1.4.1 Digital Signing Pipeline
# Run this script in an ELEVATED (Administrator) PowerShell window:
# powershell -ExecutionPolicy Bypass -File scripts\sign_and_release.ps1

$ErrorActionPreference = 'Stop'
$projectRoot = Resolve-Path "$PSScriptRoot\.."
Set-Location -LiteralPath $projectRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " FileOps Hub (App05_FileOps) Signing " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Administrator check
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Attempting to elevate to Administrator..."
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit 0
}

# 2. Ensure Smart Card Services are active
Write-Host "[1/6] Ensuring Smart Card services are active..." -ForegroundColor Yellow
Start-Service SCardSvr, CertPropSvc, ScDeviceEnum -ErrorAction SilentlyContinue

# 3. Locate certificate
$thumbprint = "E9C72CF5090840A1805296525D56BE680622A7FD"
$cert = Get-Item "Cert:\CurrentUser\My\$thumbprint" -ErrorAction SilentlyContinue
if (-not $cert) {
    $cert = Get-Item "Cert:\LocalMachine\My\$thumbprint" -ErrorAction SilentlyContinue
}
if (-not $cert) {
    Write-Error "Code signing certificate [$thumbprint] not found in Cert: store. Please ensure SimplySign is logged in."
    exit 1
}
Write-Host "Certificate found: $($cert.Subject)" -ForegroundColor Green

# 4. Locate signtool
$signtoolPaths = @(
    "C:\Dev\GitHub\06_Stepwise\release\build\signtool\signtool.exe",
    (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source,
    "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe"
)
$signtool = $signtoolPaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $signtool) {
    Write-Error "SignTool not found."
    exit 1
}

# 5. Sign main application binary
$appExe = "$projectRoot\dist\App05_FileOps.exe"
if (-not (Test-Path $appExe)) {
    Write-Error "App05_FileOps.exe not found at $appExe."
    exit 1
}

Write-Host "[2/6] Digitally signing App05_FileOps.exe..." -ForegroundColor Yellow
& $signtool sign /sha1 $thumbprint /fd sha256 /tr http://timestamp.digicert.com /td sha256 /v $appExe
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Primary timestamp failed, retrying with Certum timestamp server..."
    & $signtool sign /sha1 $thumbprint /fd sha256 /tr http://time.certum.pl /td sha256 /v $appExe
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to sign App05_FileOps.exe"
        exit $LASTEXITCODE
    }
}
Write-Host "App05_FileOps.exe signed successfully!" -ForegroundColor Green

# 6. Compile Inno Setup installer
Write-Host "[3/6] Compiling installer with Inno Setup..." -ForegroundColor Yellow
$isccPaths = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
)
$iscc = $isccPaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    Write-Error "Inno Setup compiler (ISCC.exe) not found."
    exit 1
}

& $iscc "/DAppVersion=1.4.1" "$projectRoot\tools\setup.iss"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup compilation failed with code $LASTEXITCODE"
    exit $LASTEXITCODE
}

# 7. Sign installer executable
$installerExe = "$projectRoot\release\App05_FileOps_v1.4.1.exe"
if (-not (Test-Path $installerExe)) {
    Write-Error "Installer not found at $installerExe"
    exit 1
}

Write-Host "[4/6] Digitally signing installer App05_FileOps_v1.4.1.exe..." -ForegroundColor Yellow
& $signtool sign /sha1 $thumbprint /fd sha256 /tr http://timestamp.digicert.com /td sha256 /v $installerExe
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Primary timestamp failed, retrying with Certum timestamp server..."
    & $signtool sign /sha1 $thumbprint /fd sha256 /tr http://time.certum.pl /td sha256 /v $installerExe
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to sign installer"
        exit $LASTEXITCODE
    }
}
Write-Host "Installer signed successfully!" -ForegroundColor Green

# 8. Verify signatures
Write-Host "[5/6] Verifying signatures..." -ForegroundColor Yellow
foreach ($bin in @($appExe, $installerExe)) {
    $sig = Get-AuthenticodeSignature -LiteralPath $bin
    if ($sig.Status -ne "Valid") {
        Write-Error "Signature invalid for: $bin ($($sig.StatusMessage))"
        exit 1
    }
    Write-Host "Verified $($sig.Status): $(Split-Path -Leaf $bin) (Timestamped: $($sig.TimeStamperCertificate.Subject))" -ForegroundColor Green
}

# 9. Write checksum manifest
Write-Host "[6/6] Generating SHA-256 manifests..." -ForegroundColor Yellow
$hash = (Get-FileHash -LiteralPath $installerExe -Algorithm SHA256).Hash.ToUpperInvariant()
$manifestLine = "$hash  $(Split-Path -Leaf $installerExe)"
Set-Content -Path "$projectRoot\release\App05_FileOps_v1.4.1.exe.sha256" -Value $manifestLine -Encoding ascii
Set-Content -Path "$projectRoot\release\App05_FileOps_v1.4.1.sha256" -Value $manifestLine -Encoding ascii

Write-Host "=========================================" -ForegroundColor Green
Write-Host " Signing & Verification Completed 100%! " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green

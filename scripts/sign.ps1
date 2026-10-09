# PL Suite one-click signing. Publishing is explicit and never clobbers a release.
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$CertificateThumbprint = $env:FILEOPS_SIGN_CERT_SHA1,
    [string]$SignToolPath = $env:FILEOPS_SIGNTOOL_PATH,
    [switch]$BuildLauncher,
    [switch]$Overwrite,
    [switch]$Publish,
    [switch]$SkipSmartCardService
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskBuildScript = Join-Path $PSScriptRoot 'build_all.py'
if (-not $CertificateThumbprint) {
    $taskNow = Get-Date
    $taskCertificates = @(Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object {
        $_.HasPrivateKey -and $_.NotBefore -le $taskNow -and $_.NotAfter -gt $taskNow -and
        $_.Subject -ne $_.Issuer
    })
    if ($taskCertificates.Count -eq 1) {
        $CertificateThumbprint = $taskCertificates[0].Thumbprint
    } elseif ($taskCertificates.Count -eq 0) {
        throw 'No valid code-signing certificate found in Cert:\CurrentUser\My.'
    } else {
        throw 'Multiple certificates found. Specify -CertificateThumbprint for the intended public code-signing certificate.'
    }
}
if ($Publish -and -not $CertificateThumbprint) {
    throw 'Publishing requires an explicit public CertificateThumbprint (parameter or FILEOPS_SIGN_CERT_SHA1).'
}
if (-not $SkipSmartCardService) {
    $taskCardService = Get-Service -Name SCardSvr -ErrorAction Stop
    if ($taskCardService.Status -ne 'Running') {
        $taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $taskPrincipal = [Security.Principal.WindowsPrincipal]::new($taskIdentity)
        if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'Run this script directly in your administrator PowerShell to start SCardSvr. No automatic elevation is performed.'
        }
        Start-Service -Name SCardSvr -ErrorAction Stop
        $taskCardService.WaitForStatus('Running', [TimeSpan]::FromSeconds(15))
    }
}
if (-not $SignToolPath) {
    $taskLocalSignTool = Join-Path $taskProjectRoot 'tools\_local\signing-tools\signtool.exe'
    if (Test-Path -LiteralPath $taskLocalSignTool -PathType Leaf) { $SignToolPath = $taskLocalSignTool }
}
if ($SignToolPath) {
    $taskToolSignature = Get-AuthenticodeSignature -LiteralPath $SignToolPath
    if ($taskToolSignature.Status -ne 'Valid' -or
        $taskToolSignature.SignerCertificate.Subject -notlike 'CN=Microsoft Corporation,*') {
        throw 'The configured SignTool must have a valid Microsoft signature.'
    }
}
$taskPreviousThumbprint = $env:FILEOPS_SIGN_CERT_SHA1
$taskPreviousSignTool = $env:FILEOPS_SIGNTOOL_PATH
$taskBuildArguments = @($taskBuildScript, '--require-signature')
if ($BuildLauncher) { $taskBuildArguments += '--build-launcher' }
if ($Overwrite) { $taskBuildArguments += '--overwrite' }
Push-Location -LiteralPath $taskProjectRoot
try {
    $env:FILEOPS_SIGN_CERT_SHA1 = $CertificateThumbprint
    if ($SignToolPath) { $env:FILEOPS_SIGNTOOL_PATH = $SignToolPath }
    & $Python @taskBuildArguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($Publish) {
        & $Python (Join-Path $PSScriptRoot 'publish_release.py')
    }
    exit $LASTEXITCODE
}
finally {
    $env:FILEOPS_SIGN_CERT_SHA1 = $taskPreviousThumbprint
    $env:FILEOPS_SIGNTOOL_PATH = $taskPreviousSignTool
    Pop-Location
}

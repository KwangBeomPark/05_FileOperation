# Compatibility entry point: build and sign using the canonical pipeline.
# Publishing is separate; this script never pushes or creates releases.
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$CertificateThumbprint = $env:FILEOPS_SIGN_CERT_SHA1,
    [string]$SignToolPath = $env:FILEOPS_SIGNTOOL_PATH,
    [switch]$BuildLauncher,
    [switch]$Overwrite
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
    if ($taskCertificates.Count -ne 1) {
        throw 'Specify -CertificateThumbprint for the intended public code-signing certificate.'
    }
    $CertificateThumbprint = $taskCertificates[0].Thumbprint
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
    exit $LASTEXITCODE
}
finally {
    $env:FILEOPS_SIGN_CERT_SHA1 = $taskPreviousThumbprint
    $env:FILEOPS_SIGNTOOL_PATH = $taskPreviousSignTool
    Pop-Location
}

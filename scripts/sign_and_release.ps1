# Backward-compatible command; implementation belongs to sign.ps1.
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
& (Join-Path $PSScriptRoot 'sign.ps1') @PSBoundParameters
exit $LASTEXITCODE

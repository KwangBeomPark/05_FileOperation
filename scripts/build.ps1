# Standard PL Suite entry point. Unsigned files never enter release/.
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$Unsigned,
    [switch]$BuildLauncher,
    [switch]$Overwrite,
    [switch]$Publish,
    [string]$CertificateThumbprint = $env:FILEOPS_SIGN_CERT_SHA1,
    [string]$SignToolPath = $env:FILEOPS_SIGNTOOL_PATH
)
$ErrorActionPreference = 'Stop'
if (-not $Unsigned) {
    & (Join-Path $PSScriptRoot 'sign.ps1') -Python $Python -BuildLauncher:$BuildLauncher -Overwrite:$Overwrite -Publish:$Publish -CertificateThumbprint $CertificateThumbprint -SignToolPath $SignToolPath
    exit $LASTEXITCODE
}
if ($Publish) { throw 'Unsigned development files cannot be published.' }
$taskArguments = @((Join-Path $PSScriptRoot 'build_all.py'))
if ($BuildLauncher) { $taskArguments += '--build-launcher' }
if ($Overwrite) { $taskArguments += '--overwrite' }
& $Python @taskArguments
exit $LASTEXITCODE

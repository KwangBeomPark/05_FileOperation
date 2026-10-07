# Delete only explicitly recognized, older top-level binary/checksum files.
[CmdletBinding(SupportsShouldProcess)]
param([string]$KeepVersion = '')
$ErrorActionPreference = 'Stop'
$taskProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskReleaseRoot = (Resolve-Path -LiteralPath (Join-Path $taskProjectRoot 'release')).Path
if ($taskReleaseRoot -ne (Join-Path $taskProjectRoot 'release') -or
    ((Get-Item -LiteralPath $taskReleaseRoot).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Unsafe release directory; no cleanup performed.'
}
$taskManifest = Get-Content -LiteralPath (Join-Path $taskReleaseRoot 'build-manifest.json') -Raw | ConvertFrom-Json
if (-not $KeepVersion) { $KeepVersion = $taskManifest.version }
if ($KeepVersion -ne $taskManifest.version -or -not $taskManifest.authenticode_verified) {
    throw 'The protected version must match the existing verified release manifest.'
}
foreach ($taskArtifact in $taskManifest.artifacts) {
    if (-not $taskArtifact.path.StartsWith('release/')) { continue }
    $taskProtectedName = [IO.Path]::GetFileName($taskArtifact.path)
    $taskProtected = Get-Item -LiteralPath (Join-Path $taskReleaseRoot $taskProtectedName)
    if ($taskProtected.DirectoryName -ne $taskReleaseRoot -or
        ($taskProtected.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $taskProtected.Length -ne $taskArtifact.size -or
        (Get-FileHash -LiteralPath $taskProtected.FullName -Algorithm SHA256).Hash -ne $taskArtifact.sha256) {
        throw 'Protected artifact is unsafe or changed; no cleanup performed.'
    }
    $taskSignature = Get-AuthenticodeSignature -LiteralPath $taskProtected.FullName
    if ($taskSignature.Status -ne 'Valid' -or $null -eq $taskSignature.TimeStamperCertificate -or
        $taskSignature.SignerCertificate.Thumbprint -ne $taskManifest.signing_certificate_sha1) {
        throw 'Protected artifact signature is invalid; no cleanup performed.'
    }
}
$taskPattern = '^(?<prefix>IntegratedDataTool_Setup|App05_FileOps)(?:_v(?<version>\d+(?:\.\d+)*))?\.(exe(?:\.sha256)?|sha256)$'
$taskDelete = @(Get-ChildItem -LiteralPath $taskReleaseRoot -File | Where-Object {
    if ($_.Name -match $taskPattern) {
        -not $Matches.version -or ([version]$Matches.version -lt [version]$KeepVersion)
    }
})
foreach ($taskFile in $taskDelete) {
    if ($taskFile.DirectoryName -ne $taskReleaseRoot -or ($taskFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Unsafe cleanup target; no cleanup performed.'
    }
}
$taskRemoved = 0
$taskBytes = 0L
foreach ($taskFile in $taskDelete) {
    if ($PSCmdlet.ShouldProcess($taskFile.FullName, 'Permanently remove obsolete local release artifact')) {
        Remove-Item -LiteralPath $taskFile.FullName -Force -ErrorAction Stop
        $taskRemoved += 1
        $taskBytes += $taskFile.Length
    }
}
Write-Output "Removed $taskRemoved files, $taskBytes bytes. Protected version: $KeepVersion. GitHub releases and UserSetting were not touched."

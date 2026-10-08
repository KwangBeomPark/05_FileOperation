# scripts/static-check.ps1 - Static quality and contract checks for FileOps Hub
[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$SkipRuff,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Running static checks for FileOps Hub..." -ForegroundColor Cyan

# 1. PowerShell Script Syntax Verification
$psScripts = Get-ChildItem -Path $PSScriptRoot -Filter *.ps1 -File
foreach ($script in $psScripts) {
    $tokens = $null
    $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        throw "PowerShell syntax errors in $($script.FullName): $($parseErrors[0].Message)"
    }
}
Write-Host "  [OK] PowerShell script syntax verified ($($psScripts.Count) scripts)" -ForegroundColor Green

# 2. Python CompileAll, Pip Check, Unit Tests, User Data Backup, Ruff
$skipRuffPy = if ($SkipRuff) { "True" } else { "False" }
$skipTestsPy = if ($SkipTests) { "True" } else { "False" }

$scriptContent = @"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'$PSScriptRoot')))
from build_all import run_static_checks
run_static_checks(skip_ruff=$skipRuffPy, skip_tests=$skipTestsPy)
"@

& $Python -c $scriptContent
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Static checks completed successfully!" -ForegroundColor Green

# Build a link-free ZIP and verify it in a separate extracted directory.
param([string]$Root = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath $Root).Path
& "$Root\runtime\python\python.exe" "$Root\packaging\build.py" --root $Root
if ($LASTEXITCODE -ne 0) { throw 'Packaging or verification failed. See output above.' }

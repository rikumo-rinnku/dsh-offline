# =====================================================================
#  Build the offline .7z archive and git-init the dsh-offline project.
#  Run from anywhere.  Admin not required.
# =====================================================================
param(
    [string]$Root = "e:\projects\Deepseek Harness\dsh-offline",
    [string]$SevenZip = ""  # optional: path to 7z.exe, autodetect if empty
)

$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host ""; Write-Host "=== $msg ===" -ForegroundColor Cyan }
function OK($msg)  { Write-Host "    OK - $msg" -ForegroundColor Green }
function Fail($msg){ Write-Host "    FAIL - $msg" -ForegroundColor Red; throw "Build aborted" }

# ---- Resolve 7z.exe --------------------------------------------------------
Step "Resolving 7z.exe"
if ([string]::IsNullOrEmpty($SevenZip)) {
    $candidates = @(
        "C:\Program Files\7-Zip\7z.exe",
        "C:\Program Files (x86)\7-Zip\7z.exe",
        "$env:LOCALAPPDATA\Programs\7-Zip\7z.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { $SevenZip = $c; break } }
    if ([string]::IsNullOrEmpty($SevenZip)) {
        $found = Get-Command 7z.exe -ErrorAction SilentlyContinue
        if ($found) { $SevenZip = $found.Source }
    }
}
if ([string]::IsNullOrEmpty($SevenZip) -or -not (Test-Path $SevenZip)) {
    Fail "7z.exe not found. Install 7-Zip from https://www.7-zip.org/ or pass -SevenZip path."
}
OK "Using 7z: $SevenZip"

# ---- 1. Sanity checks ------------------------------------------------------
Step "1/4 Sanity checks (every required file present)"
$checks = @(
    @("$Root\start.bat",                              "start.bat entry"),
    @("$Root\runtime\node\node.exe",                  "Portable Node"),
    @("$Root\runtime\python\pythonw.exe",             "Portable Python (GUI)"),
    @("$Root\runtime\python\python.exe",              "Portable Python (CLI)"),
    @("$Root\runtime\python\Lib\tkinter\__init__.py", "Tkinter module"),
    @("$Root\runtime\python\Lib\site-packages\customtkinter\__init__.py", "CustomTkinter"),
    @("$Root\launcher\app.py",                        "GUI app source"),
    @("$Root\launcher\engine.py",                     "Engine manager source"),
    @("$Root\dsh-core\apps\cli\lib\bin.js",           "Built DSH CLI entry"),
    @("$Root\dsh-core\node_modules\.pnpm",            "DSH pnpm store root"),
    @("$Root\dsh-core\package.json",                  "DSH workspace root")
)
foreach ($c in $checks) {
    $path, $label = $c[0], $c[1]
    if (Test-Path $path) { OK $label } else { Fail "$label missing at $path" }
}

# Extra: workspace package health (either as hoisted real dirs or as pnpm links)
$wsList = @("dsh-app-boot","dsh-web-app","dsh-bundle-base","dsh-plugin-shell","dsh-plugin-python-sdk")
foreach ($name in $wsList) {
    # The hoisted + CLI's own node_modules places them at:
    $candidates = @(
        "$Root\dsh-core\node_modules\@deepseek-ai\$name",
        "$Root\dsh-core\apps\cli\node_modules\@deepseek-ai\$name",
        "$Root\dsh-core\packages\boot\app-boot"
    )
    $foundAny = $false
    foreach ($p in $candidates) {
        if (Test-Path (Join-Path $p "package.json")) {
            # confirm package.json name
            $pj = Get-Content (Join-Path $p "package.json") -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
            if ($pj -and $pj.name -match $name) { OK "Workspace pkg @deepseek-ai/$name found at $p  (name=$($pj.name))"; $foundAny = $true; break }
        }
    }
    if (-not $foundAny) {
        # Last resort: look under any node_modules/@deepseek-ai with name match
        $fallback = Get-ChildItem "$Root\dsh-core" -Recurse -Directory -Filter $name -ErrorAction SilentlyContinue -Depth 5 `
            | Where-Object { Test-Path (Join-Path $_.FullName "package.json") } | Select-Object -First 1
        if ($fallback) { OK "Workspace pkg @deepseek-ai/$name found under $($fallback.FullName)" } else { Fail "Workspace package missing: @deepseek-ai/$name" }
    }
}

# ---- 2. CLI smoke (DSH --version via portable Node) -----------------------
Step "2/4 CLI smoke test: dsh --version"
$node = "$Root\runtime\node\node.exe"
$cli  = "$Root\dsh-core\apps\cli\lib\bin.js"
$env:DSH_HOME = "$Root\.dsh-home"
New-Item -ItemType Directory -Path $env:DSH_HOME -Force | Out-Null
Push-Location "$Root\dsh-core"
try {
    $out = & $node $cli --version 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "dsh --version exited $LASTEXITCODE : $out" }
    $ver = ($out | Out-String).Trim()
    OK "DSH CLI reports version: $ver"
} finally {
    Pop-Location
}

# ---- 3. Git init -----------------------------------------------------------
Step "3/4 Git init the project (source code only, runtime/dsh-core ignored)"
Push-Location $Root
try {
    if (-not (Test-Path ".git")) {
        git init -q
        OK "Initialized fresh empty git repo at $Root"
    } else {
        OK "Git repo already exists. Skipping init."
    }
    git status --short | Select-Object -First 20
} finally {
    Pop-Location
}

# ---- 4. Create .7z archive -------------------------------------------------
Step "4/4 Create offline .7z archive"
$archiveDir = Split-Path $Root -Parent
$archiveName = "dsh-offline-portable.7z"
$archivePath = Join-Path $archiveDir $archiveName

# Delete previous archive if present
if (Test-Path $archivePath) { Remove-Item $archivePath -Force; OK "Removed old archive" }

# Run 7z: ultra compression, 4 threads.
# We archive the CONTENTS of dsh-offline so user unzips and sees start.bat
# directly at top level.
# Exclude: git, user runtime data (DSH_HOME, caches, logs), build scripts.
& $SevenZip a -t7z -mx=9 -m0=lzma2:d=64m:fb=64 -mmt=4 -bb0 -bsp1 -bso0 `
    $archivePath `
    "$Root\*" `
    '-x!\.git\*' `
    '-x!\.dsh-home\*' `
    '-x!\.cache\*' `
    '-x!\logs\*' `
    '-x!\_pack.ps1'

if ($LASTEXITCODE -ne 0) { Fail "7z exited with code $LASTEXITCODE" }

$sizeMB = [math]::Round((Get-Item $archivePath).Length / 1MB, 0)
OK "Archive written: $archivePath  ($sizeMB MB)"

# ---- Summary ---------------------------------------------------------------
Write-Host ""
Write-Host "==========================================================="  -ForegroundColor Green
Write-Host "  BUILD FINISHED"                                                   -ForegroundColor Green
Write-Host "==========================================================="  -ForegroundColor Green
Write-Host "  Offline archive: $archivePath"
Write-Host "  Archive size:    ${sizeMB} MB"
Write-Host "  User entry:      double-click start.bat"
Write-Host "  Git repo:        initialized inside $Root"
Write-Host "==========================================================="  -ForegroundColor Green

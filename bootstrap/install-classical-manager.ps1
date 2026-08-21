<#
.SYNOPSIS
    Classical Manager - bootstrap installer for Windows.

.DESCRIPTION
    Downloads the current source from GitHub and runs the real installer,
    then removes what it downloaded. Nothing to clone, and no Git required.

    This script installs nothing by itself: it fetches, verifies the archive
    looks like the project, and hands over to install.bat, which is what asks
    the questions and creates the shortcuts.

    It deliberately does NOT install Python. That is a system-wide change no
    bootstrap should make unasked; if Python is missing it says so and stops.

.PARAMETER Ref
    Branch or tag to install. Defaults to master.

.EXAMPLE
    .\install-classical-manager.ps1
    .\install-classical-manager.ps1 -Ref v3.11
#>

[CmdletBinding()]
param(
    [string]$Ref = "master"
)

$ErrorActionPreference = "Stop"
$Repo = "regregoryallen/ClassicalManager"
$RequiredMajor = 3
$RequiredMinor = 12

function Write-Info    { param($m) Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Ok      { param($m) Write-Host " OK   $m" -ForegroundColor Green }
function Write-Failure { param($m) Write-Host "[ERROR] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "Classical Manager - bootstrap installer" -ForegroundColor White
Write-Host ""

# --- Python ------------------------------------------------------------------
# Checked before anything is downloaded, so the failure that needs a human
# decision happens first.
function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        try {
            $check = "import sys; sys.exit(0 if sys.version_info >= ($RequiredMajor, $RequiredMinor) else 1)"
            & $exe.Source -c $check 2>$null
            if ($LASTEXITCODE -eq 0) { return $exe.Source }
        } catch { continue }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Failure "Python $RequiredMajor.$RequiredMinor or newer is required and was not found."
    Write-Host ""
    Write-Host "  Install it from https://www.python.org/downloads/"
    Write-Host "    - tick 'Add python.exe to PATH'"
    Write-Host "    - leave 'tcl/tk and IDLE' ticked (the GUI needs it)"
    Write-Host ""
    Write-Host "  Or, from a terminal:  winget install Python.Python.3.12"
    Write-Host ""
    Write-Host "Then run this script again."
    exit 1
}
Write-Ok "Found $(& $python --version)"

# --- Fetch -------------------------------------------------------------------
$temp = Join-Path ([System.IO.Path]::GetTempPath()) "classical-manager-boot-$(Get-Random)"
New-Item -ItemType Directory -Path $temp -Force | Out-Null

try {
    $archive = Join-Path $temp "source.zip"

    Write-Info "Downloading $Repo ($Ref)..."
    # TLS 1.2 explicitly: Windows PowerShell 5.1 still defaults to SSL3/TLS1,
    # which GitHub refuses, and the failure looks like a network error.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $downloaded = $false
    # A tag lives under refs/tags, a branch under refs/heads.
    foreach ($kind in @("heads", "tags")) {
        $url = "https://codeload.github.com/$Repo/zip/refs/$kind/$Ref"
        try {
            Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
            $downloaded = $true
            break
        } catch { continue }
    }
    if (-not $downloaded) {
        Write-Failure "Could not download $Ref from $Repo. Check the name and your connection."
        exit 1
    }

    if (-not (Test-Path $archive) -or (Get-Item $archive).Length -eq 0) {
        Write-Failure "The download is empty. Check your connection and retry."
        exit 1
    }
    Write-Ok ("Downloaded {0:N1} MB" -f ((Get-Item $archive).Length / 1MB))

    Write-Info "Extracting..."
    try {
        Expand-Archive -Path $archive -DestinationPath $temp -Force
    } catch {
        Write-Failure "The download is not a valid archive. Check your connection and retry."
        exit 1
    }

    $sourceDir = Get-ChildItem -Path $temp -Directory |
                 Where-Object { $_.Name -like "ClassicalManager-*" } |
                 Select-Object -First 1
    if (-not $sourceDir) {
        Write-Failure "Unexpected archive layout - no ClassicalManager-* directory inside."
        exit 1
    }

    # Never run something out of an archive without checking it is what was
    # asked for. These are the files the real install depends on.
    foreach ($required in @("install.bat", "main.py", "requirements.txt")) {
        if (-not (Test-Path (Join-Path $sourceDir.FullName $required))) {
            Write-Failure "Archive does not look like Classical Manager (missing $required). Nothing has been installed."
            exit 1
        }
    }
    Write-Ok "Archive verified"

    # --- Hand over -----------------------------------------------------------
    Write-Host ""
    Write-Info "Starting the installer..."
    Write-Host ""

    Push-Location $sourceDir.FullName
    try {
        # cmd /c, not the .bat directly: install.bat uses delayed expansion
        # and returns an exit code that PowerShell would otherwise discard.
        & cmd /c "install.bat"
        $installerCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    if ($installerCode -ne 0) {
        Write-Failure "The installer exited with code $installerCode."
        exit $installerCode
    }
}
finally {
    # Runs on success, on failure and on Ctrl-C alike.
    if (Test-Path $temp) {
        Remove-Item -Path $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Ok "Bootstrap finished; downloaded files removed."

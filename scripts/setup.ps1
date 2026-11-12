# One-shot setup for Windows (PowerShell): Python 3.12 -> Poetry -> the Python
# packages, then `door doctor --fix`, which installs the rest (Tectonic, the claude
# CLI) and checks that the MCP server starts. Asks once up front;
# each step then shows a spinner and a checkmark. Safe to re-run.
#
#   .\scripts\setup.ps1              ask once, then install what is missing
#   .\scripts\setup.ps1 --yes        install without asking
#
# Then open Claude Code here (`claude`) and say /onboard.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$Repo = (Get-Location).Path
$Frames = @([char]0x280B, [char]0x2819, [char]0x2839, [char]0x2838, [char]0x283C, [char]0x2834, [char]0x2826, [char]0x2827, [char]0x2807, [char]0x280F)
$Check = [char]0x2713
$Cross = [char]0x2717

function Fail($message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

# Run a script block in the background with a yellow spinner, then a green checkmark (or a red cross,
# the output's tail, and stop). A native command's non-zero exit fails the step.
function Step($label, [scriptblock]$block) {
    $job = Start-Job -ArgumentList $Repo, $block.ToString() -ScriptBlock {
        param($repo, $code)
        Set-Location $repo
        $global:LASTEXITCODE = 0
        & ([scriptblock]::Create($code)) 2>&1
        if ($LASTEXITCODE) { throw "exited $LASTEXITCODE" }
    }
    $i = 0
    while ($job.State -eq "Running") {
        Write-Host -NoNewline "`r  "
        Write-Host -NoNewline $Frames[$i++ % 10] -ForegroundColor Yellow
        Write-Host -NoNewline " $label"
        Start-Sleep -Milliseconds 100
    }
    Write-Host -NoNewline "`r$(' ' * ($label.Length + 6))`r"
    $output = Receive-Job $job -ErrorAction SilentlyContinue 2>&1 | Out-String
    $failed = $job.State -ne "Completed"
    Remove-Job $job -Force
    if ($failed) {
        Write-Host -NoNewline "  "; Write-Host -NoNewline $Cross -ForegroundColor Red; Write-Host " $label"
        ($output -split "`n" | Select-Object -Last 20) | ForEach-Object { Write-Host "      $_" }
        Fail "$label failed - fix the above and re-run .\scripts\setup.ps1"
    }
    Mark-Done $label
}

# A green checkmark, then the rest of the line.
function Mark-Done($text) { Write-Host -NoNewline "  "; Write-Host -NoNewline $Check -ForegroundColor Green; Write-Host " $text" }
function Done($label) { Mark-Done ("{0,-22}already installed" -f $label) }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:APPDATA\Python\Scripts"
}

function Py-Version($exe, $flag) {
    try { & $exe @($flag | Where-Object { $_ }) -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>$null } catch { $null }
}

# A Python 3.12, and any Python 3.9+ (enough to run Poetry's installer).
$Py312 = $null
$Py = $null
foreach ($candidate in @(@("py", "-3.12"), @("py", $null), @("python", $null))) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $version = Py-Version $candidate[0] $candidate[1]
    if (-not $version) { continue }
    if ($version -like "3.12.*" -and -not $Py312) { $Py312 = $candidate }
    if ([int]($version.Split(".")[1]) -ge 9 -and $version -like "3.*" -and -not $Py) { $Py = $candidate }
}

$Yes = $args -contains "--yes"
Write-Host "door setup installs whatever of these is missing:"
Write-Host "  Python 3.12, Poetry, the Python packages, Tectonic (LaTeX), the claude CLI"
if (-not $Yes) {
    $answer = Read-Host "Continue? [Y/n]"
    if ($answer -match '^[Nn]') { Fail "Nothing installed." }
}
Write-Host ""

# No Python at all: winget's 3.12 (which also gives Poetry's installer something to run on).
if (-not $Py) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "No Python found. Install Python 3.12 from https://www.python.org/downloads/ and re-run .\scripts\setup.ps1"
    }
    Step "Python 3.12" { winget install --exact --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent }
    Refresh-Path
    $Py = @("py", "-3.12")
    $Py312 = $Py
}

if (Get-Command poetry -ErrorAction SilentlyContinue) {
    Done "Poetry"
} else {
    $installer = "(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | & '$($Py[0])' $($Py[1]) -"
    Step "Poetry" ([scriptblock]::Create($installer))
    Refresh-Path
    if (-not (Get-Command poetry -ErrorAction SilentlyContinue)) {
        Fail "Poetry installed but not on PATH - open a new terminal and re-run .\scripts\setup.ps1"
    }
}

# poetry.lock is written by Poetry 2 and pyproject.toml uses the [project] table;
# Poetry 1.x misreads both and fails `poetry install` with a misleading lock error.
# `poetry python install` (a Python with no admin rights) arrived in 2.1.
$poetryVersion = [regex]::Match((poetry --version), '\d+(\.\d+)*').Value
$parts = $poetryVersion.Split('.')
$upgrade = "Upgrade it with ``poetry self update`` (or reinstall from https://python-poetry.org/docs/#installation), then re-run .\scripts\setup.ps1"
if ([int]$parts[0] -lt 2) { Fail "Poetry $poetryVersion is too old: door needs Poetry 2 or later. $upgrade" }

if ($Py312) {
    Done "Python 3.12"
} else {
    if ([int]$parts[0] -eq 2 -and [int]$parts[1] -lt 1) { Fail "Poetry $poetryVersion cannot install Python 3.12 (that needs Poetry 2.1+). $upgrade" }
    Step "Python 3.12" { poetry python install 3.12 }
}

Step "Python packages" { poetry env use 3.12; if ($LASTEXITCODE) { return }; poetry install }

# Tectonic, the claude CLI, the MCP server check: same list style.
$rest = @($args)
if (-not $Yes) { $rest = @("--yes") + $rest }
& .\door.cmd doctor --fix @rest
exit $LASTEXITCODE

# Windows twin of bundle-python.sh (#355, #223): builds app\resources\ for x64 Windows.
#   python\   python-build-standalone 3.12 (python.exe at its root) with door's locked packages, by hash, wheels only
#   door\   src\, .claude\agents\{tailor,reviewer,matcher}.md and profile.example\, as in a checkout
#   bin\      tectonic.exe
# Pinned in scripts\bundle.lock.json; downloads cached in app\.bundle-cache\ (DOOR_BUNDLE_CACHE).
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$App = Resolve-Path (Join-Path $PSScriptRoot '..')
$Repo = Resolve-Path (Join-Path $App '..')
$Out = Join-Path $App 'resources'
$Cache = if ($env:DOOR_BUNDLE_CACHE) { $env:DOOR_BUNDLE_CACHE } else { Join-Path $App '.bundle-cache' }
$Lock = Get-Content (Join-Path $App 'scripts\bundle.lock.json') -Raw | ConvertFrom-Json
$Triple = 'x86_64-pc-windows-msvc'
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw "bundle-python.ps1: only x64 Windows is packaged (quickjs has no arm64 wheel)" }

function Fetch([string]$Url, [string]$Want) {
  New-Item -ItemType Directory -Force -Path $Cache | Out-Null
  $File = Join-Path $Cache ([uri]::UnescapeDataString(($Url -split '/')[-1]))
  if (-not (Test-Path $File) -or (Get-FileHash $File -Algorithm SHA256).Hash.ToLower() -ne $Want) {
    Write-Host "downloading $(Split-Path $File -Leaf)"
    Invoke-WebRequest -Uri $Url -OutFile "$File.part"
    Move-Item -Force "$File.part" $File
  }
  $Got = (Get-FileHash $File -Algorithm SHA256).Hash.ToLower()
  if ($Got -ne $Want) { throw "checksum mismatch for ${File}: $Got, wanted $Want" }
  return $File
}

if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force -Path (Join-Path $Out 'bin'), (Join-Path $Out 'door\.claude\agents') | Out-Null

# 1. the Python runtime
$Py = $Lock.python
$PyUrl = $Py.url.Replace('{tag}', $Py.tag).Replace('{version}', $Py.version).Replace('{triple}', $Triple)
tar -xzf (Fetch $PyUrl $Py.sha256.$Triple) -C $Out
$Python = Join-Path $Out 'python\python.exe'

# 2. door's packages, from poetry.lock's main group, by hash, wheels only
$Req = Join-Path $Cache 'requirements.txt'
& $Python (Join-Path $App 'scripts\lock_requirements.py') (Join-Path $Repo 'poetry.lock') | Set-Content -Encoding utf8 $Req
$env:PIP_CACHE_DIR = Join-Path $Cache 'pip'
& $Python -s -m pip install --quiet --disable-pip-version-check --no-deps --require-hashes --only-binary=:all: --no-compile -r $Req
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

# 3. door itself, laid out as in a checkout
robocopy (Join-Path $Repo 'src') (Join-Path $Out 'door\src') /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
foreach ($Agent in 'tailor.md', 'reviewer.md', 'matcher.md') { Copy-Item (Join-Path $Repo ".claude\agents\$Agent") (Join-Path $Out 'door\.claude\agents') }
robocopy (Join-Path $Repo 'profile.example') (Join-Path $Out 'door\profile.example') /E /NFL /NDL /NJH /NJS | Out-Null

# 4. Tectonic
$Tt = $Lock.tectonic
$TtUrl = $Tt.url.Replace('{version}', $Tt.version).Replace('{triple}', $Triple).Replace('{ext}', 'zip')
Expand-Archive -Force -Path (Fetch $TtUrl $Tt.sha256.$Triple) -DestinationPath (Join-Path $Out 'bin')

# 5. trim, drop pip, compile once (the app runs with PYTHONDONTWRITEBYTECODE)
$Lib = Join-Path $Out 'python\Lib'
foreach ($Dir in 'test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'site-packages\pip') { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $Lib $Dir) }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $Out 'python\tcl')
Get-ChildItem (Join-Path $Lib 'site-packages') -Directory -Filter 'pip-*.dist-info' | Remove-Item -Recurse -Force
Get-ChildItem (Join-Path $Lib 'site-packages') -Recurse -Directory -Include 'tests', 'test' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
& $Python -s -m compileall -q -j 0 $Lib (Join-Path $Out 'door\src') | Out-Null
Write-Host "bundled for $Triple into $Out"

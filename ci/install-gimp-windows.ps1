# Installs GIMP from gimp.org's installer on a Windows runner: pinned version, SHA-256 verified (ADR 0008).
$ErrorActionPreference = "Stop"
$version = "3.2.6"
$sha256 = "9337CCCBC01D4098EE7A3DAB215B3AFBE6ECE99C5287C92441D6F12CF541EBCA"
$installer = Join-Path $env:RUNNER_TEMP "gimp-setup.exe"
Invoke-WebRequest -Uri "https://download.gimp.org/gimp/v3.2/windows/gimp-$version-setup.exe" -OutFile $installer
$hash = (Get-FileHash $installer -Algorithm SHA256).Hash
if ($hash -ne $sha256) { throw "checksum mismatch: $hash" }
# machine-wide install in the default folder (C:\Program Files\GIMP 3), as most users do
Start-Process $installer -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/ALLUSERS' -Wait
$console = Join-Path $env:ProgramFiles "GIMP 3\bin\gimp-console-3.2.exe"
if (-not (Test-Path $console)) { throw "gimp-console not found at $console" }
& $console --version

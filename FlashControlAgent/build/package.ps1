param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\dist"),
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildRoot = Join-Path $root "build-artifacts"
$pyiWork = Join-Path $buildRoot "pyinstaller"
$pyiSpec = Join-Path $buildRoot "spec"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
New-Item -ItemType Directory -Force -Path $pyiWork | Out-Null
New-Item -ItemType Directory -Force -Path $pyiSpec | Out-Null

if (-not $SkipDependencyInstall) {
    python -m pip install -r (Join-Path $root "requirements-build.txt")
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --noconsole `
    --name FlashControlAgentService `
    --hidden-import win32timezone `
    --hidden-import main `
    --hidden-import delivery_queue `
    --collect-all pywin32 `
    --distpath $OutputDir `
    --workpath $pyiWork `
    --specpath $pyiSpec `
    (Join-Path $root "service.py")

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name FlashControlAgentBuild `
    --distpath $OutputDir `
    --workpath (Join-Path $buildRoot "pyinstaller-collector") `
    --specpath (Join-Path $buildRoot "spec-collector") `
    (Join-Path $root "main.py")

$serviceBundle = Join-Path $OutputDir "FlashControlAgentService"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --uac-admin `
    --name FlashControlAgentInstaller `
    --distpath $OutputDir `
    --workpath (Join-Path $buildRoot "pyinstaller-installer") `
    --specpath (Join-Path $buildRoot "spec-installer") `
    --add-data "${serviceBundle};FlashControlAgentService" `
    (Join-Path $root "installer.py")

Copy-Item (Join-Path $root "agent_config.example.json") (Join-Path $OutputDir "agent_config.json") -Force

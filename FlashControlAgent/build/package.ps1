param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "..\dist"),
    [string]$ServerUrl = "",
    [string]$HeartbeatUrl = "",
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
    --collect-all pywin32 `
    --distpath $OutputDir `
    --workpath $pyiWork `
    --specpath $pyiSpec `
    (Join-Path $root "service.py")

$serviceBundle = Join-Path $OutputDir "FlashControlAgentService"
$configPath = Join-Path $OutputDir "agent_config.json"
Copy-Item (Join-Path $root "agent_config.example.json") $configPath -Force
if ($ServerUrl) {
    python -c "import json,sys; p=sys.argv[1]; d=json.load(open(p,encoding='utf-8')); d['server_url']=sys.argv[2]; json.dump(d, open(p,'w',encoding='utf-8'), indent=2); open(p,'a',encoding='utf-8').write(chr(10))" $configPath $ServerUrl
}
if ($HeartbeatUrl) {
    python -c "import json,sys; p=sys.argv[1]; d=json.load(open(p,encoding='utf-8')); d['heartbeat_url']=sys.argv[2]; json.dump(d, open(p,'w',encoding='utf-8'), indent=2); open(p,'a',encoding='utf-8').write(chr(10))" $configPath $HeartbeatUrl
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --uac-admin `
    --name FlashControlAgentInstaller `
    --hidden-import heartbeat `
    --distpath $OutputDir `
    --workpath (Join-Path $buildRoot "pyinstaller-installer") `
    --specpath (Join-Path $buildRoot "spec-installer") `
    --add-data "${serviceBundle};FlashControlAgentService" `
    --add-data "${configPath};." `
    (Join-Path $root "installer.py")

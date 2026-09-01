# FlashControlAgent packaging

## Build

```powershell
cd FlashControlAgent
.\build\package.ps1
```

This builds:

- `FlashControlAgentService.exe`
- `FlashControlAgentBuild.exe`
- `FlashControlAgentInstaller.exe`
- `agent_config.json`

## Install

Run the installer **as Administrator**:

```powershell
.\FlashControlAgentInstaller.exe install --server-url "https://server.example/api/flashcontrol"
```

Reinstall:

```powershell
.\FlashControlAgentInstaller.exe reinstall --server-url "https://server.example/api/flashcontrol"
```

## Logs

- Installer log: `FlashControlAgentInstaller.log` next to the installer EXE
- Service log: `C:\ProgramData\FlashControlAgent\FlashControlAgent.log`
- Bootstrap log (early startup): `C:\ProgramData\FlashControlAgent\FlashControlAgent.bootstrap.log`

## Install layout

After install, `C:\ProgramData\FlashControlAgent` contains:

- `FlashControlAgentService.exe`
- `_internal/` — PyInstaller runtime dependencies, this folder is required
- `agent_config.json`

## Uninstall

```powershell
.\FlashControlAgentInstaller.exe uninstall
```

## Kaspersky rollout

Package the contents of `dist` and run `FlashControlAgentInstaller.exe` with the needed parameters on target machines.

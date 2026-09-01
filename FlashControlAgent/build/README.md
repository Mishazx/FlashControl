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
- Persistent delivery queue: `C:\ProgramData\FlashControlAgent\FlashControlAgent.queue.db`

## Install layout

After install, `C:\ProgramData\FlashControlAgent` contains:

- `FlashControlAgentService.exe`
- `_internal/` — PyInstaller runtime dependencies, this folder is required
- `agent_config.json`

## Delivery guarantees

Each Observation is committed to the local SQLite queue before the first HTTP
request. A successful 2xx response removes it from the queue. Network and server
errors keep the original payload and `event_id` for an exponential-backoff retry.
If the service stops after the server accepted an event but before the local
acknowledgement, the event is sent again; the Main Server's unique `event_id`
constraint makes that retry idempotent.

The queue never silently evicts old audit events. When `queue_max_items` is
reached, collection fails visibly in the service log until queued events can be
delivered or an administrator raises the configured limit.

## Uninstall

```powershell
.\FlashControlAgentInstaller.exe uninstall
```

## Kaspersky rollout

Package the contents of `dist` and run `FlashControlAgentInstaller.exe` with the needed parameters on target machines.

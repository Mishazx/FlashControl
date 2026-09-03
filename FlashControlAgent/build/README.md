# FlashControlAgent packaging

## Build

```powershell
cd FlashControlAgent
.\build\package.ps1
```

This builds:

- `FlashControlAgentService.exe`
- `FlashControlAgentBuild.exe`
- `FlashControlAgentDump.exe` — test helper: scans USB sticks and writes the JSON the agent would send
- `FlashControlAgentInstaller.exe`
- `agent_config.json`

## Test dump

Run next to a plugged-in USB stick:

```powershell
.\FlashControlAgentDump.exe
```

This writes `FlashControlAgentDump.json` next to the EXE — the same observation payload the service would queue and POST. Optional live send:

```powershell
.\FlashControlAgentDump.exe --send "https://server.example/api/v1/observations" --machine-token "..."
```

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
- Persistent delivery queue: `C:\ProgramData\FlashControlAgentState\FlashControlAgent.queue.db`

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

The delivery queue lives in a separate state directory next to the install
folder, so reinstalling the service does not wipe queued observations.

The queue never silently evicts old audit events. When `queue_max_items` is
reached, collection fails visibly in the service log until queued events can be
delivered or an administrator raises the configured limit.

## Uninstall

```powershell
.\FlashControlAgentInstaller.exe uninstall
```

## Kaspersky rollout

Package the contents of `dist` and run `FlashControlAgentInstaller.exe` with the needed parameters on target machines.

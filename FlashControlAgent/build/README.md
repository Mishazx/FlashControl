# FlashControlAgent packaging

## Build

```powershell
cd FlashControlAgent
.\build\package.ps1 -ServerUrl "https://collector.example.local"
```

This bakes the collector address into `agent_config.json` (and into the
installer). Pass either a domain/IP root such as
`https://collector.example.local` or `https://192.168.10.15`; the agent adds
`/api/v1/observations` itself. The full endpoint is also supported for backward
compatibility. After that, install is just:

```powershell
.\FlashControlAgentInstaller.exe install
```

No `--machine-token` and no `--server-url`. The service tells the collector who it is (`hostname`, domain, IPs, stable `agent_id`) via `POST /api/v1/agents/enroll`, gets a per-machine token, and stores it in `FlashControlAgentState\FlashControlAgent.token`. Enrollment is allowed only from the collector's configured networks.

This builds:

- `FlashControlAgentService.exe`
- `FlashControlAgentInstaller.exe`
- `agent_config.json`

## Install

Run the installer **as Administrator**. If the package was built with `-ServerUrl`, no extra arguments are required:

```powershell
.\FlashControlAgentInstaller.exe install
```

Optional overrides for a one-off machine:

```powershell
.\FlashControlAgentInstaller.exe install --server-url "https://collector.example.local"
```

`--machine-token` is only for a shared development token; the normal path is enroll. Production mTLS still uses `--client-cert-file`.

## Logs

- Installer log: `FlashControlAgentInstaller.log` next to the installer EXE
- Service log: `C:\ProgramData\FlashControlAgent\FlashControlAgent.log`
- Bootstrap log (early startup): `C:\ProgramData\FlashControlAgent\FlashControlAgent.bootstrap.log`
- Persistent delivery queue: `C:\ProgramData\FlashControlAgentState\FlashControlAgent.queue.db`
- Stable agent UUID: `C:\ProgramData\FlashControlAgentState\FlashControlAgent.id`
- Issued machine token: `C:\ProgramData\FlashControlAgentState\FlashControlAgent.token`

## Install layout

After install, `C:\ProgramData\FlashControlAgent` contains:

- `FlashControlAgentService.exe`
- `_internal/` — PyInstaller runtime dependencies, this folder is required
- `agent_config.json`

## Delivery guarantees

## Device change notifications

The Windows service registers for `GUID_DEVINTERFACE_DISK` notifications. A
disk arrival or removal wakes the service, waits two seconds by default for
PnP/storage initialization, rescans USB mass-storage, and queues `connected`
or `disconnected` Observations. `device_event_debounce_seconds` in
`agent_config.json` changes that delay. The ordinary `interval_seconds` scan
remains a fallback when Windows notifications are unavailable.

The agent is configured with one Collector API address. Deployment or DNS decides
whether that address is the Main Server or a local Proxy Collector; the agent
does not keep a proxy list and does not perform route selection.

Each Observation is committed to the local SQLite queue before the first HTTP
request. A successful 2xx response removes it from the queue. Network and server
errors keep the original payload and `event_id` for an exponential-backoff retry.
If the service stops after the server accepted an event but before the local
acknowledgement, the event is sent again; the Main Server's unique `event_id`
constraint makes that retry idempotent.

The delivery queue and agent UUID live in a separate state directory next to
the install folder, so reinstalling the service does not wipe queued
observations or change the enrolled agent identity.

The queue never silently evicts old audit events. When `queue_max_items` is
reached, collection fails visibly in the service log until queued events can be
delivered or an administrator raises the configured limit.

## Uninstall

```powershell
.\FlashControlAgentInstaller.exe uninstall
```

## Kaspersky rollout

Package the contents of `dist` and run `FlashControlAgentInstaller.exe install`
on target machines. Build a separate package per site with that site's
domain or IP in `-ServerUrl`. For `https://` over an IP address, the server TLS
certificate must contain that IP address in its Subject Alternative Name (SAN).

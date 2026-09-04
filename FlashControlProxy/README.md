# FlashControl Proxy Collector

The Proxy is a specialized store-and-forward service. It accepts
`POST /api/v1/agents/enroll`, `POST /api/v1/observations` and
`POST /api/v1/agents/heartbeat`, checks the agent identity and source CIDR,
commits data to a durable SQLite WAL queue, returns `202`, and forwards queued
items to Main with its own machine identity.

Enrollment requires both an allowed source network and a bootstrap token in
`X-FlashControl-Enroll-Token`. The Proxy issues a per-machine token bound to
that hostname; only that issued token is accepted for subsequent ingest.

An agent has one configured Collector URL and does not distinguish Proxy from
Main. On an intermediate site, that URL resolves to this local Proxy; on the
central network it resolves to Main. The Proxy owns the upstream connection.

Development configuration:

```text
FLASHCONTROL_PROXY_ID=11111111-1111-1111-1111-111111111111
FLASHCONTROL_PROXY_QUEUE=/data/proxy.db
FLASHCONTROL_PROXY_ALLOWED_NETWORKS=10.10.0.0/16,10.30.10.0/24
FLASHCONTROL_PROXY_AUTH_MODE=token
FLASHCONTROL_PROXY_ENROLL_TOKEN=development-enrollment-secret
FLASHCONTROL_PROXY_MAIN_TOKEN=development-main-secret
FLASHCONTROL_MAIN_OBSERVATIONS_URL=https://main/api/v1/observations
FLASHCONTROL_MAIN_HEARTBEAT_URL=https://main/api/v1/agents/heartbeat
```

`FLASHCONTROL_PROXY_AGENT_TOKEN` is accepted as a backwards-compatible alias
for `FLASHCONTROL_PROXY_ENROLL_TOKEN`, but is never accepted to ingest data.

For production set `FLASHCONTROL_PROXY_AUTH_MODE=mtls`, configure
`FLASHCONTROL_PROXY_TRUSTED_MTLS_PROXIES`, and map certificate fingerprints to
agent UUIDs in `FLASHCONTROL_PROXY_MTLS_AGENTS`. The TLS terminator must remove
all client-supplied `X-FlashControl-Client-*` headers and inject them only after
successful certificate verification.

Proxy-to-Main mTLS uses `FLASHCONTROL_PROXY_MAIN_CA_FILE`,
`FLASHCONTROL_PROXY_MAIN_CLIENT_CERT`, and
`FLASHCONTROL_PROXY_MAIN_CLIENT_KEY`. A development token may not be used in
production.

Build from the repository root:

```powershell
docker build -f FlashControlProxy/Dockerfile -t flashcontrol-proxy .
```

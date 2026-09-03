# FlashControl Main Server

FlashControl ingest, identity correlation, audit API, and Web UI server. It
retains raw endpoint facts and records every physical-device correlation
decision with its evidence and confidence.

## Run with Docker

```powershell
cd FlashControlPIBServer
docker compose up --build
```

Endpoints:

- `GET /health/live`
- `GET /health/ready`
- `POST /api/v1/observations`
- OpenAPI: `GET /docs`
- Web UI: `GET /`

The ingest endpoint accepts either one Observation or the complete scan document
produced by `FlashControlAgent/main.py --scan`. Reposting the same `event_id` is
safe and returns it as a duplicate.

## Local run

Development defaults to `sqlite:///./flashcontrol-dev.db`; its schema is created
automatically. Then run:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

SQLite is rejected when `FLASHCONTROL_ENVIRONMENT=production`. Production uses
PostgreSQL and requires applying migrations explicitly, in numeric order:

```text
migrations/001_initial.sql
migrations/002_identity_engine.sql
migrations/003_auth.sql
migrations/005_agents.sql
migrations/006_machine_auth.sql
migrations/007_agent_enroll.sql
```

Every accepted Observation is linked to a computer, evaluated by the identity
engine, assigned to a provisional or known physical device, and linked to a
media state. The raw Observation remains unchanged. Identity decisions retain
their classification, confidence, candidate device, and machine-readable
reasons so rules can be audited and recalculated later.

Identity linking is deliberately conservative:

- `SAME` may link automatically when hardware and media agree on the same
  computer;
- `LIKELY_SAME` records a candidate but does not merge devices automatically;
- simultaneous matching evidence on different computers is recorded as
  `SERIAL_COLLISION` and never merged;
- matching media with different hardware is `CLONE_SUSPECTED`;
- changed media identity with only ambiguous hardware evidence remains
  `UNKNOWN` until more context or an analyst decision is available.

This means a format/repartition can produce an unresolved candidate rather than
a false automatic merge. The original facts and decision reasons are retained
so the association can be recalculated when disconnect/connect context or more
evidence becomes available.

## Read-only audit API

The server exposes authenticated paginated read endpoints:

- `GET /api/v1/dashboard` for aggregate counters and identity results;
- `GET /api/v1/computers` and `GET /api/v1/computers/{id}`;
- `GET /api/v1/devices` and `GET /api/v1/devices/{id}`;
- `GET /api/v1/observations` and `GET /api/v1/observations/{event_id}`;
- `GET /api/v1/identity-decisions`;
- `GET /api/v1/identity-alerts` for collisions and clone suspects.
- `GET /api/v1/audit-log` for `admin` and `security` roles.

List endpoints accept `limit` (1–200) and `offset`, return `total`, and provide
resource-specific filters in OpenAPI. Observation lists return summaries; the
detail endpoint returns the immutable raw Observation.

All read endpoints and the Web UI require an authenticated session. The ingest
and health endpoints are separate and remain available to agents and health
checks.

The Web UI is a dependency-free responsive SPA served by FastAPI itself. It
includes Dashboard, USB devices, computers, observations, identity alerts, and
detail drawers with media states and raw evidence. It uses no external CDN and
therefore works inside an isolated network.

## Authentication and roles

Development uses local users with salted `scrypt` password hashes. There is no
default password. Create the first account interactively:

```powershell
python -m app.manage_user create --username admin --role admin
```

Then open `http://127.0.0.1:8000/`. Sessions use a random HttpOnly cookie,
SameSite strict policy, server-side token hashes, an absolute expiry, and CSRF
protection for state-changing browser requests. Login attempts are rate-limited
and login/logout activity is written to `audit_log`.

Available roles:

- `admin`: read audit data and administrative audit log;
- `security`: read audit data and administrative audit log;
- `auditor`: read-only USB audit data without the administrative audit log.

Production rejects SQLite. Authentication is local user management with salted `scrypt` hashes and the same session/CSRF flow in every environment. Create the first account interactively:

```powershell
python -m app.manage_user create --username admin --role admin
```

## Agent heartbeat

The Windows service keeps a stable random `agent_id` in
`FlashControlAgentState/FlashControlAgent.id`. On first start it calls
`POST /api/v1/agents/enroll` with hostname, domain and current IPs. Main
issues a per-agent token if the source address is in
`FLASHCONTROL_ENROLL_NETWORKS` (in development/test an empty list allows
local enroll). The token is stored hashed; only that agent UUID can use it,
and it stays bound to the computer that enrolled.

Ingest still accepts the shared `FLASHCONTROL_DEV_MACHINE_TOKEN` so dump
helpers keep working. Production refuses token mode and requires mTLS.
The server records its version, current IPs, delivery queue size, selected
route, and last-seen time. The Web UI exposes online/offline agents and queue
backlogs. Configure `heartbeat_interval_seconds` (minimum 15 seconds); the
default is 60 seconds and an agent is shown offline after three minutes.

Heartbeat and observation ingest currently expect the deployment boundary to
protect these endpoints. In development, set the same long random
`FLASHCONTROL_DEV_MACHINE_TOKEN` on Main and `machine_token` on agents/proxies.
Production refuses this mode and requires mTLS.

The TLS terminator must validate the client certificate, strip any incoming
`X-FlashControl-Client-*` headers, and inject `X-FlashControl-Client-Verify` and
`X-FlashControl-Client-Fingerprint`. Main accepts those headers only from
`FLASHCONTROL_TRUSTED_MTLS_PROXIES`, then resolves the fingerprint through the
explicit `FLASHCONTROL_MTLS_IDENTITIES` enrollment map. Direct agents cannot
forward another identity; authenticated proxies must preserve the originating
agent UUID and both identities are stored on every observation.

The Agent tries Main first and selects a Proxy only after direct delivery
fails. When several configured CIDRs match a local address, the longest prefix
wins. The Proxy commits every item to SQLite before returning `202` and removes
it only after Main acknowledges successful delivery.

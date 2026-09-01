# FlashControl Main Server

Minimal raw Observation ingest server. It stores endpoint facts unchanged and
does not assign `physical_device_id` or merge devices yet.

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
```

Every accepted Observation is linked to a computer, evaluated by the identity
engine, assigned to a provisional or known physical device, and linked to a
media state. The raw Observation remains unchanged. Identity decisions retain
their classification, confidence, candidate device, and machine-readable
reasons so rules can be audited and recalculated later.

Identity linking is deliberately conservative:

- `SAME` may link automatically when hardware and media agree on the same
  computer, or when matching VPD83 is supported by the full hardware evidence;
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

The development and test environments expose paginated read endpoints:

- `GET /api/v1/dashboard` for aggregate counters and identity results;
- `GET /api/v1/computers` and `GET /api/v1/computers/{id}`;
- `GET /api/v1/devices` and `GET /api/v1/devices/{id}`;
- `GET /api/v1/observations` and `GET /api/v1/observations/{event_id}`;
- `GET /api/v1/identity-decisions`;
- `GET /api/v1/identity-alerts` for collisions and clone suspects.

List endpoints accept `limit` (1–200) and `offset`, return `total`, and provide
resource-specific filters in OpenAPI. Observation lists return summaries; the
detail endpoint returns the immutable raw Observation.

Unauthenticated reads are always disabled in production. Until AD/OIDC and RBAC
are implemented, production read requests return HTTP 403; ingest and health
endpoints are unaffected.

The Web UI is a dependency-free responsive SPA served by FastAPI itself. It
includes Dashboard, USB devices, computers, observations, identity alerts, and
detail drawers with media states and raw evidence. It uses no external CDN and
therefore works inside an isolated network. In production the shell can load,
but its data requests remain blocked until authentication is implemented.

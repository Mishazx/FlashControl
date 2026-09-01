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

The ingest endpoint accepts either one Observation or the complete scan document
produced by `FlashControlAgent/main.py --scan`. Reposting the same `event_id` is
safe and returns it as a duplicate.

## Local run

Set `FLASHCONTROL_DATABASE_URL`, apply `migrations/001_initial.sql`, then run:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```


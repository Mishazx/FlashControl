# Deployment to `main-flash`

This deployment intentionally uses the Docker CLI rather than Compose because
the current server has Docker but no Compose plugin. It creates:

- `flashcontrol-postgres`, backed by the named volume `flashcontrol-pgdata`;
- `flashcontrol-main`, available only on the private Docker network;
- `flashcontrol-web`, an Nginx frontend exposed on TCP port 80;
- the private Docker network `flashcontrol`;
- up to three pre-migration PostgreSQL dumps in `/opt/flashcontrol/shared/backups`.

## First deployment

Create the server-side configuration without committing secrets:

```bash
ssh main-flash
sudo mkdir -p /opt/flashcontrol/shared
sudo cp /path/to/flashcontrol.env.example /opt/flashcontrol/shared/flashcontrol.env
sudo chmod 600 /opt/flashcontrol/shared/flashcontrol.env
sudo editor /opt/flashcontrol/shared/flashcontrol.env
```

Production startup requires real HTTPS OIDC settings and an mTLS identity map.
The TLS reverse proxy must validate client certificates, remove client-supplied
`X-FlashControl-Client-*` headers, and inject the verified fingerprint headers.
The supplied Nginx configuration is for an internal HTTP pilot and deliberately
removes spoofed mTLS identity headers. Replace it with a TLS/mTLS server block
before switching the application environment to production.

From the repository root on the development machine:

```powershell
.\deploy\main-flash\push.ps1
```

For the first internal pilot, the script can generate and install database and
machine secrets automatically:

```powershell
.\deploy\main-flash\push.ps1 -BootstrapPilot
```

The generated admin password and machine token are printed once. Save them in a
password manager and configure agents with the machine token. Later accounts
can be created interactively with `python -m app.manage_user` in the application
container.

The script uploads the working tree's server/deployment files, builds a tagged
image on `main-flash`, backs up the database, applies all idempotent migrations,
starts the new container, waits for `/health/ready`, and restores the previous
application container when the health check fails.

## Subsequent updates

Run the same `push.ps1` command. Releases are stored under
`/opt/flashcontrol/releases/<UTC timestamp>`. Old images older than seven days
are pruned after a successful update. Release source directories are retained
and can be removed manually after verifying the deployment.

Useful diagnostics:

```bash
sudo docker ps
sudo docker logs --tail 100 flashcontrol-main
curl http://127.0.0.1/health/ready
```

Database data is never removed by the update script. A failed application
health check rolls the application container back, but database migrations are
forward-only; use the generated SQL dump for a database rollback.

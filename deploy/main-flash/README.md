# Deployment to `main-flash`

This deployment intentionally uses the Docker CLI rather than Compose because
the current server has Docker but no Compose plugin. It creates:

- `flashcontrol-postgres`, backed by the named volume `flashcontrol-pgdata`;
- `flashcontrol-main`, available only on the private Docker network;
- `flashcontrol-web`, an Nginx container with the React frontend built from
  `FlashControlPIBServer/web-react`, exposed on TCP port 80;
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

The web container requires a PEM TLS certificate and its private key. For an
internal pilot, create a self-signed pair once on `main-flash`:

```bash
sudo mkdir -p /opt/flashcontrol/shared/certs
sudo openssl req -x509 -newkey rsa:4096 -sha256 -nodes -days 365 \
  -keyout /opt/flashcontrol/shared/certs/tls.key \
  -out /opt/flashcontrol/shared/certs/tls.crt \
  -subj "/CN=main-flash"
sudo chmod 600 /opt/flashcontrol/shared/certs/tls.key
sudo chmod 644 /opt/flashcontrol/shared/certs/tls.crt
```

`push.ps1` uploads the deployment script; it then bind-mounts those two
server-side files into `flashcontrol-web` and publishes HTTPS on port 443.
Its web health check also uses HTTPS and accepts the self-signed certificate.
Use a certificate issued for the server's DNS name instead when it is accessed
outside the internal pilot.

Production startup uses local web users and an mTLS identity map for machine
auth. The TLS reverse proxy must validate client certificates, remove
client-supplied `X-FlashControl-Client-*` headers, and inject the verified
fingerprint headers. The supplied Nginx configuration is for an internal HTTP
pilot and deliberately removes spoofed mTLS identity headers. Replace it with a
TLS/mTLS server block before switching the application environment to
production.

From the repository root on the development machine:

```powershell
.\deploy\main-flash\push.ps1
```

For the first internal pilot, the script can generate and install database and
machine secrets automatically:

```powershell
.\deploy\main-flash\push.ps1 -BootstrapPilot
```

If the database is empty, the deploy creates a local `admin` user and prints the
password once. Save it, then configure agents with the machine token from
`flashcontrol.env`. Later accounts can be created interactively with
`python -m app.manage_user` in the application container.

To wipe PostgreSQL and start from the bootstrap schema:

```powershell
.\deploy\main-flash\push.ps1 -ResetDatabase
```

The script uploads the working tree's server/deployment files, builds tagged API
and React frontend images on `main-flash`, backs up the database, applies
`migrations/001_initial.sql`, starts the new container, waits for
`/health/ready`, and restores the previous application container when the
health check fails. `-ResetDatabase` dumps, drops, and recreates the
application database before applying that schema.

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

Ordinary updates dump PostgreSQL and apply `migrations/001_initial.sql` without
removing data. A failed application health check rolls the application
container back; database migrations are additive, so use the generated SQL dump
if you need a data rollback. Use `-ResetDatabase` only when you intentionally
want a clean catalog.

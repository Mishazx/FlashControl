#!/usr/bin/env bash
set -Eeuo pipefail

release_dir=${1:?usage: deploy.sh RELEASE_DIRECTORY [IMAGE_TAG] [--reset-database]}
shift
image_tag=$(date -u +%Y%m%d%H%M%S)
reset_database=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset-database) reset_database=true ;;
    *) image_tag=$1 ;;
  esac
  shift
done
install_dir=/opt/flashcontrol
shared_dir=$install_dir/shared
env_file=$shared_dir/flashcontrol.env
backup_dir=$shared_dir/backups
tls_dir=$shared_dir/certs
tls_cert=$tls_dir/tls.crt
tls_key=$tls_dir/tls.key
network=flashcontrol
db_container=flashcontrol-postgres
app_container=flashcontrol-main
web_container=flashcontrol-web
image=flashcontrol-main:$image_tag
frontend_image=flashcontrol-web:$image_tag
previous_container=flashcontrol-main-previous

docker_cmd=(sudo docker)

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

env_value() {
  local key=$1
  sed -n "s/^${key}=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

[[ -d "$release_dir/FlashControlPIBServer" ]] || fail "release does not contain FlashControlPIBServer"
[[ -f "$env_file" ]] || fail "missing $env_file (start from flashcontrol.env.example)"
[[ -f "$tls_cert" ]] || fail "missing TLS certificate: $tls_cert"
[[ -f "$tls_key" ]] || fail "missing TLS private key: $tls_key"

postgres_db=$(env_value POSTGRES_DB)
postgres_user=$(env_value POSTGRES_USER)
postgres_password=$(env_value POSTGRES_PASSWORD)
[[ -n "$postgres_db" && -n "$postgres_user" && -n "$postgres_password" ]] || fail "PostgreSQL settings are incomplete"
[[ "$postgres_db" != postgres ]] || fail "POSTGRES_DB cannot be postgres"
[[ "$postgres_db" =~ ^[A-Za-z0-9_-]+$ ]] || fail "POSTGRES_DB contains unsupported characters"
[[ "$postgres_user" =~ ^[A-Za-z0-9_-]+$ ]] || fail "POSTGRES_USER contains unsupported characters"
[[ "$postgres_password" =~ ^[A-Za-z0-9._~-]+$ ]] || fail "POSTGRES_PASSWORD must be URL-safe (letters, digits, . _ ~ -)"

mkdir -p "$backup_dir"
  "${docker_cmd[@]}" network inspect "$network" >/dev/null 2>&1 || \
  "${docker_cmd[@]}" network create --subnet 172.30.0.0/24 "$network" >/dev/null

if ! "${docker_cmd[@]}" container inspect "$db_container" >/dev/null 2>&1; then
  "${docker_cmd[@]}" run -d \
    --name "$db_container" \
    --restart unless-stopped \
    --network "$network" \
    --env-file "$env_file" \
    --mount source=flashcontrol-pgdata,target=/var/lib/postgresql/data \
    --health-cmd="pg_isready -U $postgres_user -d $postgres_db" \
    --health-interval=5s --health-timeout=3s --health-retries=20 \
    postgres:17-alpine >/dev/null
fi

for _ in $(seq 1 30); do
  [[ $("${docker_cmd[@]}" inspect -f '{{.State.Health.Status}}' "$db_container" 2>/dev/null) == healthy ]] && break
  sleep 2
done
[[ $("${docker_cmd[@]}" inspect -f '{{.State.Health.Status}}' "$db_container") == healthy ]] || fail "PostgreSQL did not become healthy"

backup_file=$backup_dir/flashcontrol-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
"${docker_cmd[@]}" exec -e PGPASSWORD="$postgres_password" "$db_container" \
  pg_dump -U "$postgres_user" "$postgres_db" | gzip -9 >"$backup_file"
find "$backup_dir" -maxdepth 1 -type f -name 'flashcontrol-*.sql.gz' -printf '%T@ %p\n' \
  | sort -nr | tail -n +4 | cut -d' ' -f2- | xargs -r rm -f

if [[ "$reset_database" == true ]]; then
  "${docker_cmd[@]}" exec -e PGPASSWORD="$postgres_password" "$db_container" \
    psql -v ON_ERROR_STOP=1 -U "$postgres_user" -d postgres \
    -c "DROP DATABASE IF EXISTS \"${postgres_db}\" WITH (FORCE);" \
    -c "CREATE DATABASE \"${postgres_db}\" OWNER \"${postgres_user}\";"
fi

for migration in "$release_dir"/FlashControlPIBServer/migrations/*.sql; do
  "${docker_cmd[@]}" exec -i -e PGPASSWORD="$postgres_password" "$db_container" \
    psql -v ON_ERROR_STOP=1 -U "$postgres_user" -d "$postgres_db" <"$migration"
done

"${docker_cmd[@]}" build --pull --label com.flashcontrol.component=main -t "$image" "$release_dir/FlashControlPIBServer"
"${docker_cmd[@]}" build --pull --label com.flashcontrol.component=web -t "$frontend_image" \
  -f "$release_dir/FlashControlPIBServer/Dockerfile.frontend" "$release_dir/FlashControlPIBServer"

"${docker_cmd[@]}" rm -f "$previous_container" >/dev/null 2>&1 || true
if "${docker_cmd[@]}" container inspect "$app_container" >/dev/null 2>&1; then
  "${docker_cmd[@]}" stop "$app_container" >/dev/null
  "${docker_cmd[@]}" rename "$app_container" "$previous_container"
fi

database_url="postgresql+psycopg://${postgres_user}:${postgres_password}@${db_container}:5432/${postgres_db}"
trusted_proxies=$(env_value FLASHCONTROL_TRUSTED_PROXIES)
trusted_proxies=${trusted_proxies:-172.30.0.0/24}
if ! "${docker_cmd[@]}" run -d \
  --name "$app_container" \
  --restart unless-stopped \
  --network "$network" \
  --network-alias api \
  --env-file "$env_file" \
  -e FLASHCONTROL_DATABASE_URL="$database_url" \
  -e FLASHCONTROL_TRUSTED_PROXIES="$trusted_proxies" \
  "$image" >/dev/null; then
  "${docker_cmd[@]}" rename "$previous_container" "$app_container" 2>/dev/null || true
  "${docker_cmd[@]}" start "$app_container" >/dev/null 2>&1 || true
  fail "new container could not be started; previous container restored"
fi

healthy=false
for _ in $(seq 1 30); do
  if [[ $("${docker_cmd[@]}" inspect -f '{{.State.Health.Status}}' "$app_container" 2>/dev/null) == healthy ]]; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != true ]]; then
  "${docker_cmd[@]}" logs --tail 100 "$app_container" >&2 || true
  "${docker_cmd[@]}" rm -f "$app_container" >/dev/null 2>&1 || true
  if "${docker_cmd[@]}" container inspect "$previous_container" >/dev/null 2>&1; then
    "${docker_cmd[@]}" rename "$previous_container" "$app_container"
    "${docker_cmd[@]}" start "$app_container" >/dev/null
  fi
  "${docker_cmd[@]}" restart "$web_container" >/dev/null 2>&1 || true
  fail "health check failed; previous application container restored"
fi

"${docker_cmd[@]}" rm -f "$web_container" >/dev/null 2>&1 || true
"${docker_cmd[@]}" run -d \
  --name "$web_container" \
  --restart unless-stopped \
  --network "$network" \
  -p 80:80 \
  -p 443:443 \
  --mount "type=bind,src=$tls_cert,dst=/etc/nginx/certs/tls.crt,readonly" \
  --mount "type=bind,src=$tls_key,dst=/etc/nginx/certs/tls.key,readonly" \
  --health-cmd='wget --no-check-certificate -q -O /dev/null https://127.0.0.1/health/ready || exit 1' \
  --health-interval=15s --health-timeout=3s --health-retries=4 \
  "$frontend_image" >/dev/null

web_healthy=false
for _ in $(seq 1 20); do
  if [[ $("${docker_cmd[@]}" inspect -f '{{.State.Health.Status}}' "$web_container" 2>/dev/null) == healthy ]]; then
    web_healthy=true
    break
  fi
  sleep 2
done
if [[ "$web_healthy" != true ]]; then
  "${docker_cmd[@]}" logs --tail 100 "$web_container" >&2 || true
  "${docker_cmd[@]}" rm -f "$web_container" >/dev/null 2>&1 || true
  "${docker_cmd[@]}" rm -f "$app_container" >/dev/null 2>&1 || true
  if "${docker_cmd[@]}" container inspect "$previous_container" >/dev/null 2>&1; then
    "${docker_cmd[@]}" rename "$previous_container" "$app_container"
    "${docker_cmd[@]}" start "$app_container" >/dev/null
    "${docker_cmd[@]}" run -d \
      --name "$web_container" --restart unless-stopped --network "$network" \
      -p 80:80 -p 443:443 \
      --mount "type=bind,src=$tls_cert,dst=/etc/nginx/certs/tls.crt,readonly" \
      --mount "type=bind,src=$tls_key,dst=/etc/nginx/certs/tls.key,readonly" \
      "$frontend_image" >/dev/null
  fi
  fail "Nginx health check failed; previous application container restored"
fi

"${docker_cmd[@]}" rm "$previous_container" >/dev/null 2>&1 || true
"${docker_cmd[@]}" image prune -af \
  --filter 'label=com.flashcontrol.component=main' \
  --filter 'until=168h' >/dev/null
"${docker_cmd[@]}" image prune -af \
  --filter 'label=com.flashcontrol.component=web' \
  --filter 'until=168h' >/dev/null

if [[ -z "$(env_value FLASHCONTROL_LDAP_SERVER_URI)" ]]; then
  user_count=$("${docker_cmd[@]}" exec -e PGPASSWORD="$postgres_password" "$db_container" \
    psql -At -U "$postgres_user" -d "$postgres_db" -c "SELECT count(*) FROM auth_users" | tr -d '\r\n ')
  if [[ "${user_count:-0}" -eq 0 ]]; then
    admin_password=$("${docker_cmd[@]}" exec "$app_container" python -c "import secrets; print(secrets.token_urlsafe(18))")
    [[ -n "$admin_password" ]] || fail "could not generate admin password"
    "${docker_cmd[@]}" exec "$app_container" \
      python -m app.manage_user create --username admin --role admin --password "$admin_password" \
      >/dev/null
    echo "Admin username: admin"
    echo "Admin password: $admin_password"
    machine_token=$(env_value FLASHCONTROL_DEV_MACHINE_TOKEN)
    if [[ -n "$machine_token" ]]; then
      echo "Machine token: $machine_token"
    fi
  fi
fi
echo "Deployed $image at http://$(hostname -I | awk '{print $1}')/; backup: $backup_file"

#!/bin/bash
# Hot-detach last USB Mass Storage image from Proxmox VM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/.state"
VMID="${VMID:-5000}"
STATE_FILE="${STATE_DIR}/${VMID}.last"

usage() {
    cat <<'EOF'
Usage:
  sudo ./detach.sh

Environment:
  VMID=5000   Proxmox VM id (default: 5000)
EOF
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "error: run as root (sudo)" >&2
        exit 1
    fi
}

monitor_cmd() {
    qm monitor "${VMID}" --command "$1" || true
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

require_root

if [[ ! -f "${STATE_FILE}" ]]; then
    echo "error: no attachment state for VM ${VMID}: ${STATE_FILE}" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "${STATE_FILE}"

echo "Detaching ${IMAGE:-unknown}"
echo "  DEV_ID=${DEV_ID:-}"
echo "  DRIVE_ID=${DRIVE_ID:-}"

if [[ -n "${DEV_ID:-}" ]]; then
    monitor_cmd "device_del ${DEV_ID}"
fi
if [[ -n "${DRIVE_ID:-}" ]]; then
    monitor_cmd "drive_del ${DRIVE_ID}"
fi

rm -f "${STATE_FILE}"
echo "Detached."

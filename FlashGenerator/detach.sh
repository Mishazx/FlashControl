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

qmp_monitor_cmd() {
    python3 - "$VMID" "$1" <<'PY'
import json
import socket
import sys

vmid = sys.argv[1]
command = sys.argv[2]
socket_path = f"/var/run/qemu-server/{vmid}.qmp"

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.connect(socket_path)
    stream = sock.makefile("rwb")

    greeting = json.loads(stream.readline())
    if "QMP" not in greeting:
        raise SystemExit("invalid QMP greeting")

    stream.write((json.dumps({"execute": "qmp_capabilities"}) + "\n").encode("utf-8"))
    stream.flush()
    while True:
        response = json.loads(stream.readline())
        if "error" in response:
            raise SystemExit(response["error"].get("desc", "qmp_capabilities failed"))
        if "return" in response:
            break

    request = {
        "execute": "human-monitor-command",
        "arguments": {
            "command-line": command,
        },
    }
    stream.write((json.dumps(request) + "\n").encode("utf-8"))
    stream.flush()

    while True:
        line = stream.readline()
        if not line:
            raise SystemExit("qmp connection closed")
        response = json.loads(line)
        if "error" in response:
            raise SystemExit(response["error"].get("desc", "monitor command failed"))
        if "return" in response:
            result = response["return"]
            if isinstance(result, str):
                sys.stdout.write(result)
            elif result not in (None, {}, []):
                sys.stdout.write(json.dumps(result))
            break
PY
}

monitor_cmd() {
    qmp_monitor_cmd "$1" || true
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

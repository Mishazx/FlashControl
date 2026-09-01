#!/bin/bash
# Hot-attach raw image to Proxmox VM as USB Mass Storage (not VirtIO disk).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/.state"
VMID="${VMID:-5000}"
USB_BUS="${USB_BUS:-}"

usage() {
    cat <<'EOF'
Usage:
  sudo ./attach.sh <image.img>

Environment:
  VMID=5000
  USB_BUS=xhci.0

Optional QEMU hardware identity (override manifest):
  QEMU_USB_SERIAL=FG-001        USB device serial (PnP serial candidate)
  QEMU_DRIVE_SERIAL=STOR001     block device serial (storage descriptor)
  QEMU_VENDOR_ID=0781           USB vendor id (hex, best-effort)
  QEMU_PRODUCT_ID=5583          USB product id (hex, best-effort)
  QEMU_REMOVABLE=true

Manifest <image>.json may contain:
  "qemu_attach": {
    "usb_serial": "FG-COLLISION",
    "drive_serial": "STOR-COLL",
    "vendor_id": "0781",
    "product_id": "5583",
    "removable": true
  }

Detach:
  sudo ./detach.sh
EOF
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "error: run as root (sudo)" >&2
        exit 1
    fi
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "error: command not found: $1" >&2
        exit 1
    fi
}

vm_running() {
    qm status "${VMID}" 2>/dev/null | awk '{print $2}' | grep -qx running
}

detect_usb_bus() {
    if [[ -n "${USB_BUS}" ]]; then
        echo "${USB_BUS}"
        return
    fi

    local tree
    tree="$(qm monitor "${VMID}" --command 'info qtree' 2>/dev/null || true)"
    if echo "${tree}" | grep -q 'xhci.0'; then
        echo 'xhci.0'
        return
    fi
    if echo "${tree}" | grep -q 'ehci.0'; then
        echo 'ehci.0'
        return
    fi
    if echo "${tree}" | grep -q 'usb-bus.0'; then
        echo 'usb-bus.0'
        return
    fi

    echo 'xhci.0'
}

sanitize_id() {
    echo "$1" | tr -c 'a-zA-Z0-9_' '_' | cut -c1-48
}

monitor_cmd() {
    local cmd="$1"
    qm monitor "${VMID}" --command "${cmd}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 ]]; then
    usage
    exit 0
fi

require_root
require_cmd qm
require_cmd python3

IMAGE="$(readlink -f "$1")"
if [[ ! -f "${IMAGE}" ]]; then
    echo "error: image not found: ${IMAGE}" >&2
    exit 1
fi

if ! vm_running; then
    echo "error: VM ${VMID} is not running. Start it first: qm start ${VMID}" >&2
    exit 1
fi

BUS="$(detect_usb_bus)"
BASE_NAME="$(basename "${IMAGE}" .img)"
DRIVE_ID="fg_$(sanitize_id "${BASE_NAME}")"
DEV_ID="${DRIVE_ID}_dev"

PLAN="$(python3 "${SCRIPT_DIR}/qemu_attach.py" "${IMAGE}" "${DRIVE_ID}" "${DEV_ID}" "${BUS}")"
DRIVE_CMD="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["drive_add"])' <<< "${PLAN}")"
mapfile -t DEVICE_CMDS < <(python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)["device_add_variants"]))' <<< "${PLAN}")
QEMU_ATTACH_JSON="$(python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["qemu_attach"], ensure_ascii=False))' <<< "${PLAN}")"

mkdir -p "${STATE_DIR}"
STATE_FILE="${STATE_DIR}/${VMID}.last"

if [[ -f "${STATE_FILE}" ]]; then
    echo "warning: previous attachment state exists; detach first with ./detach.sh" >&2
fi

echo "Attaching ${IMAGE}"
echo "  VMID=${VMID}"
echo "  BUS=${BUS}"
echo "  DRIVE_ID=${DRIVE_ID}"
echo "  DEV_ID=${DEV_ID}"
echo "  qemu_attach=${QEMU_ATTACH_JSON}"

monitor_cmd "${DRIVE_CMD}"

attached=false
for device_cmd in "${DEVICE_CMDS[@]}"; do
    echo "  try: ${device_cmd}"
    if monitor_cmd "${device_cmd}"; then
        attached=true
        break
    fi
done

if [[ "${attached}" != "true" ]]; then
    monitor_cmd "drive_del ${DRIVE_ID}" || true
    echo "error: device_add failed for all variants. Try USB_BUS=ehci.0 or USB_BUS=usb-bus.0" >&2
    exit 1
fi

cat > "${STATE_FILE}" <<EOF
VMID=${VMID}
IMAGE=${IMAGE}
DRIVE_ID=${DRIVE_ID}
DEV_ID=${DEV_ID}
BUS=${BUS}
QEMU_ATTACH=${QEMU_ATTACH_JSON}
EOF

echo ""
echo "Attached. In Windows 11 wait for the new removable disk, then run probe."
echo "Detach when done:"
echo "  sudo ./detach.sh"

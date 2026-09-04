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
  sudo ./attach.sh                  VMID=5000, pick an image from output/
  sudo ./attach.sh <VMID>           attach an image to VM <VMID> (interactive)
  sudo ./attach.sh <VMID> <image or profile>
  sudo ./attach.sh <image or profile>     (VMID from env or 5000)

Environment:
  VMID=5000
  USB_BUS=xhci.0
  OUTPUT_DIR=<this_dir>/output    directory scanned for the interactive menu

The VMID is taken from the first argument when it is a plain number,
otherwise from the VMID environment variable (default 5000).

Interactive mode lists every output/*.img together with the serial/identity
info from its <image>.json manifest (qemu_attach), so you pick one by number
and it is mounted automatically without typing the image or json path.

A full path (or any argument that is not recognized as a menu selection,
e.g. ./attach.sh output/baseline_mbr_fat32.img) attaches that image directly.
When an argument ends with .img, the matching <image>.json manifest is read
automatically — you never have to pass the json explicitly.

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
  sudo ./detach.sh <VMID>
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

vm_running() {
    qm status "${VMID}" 2>/dev/null | awk '{print $2}' | grep -qx running
}

detect_usb_bus() {
    if [[ -n "${USB_BUS}" ]]; then
        echo "${USB_BUS}"
        return
    fi

    local tree
    tree="$(qmp_monitor_cmd 'info qtree' 2>/dev/null || true)"
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
    qmp_monitor_cmd "${cmd}"
}

OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/output}"

# List output/*.img together with identity info from the matching *.img.json
# manifest (qemu_attach). Each line is a single item's info needed for rounding
# out a menu: description | usb serial | drive serial | vid:pid | removable.
list_images() {
    if [[ ! -d "${OUTPUT_DIR}" ]]; then
        echo "error: no output directory: ${OUTPUT_DIR} (run generate first)" >&2
        exit 1
    fi
    shopt -s nullglob
    local image
    for image in "${OUTPUT_DIR}"/*.img; do
        [[ -f "${image}" ]] || continue
        python3 - "${image}" <<'PY'
import json, os, sys
image = sys.argv[1]
name = os.path.basename(image)
manifest_path = image + ".json"
info = {"desc": "", "usb_serial": "-", "drive_serial": "-", "vid_pid": "-", "removable": "?"}
if os.path.isfile(manifest_path):
    try:
        doc = json.load(open(manifest_path, encoding="utf-8"))
    except Exception:
        doc = {}
    info["desc"] = (doc.get("description") or "").strip()
    a = doc.get("qemu_attach") if isinstance(doc.get("qemu_attach"), dict) else {}
    info["usb_serial"] = a.get("usb_serial") or "-"
    info["drive_serial"] = a.get("drive_serial") or "-"
    vid = a.get("vendor_id") or ""
    pid = a.get("product_id") or ""
    info["vid_pid"] = (vid + ":" + pid) if vid and pid else "-"
    info["removable"] = "on" if a.get("removable", True) else "off"
print("%s\t%s\t%s\t%s\t%s\t%s" % (name, info["desc"], info["usb_serial"], info["drive_serial"], info["vid_pid"], info["removable"]))
PY
    done
    shopt -u nullglob
}

# Resolve an argument to an absolute image path.
#   1. "N"          -> the Nth image from the menu (only when arg is purely digits)
#   2. a .img path  -> the path itself (explicit; keeps default, non-interactive)
#   3. a profile name -> output/<name>.img if it exists
resolve_image_arg() {
    local arg="$1"
    local images_file
    images_file="$(mktemp)"
    list_images > "${images_file}"
    local count
    count="$(wc -l < "${images_file}" | tr -d ' ')"
    local line image
    if [[ "${arg}" =~ ^[0-9]+$ ]]; then
        if [[ "${arg}" -ge 1 && "${arg}" -le "${count}" ]]; then
            image="$(sed -n "${arg}p" "${images_file}" | cut -f1)"
            rm -f "${images_file}"
            readlink -f "${OUTPUT_DIR}/${image}"
            return
        fi
        echo "error: invalid selection ${arg}: expected 1..${count}" >&2
        rm -f "${images_file}"
        exit 1
    fi
    if [[ "${arg}" =~ \.img$ ]]; then
        rm -f "${images_file}"
        readlink -f "${arg}"
        return
    fi
    # profile name
    if [[ -f "${OUTPUT_DIR}/${arg}.img" ]]; then
        rm -f "${images_file}"
        readlink -f "${OUTPUT_DIR}/${arg}.img"
        return
    fi
    rm -f "${images_file}"
    echo "error: no such image/profile: ${arg}" >&2
    exit 1
}

# Interactive menu over the available images.
pick_image_interactive() {
    local images_file
    images_file="$(mktemp)"
    list_images > "${images_file}"
    local count
    count="$(wc -l < "${images_file}" | tr -d ' ')"
    if [[ "${count}" -eq 0 ]]; then
        echo "error: no images in ${OUTPUT_DIR} (run generate first)" >&2
        rm -f "${images_file}"
        exit 1
    fi
    echo "Available images in ${OUTPUT_DIR}:"
    echo ""
    printf '  %-3s %-28s %-34s %-16s %-12s %s\n' "#" "IMAGE" "USB SERIAL" "DRIVE SERIAL" "VID:PID" "REM"
    local idx
    idx=0
    while IFS=$'\t' read -r name desc usb drive vidpid rem; do
        idx=$((idx + 1))
        local shown_name="${name%.img}"
        printf '  %-3d %-28s %-34s %-16s %-12s %s\n' "${idx}" "${shown_name}" "${usb}" "${drive}" "${vidpid}" "${rem}"
        if [[ -n "${desc}" ]]; then
            printf '       %-28s %s\n' "" "${desc}"
        fi
    done < "${images_file}"
    rm -f "${images_file}"
    echo ""
    local selection
    read -r -p "Pick a number (1-${count}) or hit Enter to cancel: " selection
    if [[ -z "${selection}" ]]; then
        echo "cancelled."
        exit 0
    fi
    resolve_image_arg "${selection}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

require_root
require_cmd qm
require_cmd python3

# The first argument is the VMID when it is a plain number; otherwise it is an
# image/profile selection. The VMID can also come from the VMID env var.
if [[ $# -ge 1 && "$1" =~ ^[0-9]+$ ]]; then
    VMID="$1"
    shift
fi
VMID="${VMID:-5000}"

IMAGE=""
if [[ $# -lt 1 ]]; then
    # Interactive: no image argument -> numbered menu over output/*.img
    IMAGE="$(pick_image_interactive)"
else
    IMAGE="$(resolve_image_arg "$1")"
fi
readlink -f "${IMAGE}" >/dev/null 2>&1
IMAGE="$(readlink -f "${IMAGE}")"
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
DEV_ID="${DRIVE_ID}"

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

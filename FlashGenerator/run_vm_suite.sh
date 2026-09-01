#!/bin/bash
# Прогон synthetic USB профилей на Proxmox: generate / attach suite / detach.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/.state"
OUTPUT_DIR="${SCRIPT_DIR}/output"
SUITE_FILE="${SCRIPT_DIR}/test_suite.json"
VMID="${VMID:-5000}"
DELAY="${DELAY:-20}"
SHARE_DIR="${FLASHGEN_SHARE:-}"

usage() {
    cat <<'EOF'
Usage:
  sudo ./run_vm_suite.sh generate [--force]
  sudo ./run_vm_suite.sh suite [--delay 20]
  sudo ./run_vm_suite.sh attach <profile>
  sudo ./run_vm_suite.sh detach
  sudo ./run_vm_suite.sh status

Environment:
  VMID=5000
  DELAY=20                 seconds to keep each profile attached in suite mode
  FLASHGEN_SHARE=/mnt/...  optional shared folder visible in Windows VM

Suite mode:
  1. Start in Windows VM:
       .\run_probe_tests.ps1 -Watch
  2. On Proxmox host:
       sudo ./run_vm_suite.sh suite

Manual profiles (rename/format) are skipped in suite mode.
EOF
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "error: run as root (sudo)" >&2
        exit 1
    fi
}

read_suite_profiles() {
    python3 - <<'PY' "${SUITE_FILE}"
import json, sys
suite = json.load(open(sys.argv[1], encoding="utf-8"))
manual = set(suite.get("manual_profiles") or [])
for name in suite.get("profiles") or []:
    if name not in manual:
        print(name)
PY
}

write_current_profile() {
    local profile="$1"
    mkdir -p "${STATE_DIR}"
    echo "${profile}" > "${STATE_DIR}/current_profile.txt"
    if [[ -n "${SHARE_DIR}" ]]; then
        mkdir -p "${SHARE_DIR}"
        echo "${profile}" > "${SHARE_DIR}/current_profile.txt"
    fi
}

clear_current_profile() {
    rm -f "${STATE_DIR}/current_profile.txt"
    if [[ -n "${SHARE_DIR}" && -f "${SHARE_DIR}/current_profile.txt" ]]; then
        rm -f "${SHARE_DIR}/current_profile.txt"
    fi
}

cmd="${1:-}"
shift || true

case "${cmd}" in
    generate)
        require_root
        force=()
        if [[ "${1:-}" == "--force" ]]; then
            force=(--force)
        fi
        exec python3 "${SCRIPT_DIR}/generate.py" --all "${force[@]}"
        ;;
    attach)
        require_root
        profile="${1:?profile name required}"
        image="${OUTPUT_DIR}/${profile}.img"
        if [[ ! -f "${image}" ]]; then
            echo "error: image not found: ${image}" >&2
            echo "run: sudo ./run_vm_suite.sh generate" >&2
            exit 1
        fi
        write_current_profile "${profile}"
        exec "${SCRIPT_DIR}/attach.sh" "${image}"
        ;;
    detach)
        require_root
        clear_current_profile
        exec "${SCRIPT_DIR}/detach.sh"
        ;;
    status)
        qm status "${VMID}" || true
        if [[ -f "${STATE_DIR}/${VMID}.last" ]]; then
            echo "attached state:"
            cat "${STATE_DIR}/${VMID}.last"
        else
            echo "no active attachment state"
        fi
        if [[ -f "${STATE_DIR}/current_profile.txt" ]]; then
            echo "current profile: $(cat "${STATE_DIR}/current_profile.txt")"
        fi
        ;;
    suite)
        require_root
        if [[ "${1:-}" == "--delay" ]]; then
            DELAY="${2:?delay value required}"
            shift 2
        fi
        if ! qm status "${VMID}" 2>/dev/null | awk '{print $2}' | grep -qx running; then
            echo "error: VM ${VMID} is not running" >&2
            exit 1
        fi
        mapfile -t profiles < <(read_suite_profiles)
        if [[ "${#profiles[@]}" -eq 0 ]]; then
            echo "error: no profiles in suite" >&2
            exit 1
        fi
        echo "Running suite on VM ${VMID} with ${DELAY}s delay"
        echo "Profiles: ${profiles[*]}"
        if [[ -n "${SHARE_DIR}" ]]; then
            echo "Shared profile marker: ${SHARE_DIR}/current_profile.txt"
        fi
        echo ""
        for profile in "${profiles[@]}"; do
            image="${OUTPUT_DIR}/${profile}.img"
            if [[ ! -f "${image}" ]]; then
                echo "error: missing image for ${profile}, run generate first" >&2
                exit 1
            fi
            echo "==> ${profile}"
            write_current_profile "${profile}"
            "${SCRIPT_DIR}/attach.sh" "${image}"
            sleep "${DELAY}"
            "${SCRIPT_DIR}/detach.sh"
            sleep 2
        done
        clear_current_profile
        echo ""
        echo "Suite attach/detach complete."
        echo "Analyze Windows results with:"
        echo "  python analyze_results.py results/"
        ;;
    -h|--help|help|"")
        usage
        ;;
    *)
        echo "error: unknown command: ${cmd}" >&2
        usage
        exit 1
        ;;
esac

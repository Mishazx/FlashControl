# -*- coding: utf-8 -*-
"""Test helper: dump the USB observation JSON the agent would queue and send."""

from __future__ import print_function

import argparse
import contextlib
import io
import json
import os
import sys
import uuid
import urllib.error
import urllib.request


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def default_out_path():
    if getattr(sys, "frozen", False):
        return os.path.join(app_dir(), "FlashControlAgentDump.json")
    return os.path.join(os.getcwd(), "FlashControlAgentDump.json")


def load_collector():
    if getattr(sys, "frozen", False):
        import main as collector
        return collector
    try:
        from FlashControlAgent import main as collector
    except ImportError:
        import main as collector
    return collector


def capture_collector_json(collector_args):
    collector = load_collector()

    argv_backup = list(sys.argv)
    buffer = io.StringIO()
    try:
        sys.argv = [argv_backup[0]] + list(collector_args)
        with contextlib.redirect_stdout(buffer):
            result = collector.main()
    finally:
        sys.argv = argv_backup

    text = buffer.getvalue().strip()
    if not text:
        raise RuntimeError("collector produced no output")
    json.loads(text)
    return text, result


def observations_from_document(document):
    try:
        from FlashControlAgent.observation_payload import expand_observations
    except ImportError:
        from observation_payload import expand_observations
    return expand_observations(document)


def dump_payload(document):
    try:
        from FlashControlAgent.observation_payload import pack_observation_payload
    except ImportError:
        from observation_payload import pack_observation_payload
    return pack_observation_payload(observations_from_document(document))


def observation_event_id(observation):
    if not isinstance(observation, dict):
        return None
    event_id = observation.get("event_id")
    if event_id:
        return str(event_id)
    event = observation.get("event") or {}
    event_id = event.get("id")
    return str(event_id) if event_id else None


def device_label(observation):
    device = observation.get("device") or {}
    storage = device.get("storage") or {}
    vendor = device.get("vendor") or storage.get("vendor") or "?"
    product = device.get("product") or storage.get("product") or "?"
    serial = device.get("serial") or storage.get("serial") or "?"
    return "%s %s serial=%s" % (vendor, product, serial)


def write_text(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def post_json(server_url, payload, timeout_seconds, headers=None):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        server_url,
        data=body.encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response.read()
        return response.getcode()


def print_summary(document, out_path):
    observations = observations_from_document(document)
    sys.stderr.write(
        "Collected %s observation(s). This is the JSON the agent would queue and send.\n"
        % len(observations)
    )
    if not observations:
        sys.stderr.write(
            "No USB flash drives found. Plug one in and run again.\n"
        )
    for index, observation in enumerate(observations, 1):
        sys.stderr.write(
            "  %s. %s event_id=%s\n"
            % (index, device_label(observation), observation_event_id(observation) or "-")
        )
    sys.stderr.write("Wrote %s\n" % os.path.abspath(out_path))


def resolve_send_identity(machine_id, machine_token):
    token = (machine_token or "").strip()
    if not token:
        raise RuntimeError("machine token is required to send observations")
    value = (machine_id or "").strip()
    if not value:
        value = str(uuid.uuid4())
    try:
        return str(uuid.UUID(value)), token
    except ValueError:
        raise RuntimeError("machine id must be a UUID")


def send_observations(document, server_url, timeout_seconds, machine_id, machine_token):
    observations = observations_from_document(document)
    if not observations:
        raise RuntimeError("nothing to send: collector returned no observations")
    machine_id, machine_token = resolve_send_identity(machine_id, machine_token)
    headers = {
        "X-FlashControl-Machine-ID": machine_id,
        "X-FlashControl-Machine-Kind": "agent",
        "X-FlashControl-Machine-Token": machine_token,
    }
    for observation in observations:
        event_id = observation_event_id(observation) or "?"
        try:
            status = post_json(server_url, observation, timeout_seconds, headers)
            sys.stderr.write("Sent %s -> HTTP %s\n" % (event_id, status))
        except urllib.error.HTTPError as exc:
            raise RuntimeError("send failed for %s: HTTP %s" % (event_id, exc.code)) from None
        except Exception as exc:
            raise RuntimeError("send failed for %s: %s" % (event_id, exc)) from None


def pause_if_needed(enabled):
    if not enabled:
        return
    try:
        if not sys.stdin.isatty():
            return
    except Exception:
        return
    try:
        input("\nPress Enter to exit...")
    except EOFError:
        pass


def build_parser():
    parser = argparse.ArgumentParser(
        description="Dump the USB observation JSON FlashControlAgent would send."
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default: FlashControlAgentDump.json next to the EXE)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Include the full diagnostic payload (PnP tree, unused partitions, host extras)",
    )
    parser.add_argument(
        "--send",
        metavar="URL",
        default="",
        help="Also POST each observation to this URL, the same way the agent does",
    )
    parser.add_argument(
        "--machine-id",
        default="",
        help="Agent UUID sent as X-FlashControl-Machine-ID. Generated if omitted.",
    )
    parser.add_argument(
        "--machine-token",
        default="",
        help="Shared development token; required with --send",
    )
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--no-pause", action="store_true")
    return parser


def run(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    collector_args = []
    if args.debug:
        collector_args.append("--debug")
    text, collector_status = capture_collector_json(collector_args)
    if collector_status not in (None, 0):
        return collector_status

    document = json.loads(text)
    payload = dump_payload(document)
    out_path = os.path.abspath(args.out or default_out_path())
    write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2))
    print_summary(payload, out_path)

    if args.send:
        machine_id, machine_token = resolve_send_identity(
            args.machine_id, args.machine_token
        )
        if not (args.machine_id or "").strip():
            sys.stderr.write("Generated machine-id %s\n" % machine_id)
        send_observations(
            payload,
            args.send.strip(),
            max(1, int(args.timeout_seconds or 30)),
            machine_id,
            machine_token,
        )

    pause_if_needed(getattr(sys, "frozen", False) and not args.no_pause)
    return 0


def main(argv=None):
    try:
        return run(argv)
    except Exception as exc:
        sys.stderr.write("Dump failed: %s\n" % exc)
        pause_if_needed(getattr(sys, "frozen", False) and "--no-pause" not in (argv or sys.argv))
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)

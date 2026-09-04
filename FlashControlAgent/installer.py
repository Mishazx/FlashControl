# -*- coding: utf-8 -*-
"""Installer bootstrapper for FlashControlAgent."""

from __future__ import print_function

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import logging
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

try:
    from heartbeat import observations_url, persist_agent_id
except ImportError:
    from FlashControlAgent.heartbeat import observations_url, persist_agent_id


SERVICE_NAME = "FlashControlAgent"
SERVICE_EXE_NAME = "FlashControlAgentService.exe"
SERVICE_DIR_NAME = "FlashControlAgentService"
DEFAULT_INSTALL_DIR = r"C:\ProgramData\FlashControlAgent"
LOGGER = None


class ConsoleFormatter(logging.Formatter):
    """Keep tracebacks in the log file without dumping them to the console."""

    def format(self, record):
        exc_info = record.exc_info
        exc_text = record.exc_text
        record.exc_info = None
        record.exc_text = None
        try:
            return super(ConsoleFormatter, self).format(record)
        finally:
            record.exc_info = exc_info
            record.exc_text = exc_text


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def state_dir(install_dir):
    parent_dir = os.path.dirname(os.path.abspath(install_dir))
    return os.path.join(parent_dir, SERVICE_NAME + "State")


def queue_path(install_dir):
    return os.path.join(state_dir(install_dir), "FlashControlAgent.queue.db")


def agent_id_file_path(install_dir):
    return os.path.join(state_dir(install_dir), "FlashControlAgent.id")


def machine_token_file_path(install_dir):
    return os.path.join(state_dir(install_dir), "FlashControlAgent.token")


def migrate_state_file(install_dir, filename):
    old_path = os.path.join(os.path.abspath(install_dir), filename)
    new_path = os.path.join(state_dir(install_dir), filename)
    if not os.path.exists(old_path) or os.path.exists(new_path):
        return
    state_folder = os.path.dirname(new_path)
    if state_folder and not os.path.exists(state_folder):
        os.makedirs(state_folder)
    shutil.move(old_path, new_path)


def migrate_queue_file(install_dir):
    migrate_state_file(install_dir, "FlashControlAgent.queue.db")


def migrate_agent_id_file(install_dir):
    migrate_state_file(install_dir, "FlashControlAgent.id")


def optional_text(value):
    return (value or "").strip()


def bundled_agent_config():
    candidates = [
        os.path.join(resource_dir(), "agent_config.json"),
        os.path.join(app_dir(), "agent_config.json"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r") as handle:
                loaded = json.load(handle)
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    return {}


def overlay_text(cli_value, bundled_value):
    cli = optional_text(cli_value)
    if cli:
        return cli
    return optional_text(bundled_value)


def build_agent_config(args, install_dir, bundled=None):
    bundled = bundled or {}
    return {
        "server_url": overlay_text(getattr(args, "server_url", ""), bundled.get("server_url")),
        "interval_seconds": args.interval_seconds,
        "request_timeout_seconds": args.request_timeout_seconds,
        "queue_file": queue_path(install_dir),
        "queue_max_items": 100000,
        "retry_interval_seconds": 30,
        "retry_max_seconds": 3600,
        "delivery_batch_size": 100,
        "heartbeat_url": overlay_text(
            getattr(args, "heartbeat_url", ""), bundled.get("heartbeat_url")
        ),
        "enroll_url": overlay_text(getattr(args, "enroll_url", ""), bundled.get("enroll_url")),
        "agent_id_file": agent_id_file_path(install_dir),
        "machine_token": overlay_text(
            getattr(args, "machine_token", ""), bundled.get("machine_token")
        ),
        "machine_token_file": machine_token_file_path(install_dir),
        "ca_file": overlay_text(getattr(args, "ca_file", ""), bundled.get("ca_file")),
        "client_cert_file": overlay_text(
            getattr(args, "client_cert_file", ""), bundled.get("client_cert_file")
        ),
        "client_key_file": overlay_text(
            getattr(args, "client_key_file", ""), bundled.get("client_key_file")
        ),
        "collector_args": [],
        "include_non_usb": bool(getattr(args, "include_non_usb", False)),
        "log_file": "FlashControlAgent.log",
    }


def resource_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_dir())
    return app_dir()


def bundled_service_dir():
    embedded = os.path.join(resource_dir(), SERVICE_DIR_NAME)
    if os.path.isdir(embedded):
        return embedded
    local = os.path.join(app_dir(), SERVICE_DIR_NAME)
    if os.path.isdir(local):
        return local
    return None


def bundled_service_path():
    service_dir = bundled_service_dir()
    if service_dir:
        return os.path.join(service_dir, SERVICE_EXE_NAME)
    embedded = os.path.join(resource_dir(), SERVICE_EXE_NAME)
    if os.path.exists(embedded):
        return embedded
    return os.path.join(app_dir(), SERVICE_EXE_NAME)


def stop_service_processes():
    safe_run(["taskkill", "/F", "/IM", SERVICE_EXE_NAME])
    if service_exists():
        safe_run(["sc.exe", "stop", SERVICE_NAME])
    time.sleep(2)


def copy_service_files(install_dir):
    stop_service_processes()

    service_dir = bundled_service_dir()
    if service_dir:
        if os.path.exists(install_dir):
            shutil.rmtree(install_dir, ignore_errors=True)
        shutil.copytree(service_dir, install_dir)
        return os.path.join(install_dir, SERVICE_EXE_NAME)

    service_src = bundled_service_path()
    if not os.path.exists(service_src):
        raise RuntimeError("Bundled service binary is missing: %s" % service_src)

    if not os.path.exists(install_dir):
        os.makedirs(install_dir)

    service_dst = os.path.join(install_dir, SERVICE_EXE_NAME)
    shutil.copy2(service_src, service_dst)
    return service_dst


def installer_log_path():
    return os.path.join(app_dir(), "FlashControlAgentInstaller.log")


def setup_logger():
    logger = logging.getLogger("FlashControlAgentInstaller")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ConsoleFormatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console_handler)

    handler = RotatingFileHandler(
        installer_log_path(),
        maxBytes=1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_checked(command):
    LOGGER.info("Running: %s", " ".join(map(str, command)))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        LOGGER.error("Command failed (%s): %s", result.returncode, " ".join(map(str, command)))
        if result.stdout.strip():
            LOGGER.error("stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            LOGGER.error("stderr: %s", result.stderr.strip())
        raise RuntimeError(
            "Command failed (%s): %s\n%s"
            % (result.returncode, " ".join(command), result.stderr.strip())
        )
    return result


def safe_run(command):
    try:
        return run_checked(command)
    except Exception:
        return None


def service_exists():
    result = subprocess.run(
        ["sc.exe", "query", SERVICE_NAME],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def write_json(path, payload):
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(path, "w") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def validate_server_url(server_url, timeout_seconds):
    if not server_url:
        return

    LOGGER.info("Validating server URL: %s", server_url)
    request = urllib.request.Request(
        server_url,
        method="GET",
        headers={
            "User-Agent": "FlashControlAgentInstaller/1.0",
            "Accept": "application/json, text/plain, */*",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", response.getcode())
            LOGGER.info("Server URL reachable, HTTP %s", status)
    except urllib.error.HTTPError as exc:
        # Любой HTTP-ответ значит, что до сервера мы достучались.
        LOGGER.info("Server URL reachable, HTTP %s", exc.code)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.gaierror):
            host = urlparse(server_url).hostname or server_url
            raise RuntimeError(
                "Cannot resolve server host '%s'. Check the server URL, DNS, and network connection."
                % host
            ) from None
        raise RuntimeError("Server URL is not reachable: %s" % exc.reason) from None
    except Exception as exc:
        raise RuntimeError("Server URL is not reachable: %s" % exc) from None


def install(args):
    LOGGER.info("Install started")
    if not is_admin():
        raise RuntimeError("Administrator rights are required to install a Windows service.")

    bundled = bundled_agent_config()
    config = build_agent_config(args, os.path.abspath(args.install_dir), bundled)
    validate_server_url(
        observations_url(config.get("server_url")),
        min(int(args.request_timeout_seconds or 30), 10),
    )

    install_dir = os.path.abspath(args.install_dir)
    stop_service_processes()
    migrate_queue_file(install_dir)
    migrate_agent_id_file(install_dir)
    service_dst = copy_service_files(install_dir)
    LOGGER.info("Copied service files to %s", install_dir)

    try:
        agent_id = persist_agent_id(
            agent_id_file_path(install_dir),
            optional_text(getattr(args, "agent_id", "")),
        )
    except ValueError:
        raise RuntimeError("--agent-id must be a UUID") from None
    write_json(os.path.join(install_dir, "agent_config.json"), config)
    LOGGER.info("Wrote config to %s", os.path.join(install_dir, "agent_config.json"))
    LOGGER.info("Agent identity %s", agent_id)
    if config.get("server_url") and not config.get("machine_token") and not config.get("client_cert_file"):
        LOGGER.info("Collector URL baked in; agent will enroll and receive its own token")
    if config.get("machine_token"):
        LOGGER.info("Development machine token configured")
    if config.get("client_cert_file"):
        LOGGER.info("mTLS client certificate configured: %s", config["client_cert_file"])

    if service_exists():
        LOGGER.info("Service already exists, removing old copy")
        safe_run([service_dst, "stop"])
        safe_run([service_dst, "remove"])
        time.sleep(2)

    run_checked([service_dst, "install"])
    safe_run(["sc.exe", "config", SERVICE_NAME, "start=", "auto"])

    start_result = subprocess.run(
        [service_dst, "start", "--wait", "30"],
        capture_output=True,
        text=True,
    )
    if start_result.returncode != 0:
        LOGGER.warning(
            "Service start returned %s. stdout=%s stderr=%s",
            start_result.returncode,
            start_result.stdout.strip(),
            start_result.stderr.strip(),
        )
        LOGGER.warning(
            "Service files are installed. Check %s and Windows Event Viewer if the service did not start.",
            os.path.join(install_dir, "FlashControlAgent.log"),
        )
    else:
        LOGGER.info("Service started successfully")

    LOGGER.info("Install complete")

    return 0


def uninstall(args):
    LOGGER.info("Uninstall started")
    if not is_admin():
        raise RuntimeError("Administrator rights are required to remove a Windows service.")

    install_dir = os.path.abspath(args.install_dir)
    service_dst = os.path.join(install_dir, SERVICE_EXE_NAME)
    safe_run([service_dst, "stop"])
    safe_run([service_dst, "remove"])
    safe_run(["sc.exe", "delete", SERVICE_NAME])

    if os.path.exists(install_dir):
        shutil.rmtree(install_dir, ignore_errors=True)
    LOGGER.info("Uninstall complete")

    return 0


def reinstall(args):
    LOGGER.info("Reinstall started")
    uninstall(args)
    install(args)
    LOGGER.info("Reinstall complete")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="FlashControlAgent installer")
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    common.add_argument("--server-url", default="")
    common.add_argument("--machine-token", default="")
    common.add_argument("--agent-id", default="")
    common.add_argument("--heartbeat-url", default="")
    common.add_argument("--enroll-url", default="")
    common.add_argument("--ca-file", default="")
    common.add_argument("--client-cert-file", default="")
    common.add_argument("--client-key-file", default="")
    common.add_argument("--interval-seconds", type=int, default=3600)
    common.add_argument("--request-timeout-seconds", type=int, default=30)
    common.add_argument("--include-non-usb", action="store_true")

    sub.add_parser("install", parents=[common], help="Install the service")
    sub.add_parser("uninstall", parents=[common], help="Remove the service")
    sub.add_parser("reinstall", parents=[common], help="Reinstall the service")

    parser.set_defaults(command="install")
    return parser


def main():
    global LOGGER
    LOGGER = setup_logger()
    parser = build_parser()
    try:
        args = parser.parse_args()

        if args.command == "install":
            return install(args)
        if args.command == "uninstall":
            return uninstall(args)
        if args.command == "reinstall":
            return reinstall(args)
        parser.error("Unknown command: %s" % args.command)
    except Exception as exc:
        LOGGER.exception("Installer failed: %s", exc)
        print("Details: %s" % installer_log_path())
        return 1


if __name__ == "__main__":
    sys.exit(main())

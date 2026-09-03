# -*- coding: utf-8 -*-
"""Windows service host for FlashControlAgent."""

from __future__ import print_function

import contextlib
import io
import json
import logging
import os
import ssl
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from logging.handlers import RotatingFileHandler

from delivery_queue import DeliveryQueue, deliver_due
from heartbeat import (
    build_enroll_payload,
    build_heartbeat,
    current_machine_token,
    delivery_credentials_configured,
    enroll_url,
    heartbeat_url,
    load_or_create_agent_id,
    persist_secret,
)
from observation_payload import expand_observations, pack_observation_payload

import servicemanager
import win32event
import win32con
import win32gui
import win32gui_struct
import win32service
import win32serviceutil
import win32timezone

SERVICE_NAME = "FlashControlAgent"
SERVICE_DISPLAY_NAME = "FlashControl Agent"
SERVICE_DESCRIPTION = "Collects device inventory and forwards JSON to the backend."
# GUID_DEVINTERFACE_DISK.  Registering this interface (rather than every USB
# device) keeps notifications limited to storage devices, not hubs/keyboards.
GUID_DEVINTERFACE_DISK = "{53F56307-B6BF-11D0-94F2-00A0C91EFB8B}"

DEFAULT_CONFIG = {
    "server_url": "",
    "interval_seconds": 3600,
    "request_timeout_seconds": 30,
    "collector_args": [],
    "log_file": "FlashControlAgent.log",
    "queue_file": "FlashControlAgent.queue.db",
    "queue_max_items": 100000,
    "retry_interval_seconds": 30,
    "retry_max_seconds": 3600,
    "delivery_batch_size": 100,
    "heartbeat_url": "",
    "heartbeat_interval_seconds": 60,
    "device_event_debounce_seconds": 2,
    "agent_id_file": "FlashControlAgent.id",
    "machine_token": "",
    "machine_token_file": "FlashControlAgent.token",
    "ca_file": "",
    "client_cert_file": "",
    "client_key_file": "",
}


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


DEFAULT_CONFIG["queue_file"] = os.path.join(
    os.path.dirname(app_dir()),
    "FlashControlAgentState",
    DEFAULT_CONFIG["queue_file"],
)
DEFAULT_CONFIG["agent_id_file"] = os.path.join(
    os.path.dirname(app_dir()),
    "FlashControlAgentState",
    DEFAULT_CONFIG["agent_id_file"],
)
DEFAULT_CONFIG["machine_token_file"] = os.path.join(
    os.path.dirname(app_dir()),
    "FlashControlAgentState",
    DEFAULT_CONFIG["machine_token_file"],
)


def bootstrap_log_path():
    return os.path.join(app_dir(), "FlashControlAgent.bootstrap.log")


def bootstrap_log(message):
    line = "[%s] %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), message)
    try:
        with open(bootstrap_log_path(), "a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def config_path():
    return os.path.join(app_dir(), "agent_config.json")


def read_config():
    config = dict(DEFAULT_CONFIG)
    path = config_path()
    if not os.path.exists(path):
        return config

    try:
        with open(path, "r") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            config.update(loaded)
    except Exception:
        pass

    return config


def log_path(config):
    filename = config.get("log_file") or DEFAULT_CONFIG["log_file"]
    if os.path.isabs(filename):
        return filename
    return os.path.join(app_dir(), filename)


def queue_path(config):
    filename = config.get("queue_file") or DEFAULT_CONFIG["queue_file"]
    if os.path.isabs(filename):
        return filename
    return os.path.join(app_dir(), filename)


def agent_id_path(config):
    filename = config.get("agent_id_file") or DEFAULT_CONFIG["agent_id_file"]
    if os.path.isabs(filename):
        path = filename
    else:
        path = os.path.join(app_dir(), filename)
    if not os.path.exists(path):
        legacy = os.path.join(app_dir(), "FlashControlAgent.id")
        if os.path.exists(legacy):
            return legacy
    return path


def machine_token_path(config):
    filename = config.get("machine_token_file") or DEFAULT_CONFIG["machine_token_file"]
    if os.path.isabs(filename):
        return filename
    return os.path.join(app_dir(), filename)


def get_logger(config):
    path = log_path(config)
    folder = os.path.dirname(path)
    if folder and not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except OSError:
            pass

    logger = logging.getLogger("FlashControlAgent")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def write_log(config, message):
    get_logger(config).info(message)


def capture_collector_json(collector_args):
    import main as collector

    argv_backup = list(sys.argv)
    stdout_backup = sys.stdout
    buffer = io.StringIO()
    try:
        sys.argv = [argv_backup[0]] + list(collector_args)
        with contextlib.redirect_stdout(buffer):
            collector.main()
    finally:
        sys.argv = argv_backup
        sys.stdout = stdout_backup

    text = buffer.getvalue().strip()
    if not text:
        raise RuntimeError("collector produced no output")
    json.loads(text)
    return text


def device_key(observation):
    """Stable key used only for the local disconnect cache."""
    hashes = observation.get("hashes") or {}
    value = hashes.get("hardware_stable")
    if value:
        return "hardware:" + str(value)
    device = observation.get("device") or {}
    serial = device.get("serial")
    if serial:
        return "serial:" + str(serial)
    return None


def observations_by_device_key(document):
    result = {}
    for observation in expand_observations(document):
        key = device_key(observation)
        if key:
            result[key] = observation
    return result


def device_change_payload(document, previous_devices):
    """Turn a notification-triggered rescan into connect/disconnect events."""
    current_devices = observations_by_device_key(document)
    event_observations = []
    observed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for key in sorted(set(previous_devices) - set(current_devices)):
        item = dict(previous_devices[key])
        event = dict(item.get("event") or {})
        event.update({"id": str(uuid.uuid4()), "type": "disconnected", "observed_at_utc": observed_at})
        item["event"] = event
        event_observations.append(item)
    for key in sorted(set(current_devices) - set(previous_devices)):
        item = dict(current_devices[key])
        event = dict(item.get("event") or {})
        event.update({"id": str(uuid.uuid4()), "type": "connected", "observed_at_utc": observed_at})
        item["event"] = event
        event_observations.append(item)

    previous_devices.clear()
    previous_devices.update(current_devices)
    if not event_observations:
        return None
    return pack_observation_payload(event_observations)


def machine_headers(agent_id, token):
    return {
        "X-FlashControl-Machine-ID": agent_id,
        "X-FlashControl-Machine-Kind": "agent",
        "X-FlashControl-Machine-Token": token or "",
    }


def ssl_context(config):
    context = ssl.create_default_context(
        cafile=config.get("ca_file") or None
    )
    certificate = config.get("client_cert_file") or ""
    if certificate:
        context.load_cert_chain(certificate, config.get("client_key_file") or None)
    return context


def post_json(server_url, json_text, timeout_seconds, headers=None, context=None):
    if not isinstance(json_text, str):
        json_text = json.dumps(json_text, ensure_ascii=False, separators=(",", ":"))
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        server_url,
        data=json_text.encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
        body = response.read()
        return response.getcode(), body


def enroll_with_collector(url, payload, timeout_seconds, context):
    status_code, body = post_json(url, payload, timeout_seconds, context=context)
    if status_code < 200 or status_code >= 300:
        raise RuntimeError("enroll returned HTTP %s" % status_code)
    document = json.loads(body.decode("utf-8"))
    token = str(document.get("machine_token") or "").strip()
    if not token:
        raise RuntimeError("enroll response did not include machine_token")
    return token


def drain_delivery_queue(queue, server_url, timeout_seconds, batch_size,
                         retry_interval_seconds, retry_max_seconds, logger,
                         agent_id, machine_token, context):
    def sender(payload_json):
        headers = machine_headers(agent_id, machine_token)
        status_code, _body = post_json(server_url, payload_json, timeout_seconds, headers, context)
        if status_code < 200 or status_code >= 300:
            raise RuntimeError("server returned HTTP %s" % status_code)

    def log_failure(event_id, exc, delay):
        logger.warning(
            "delivery failed for event_id=%s; retry in %ss: %s",
            event_id,
            int(delay or retry_interval_seconds),
            exc,
        )

    return deliver_due(
        queue,
        sender,
        limit=batch_size,
        base_delay=retry_interval_seconds,
        max_delay=retry_max_seconds,
        on_failure=log_failure,
    )


class FlashControlAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        bootstrap_log("service __init__")
        super(FlashControlAgentService, self).__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.device_event = win32event.CreateEvent(None, 0, 0, None)
        self.device_notification_handle = None
        self.config = read_config()
        self.logger = get_logger(self.config)
        bootstrap_log("service logger ready")

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcOtherEx(self, control, event_type, data):
        """Wake the collector when Windows reports a disk interface change."""
        if control == win32service.SERVICE_CONTROL_DEVICEEVENT:
            win32event.SetEvent(self.device_event)

    def GetAcceptedControls(self):
        """Explicitly opt in to HandlerEx device-change callbacks."""
        accepted = win32serviceutil.ServiceFramework.GetAcceptedControls(self)
        # pywin32 uses the DEVICEEVENT control value in the accepted-controls
        # mask (see its serviceEvents.py example).
        return accepted | win32service.SERVICE_CONTROL_DEVICEEVENT

    def register_device_notifications(self):
        """Subscribe this service to arrival/removal events for disk devices.

        This is intentionally best-effort: periodic collection remains a safe
        fallback on old Windows versions or under a restricted service host.
        """
        try:
            notification_filter = win32gui_struct.PackDEV_BROADCAST_DEVICEINTERFACE(
                GUID_DEVINTERFACE_DISK
            )
            self.device_notification_handle = win32gui.RegisterDeviceNotification(
                self.ssh,
                notification_filter,
                win32con.DEVICE_NOTIFY_SERVICE_HANDLE,
            )
            self.logger.info("subscribed to Windows disk device notifications")
        except Exception as exc:
            self.logger.warning(
                "Windows disk device notifications unavailable; using periodic scan: %s",
                exc,
            )

    def unregister_device_notifications(self):
        if self.device_notification_handle is None:
            return
        try:
            win32gui.UnregisterDeviceNotification(self.device_notification_handle)
        except Exception:
            pass
        self.device_notification_handle = None

    def SvcDoRun(self):
        bootstrap_log("SvcDoRun entered")
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self.logger.info("%s started", SERVICE_DISPLAY_NAME)
        servicemanager.LogInfoMsg("%s started" % SERVICE_DISPLAY_NAME)
        bootstrap_log("service reported RUNNING")
        self.run()

    def run(self):
        interval_seconds = int(self.config.get("interval_seconds") or 0)
        if interval_seconds < 1:
            interval_seconds = 3600
        timeout_seconds = int(self.config.get("request_timeout_seconds") or 30)
        if timeout_seconds < 1:
            timeout_seconds = 30
        retry_interval_seconds = max(
            1, int(self.config.get("retry_interval_seconds") or 30)
        )
        retry_max_seconds = max(
            retry_interval_seconds, int(self.config.get("retry_max_seconds") or 3600)
        )
        batch_size = max(1, int(self.config.get("delivery_batch_size") or 100))
        heartbeat_interval = max(
            15, int(self.config.get("heartbeat_interval_seconds") or 60)
        )
        device_event_debounce = max(
            0, float(self.config.get("device_event_debounce_seconds") or 2)
        )
        agent_id = load_or_create_agent_id(agent_id_path(self.config))
        transport_ssl_context = ssl_context(self.config)
        token_path = machine_token_path(self.config)
        self.config["machine_token_file"] = token_path

        collector_args = self.config.get("collector_args") or []

        queue = DeliveryQueue(
            queue_path(self.config),
            max_items=int(self.config.get("queue_max_items") or 100000),
        )
        self.logger.info(
            "agent identity %s; delivery queue ready: path=%s size=%s",
            agent_id,
            queue.path,
            queue.count(),
        )
        next_collection_at = 0
        next_heartbeat_at = 0
        device_scan_at = None
        device_notification_scan = False
        device_cache = {}
        self.register_device_notifications()
        try:
            while True:
                now = time.time()
                if device_scan_at is not None and now >= device_scan_at:
                    self.logger.info("processing Windows disk device notification")
                    next_collection_at = 0
                    device_scan_at = None
                    device_notification_scan = True
                if now >= next_collection_at:
                    try:
                        self.logger.info("collection cycle started")
                        payload = capture_collector_json(collector_args)
                        document = json.loads(payload)
                        if device_notification_scan:
                            event_payload = device_change_payload(document, device_cache)
                            if event_payload is None:
                                self.logger.info("disk notification produced no USB device change")
                            else:
                                event_ids = queue.enqueue_json(
                                    json.dumps(event_payload, ensure_ascii=False)
                                )
                                self.logger.info(
                                    "queued %s device-change observation(s); queue_size=%s",
                                    len(event_ids), queue.count(),
                                )
                        else:
                            device_cache.clear()
                            device_cache.update(observations_by_device_key(document))
                            event_ids = queue.enqueue_json(payload)
                            self.logger.info(
                                "queued %s observation(s); queue_size=%s",
                                len(event_ids), queue.count(),
                            )
                    except Exception:
                        self.logger.exception("collection cycle failed")
                    finally:
                        device_notification_scan = False
                    next_collection_at = time.time() + interval_seconds

                server_url = (self.config.get("server_url") or "").strip()
                machine_token = current_machine_token(self.config)
                credentials_ready = delivery_credentials_configured(self.config)
                target_enroll_url = enroll_url(
                    server_url, self.config.get("enroll_url") or ""
                )
                if (
                    server_url
                    and target_enroll_url
                    and not credentials_ready
                    and not (self.config.get("client_cert_file") or "").strip()
                ):
                    try:
                        import main as collector
                        issued = enroll_with_collector(
                            target_enroll_url,
                            build_enroll_payload(
                                agent_id, collector.PROBE_VERSION, collector.host_info()
                            ),
                            timeout_seconds,
                            transport_ssl_context,
                        )
                        persist_secret(token_path, issued)
                        machine_token = issued
                        credentials_ready = True
                        self.logger.info("enrolled with collector as %s", agent_id)
                    except Exception as exc:
                        self.logger.warning("enroll failed: %s", exc)

                if server_url and credentials_ready:
                    delivered = drain_delivery_queue(
                        queue, server_url, timeout_seconds, batch_size,
                        retry_interval_seconds, retry_max_seconds, self.logger,
                        agent_id, machine_token,
                        transport_ssl_context,
                    )
                    if delivered:
                        self.logger.info(
                            "delivered %s observation(s); queue_size=%s",
                            delivered,
                            queue.count(),
                        )

                now = time.time()
                target_heartbeat_url = heartbeat_url(
                    server_url, self.config.get("heartbeat_url") or ""
                )
                if target_heartbeat_url and credentials_ready and now >= next_heartbeat_at:
                    try:
                        import main as collector
                        heartbeat_payload = build_heartbeat(
                            agent_id, collector.PROBE_VERSION, queue.count(),
                            collector.host_info(),
                            "direct", None,
                        )
                        heartbeat_status, _heartbeat_body = post_json(
                            target_heartbeat_url, heartbeat_payload, timeout_seconds,
                            machine_headers(agent_id, machine_token),
                            transport_ssl_context,
                        )
                        if heartbeat_status < 200 or heartbeat_status >= 300:
                            raise RuntimeError("heartbeat returned HTTP %s" % heartbeat_status)
                        self.logger.info("heartbeat accepted; queue_size=%s", queue.count())
                    except Exception as exc:
                        self.logger.warning("heartbeat failed: %s", exc)
                    next_heartbeat_at = time.time() + heartbeat_interval

                wait_seconds = min(
                    retry_interval_seconds,
                    max(1, next_collection_at - time.time()),
                    max(1, next_heartbeat_at - time.time()) if target_heartbeat_url else retry_interval_seconds,
                )
                if device_scan_at is not None:
                    wait_seconds = min(
                        wait_seconds,
                        max(0.1, device_scan_at - time.time()),
                    )
                wait_result = win32event.WaitForMultipleObjects(
                    [self.stop_event, self.device_event],
                    False,
                    int(wait_seconds * 1000),
                )
                if wait_result == win32event.WAIT_OBJECT_0:
                    break
                if wait_result == win32event.WAIT_OBJECT_0 + 1:
                    # A newly announced disk can need a moment before its
                    # storage descriptor and PnP chain are queryable.
                    device_scan_at = time.time() + device_event_debounce
                    self.logger.info(
                        "Windows disk device notification received; scan scheduled in %.1fs",
                        device_event_debounce,
                    )
        finally:
            self.unregister_device_notifications()
            queue.close()


def service_main():
    bootstrap_log("service_main argv=%s" % " ".join(sys.argv))
    try:
        if len(sys.argv) == 1:
            # Frozen EXE started by Windows Service Control Manager.
            bootstrap_log("entering SCM host mode")
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(FlashControlAgentService)
            servicemanager.StartServiceCtrlDispatcher()
            return

        win32serviceutil.HandleCommandLine(FlashControlAgentService)
    except Exception:
        bootstrap_log("service_main failed:\n%s" % traceback.format_exc())
        raise


if __name__ == "__main__":
    service_main()

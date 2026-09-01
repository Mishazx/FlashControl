# -*- coding: utf-8 -*-
"""Windows service host for FlashControlAgent."""

from __future__ import print_function

import contextlib
import io
import json
import logging
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler

from delivery_queue import DeliveryQueue, deliver_due

import servicemanager
import win32event
import win32service
import win32serviceutil
import win32timezone

SERVICE_NAME = "FlashControlAgent"
SERVICE_DISPLAY_NAME = "FlashControl Agent"
SERVICE_DESCRIPTION = "Collects device inventory and forwards JSON to the backend."

DEFAULT_CONFIG = {
    "server_url": "",
    "interval_seconds": 3600,
    "request_timeout_seconds": 30,
    "collector_args": [],
    "include_non_usb": False,
    "log_file": "FlashControlAgent.log",
    "queue_file": "FlashControlAgent.queue.db",
    "queue_max_items": 100000,
    "retry_interval_seconds": 30,
    "retry_max_seconds": 3600,
    "delivery_batch_size": 100,
}


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


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


def post_json(server_url, json_text, timeout_seconds):
    request = urllib.request.Request(
        server_url,
        data=json_text.encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response.read()
        return response.getcode()


def drain_delivery_queue(queue, server_url, timeout_seconds, batch_size,
                         retry_interval_seconds, retry_max_seconds, logger):
    def sender(payload_json):
        status_code = post_json(server_url, payload_json, timeout_seconds)
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
        self.config = read_config()
        self.logger = get_logger(self.config)
        bootstrap_log("service logger ready")

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

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

        collector_args = self.config.get("collector_args") or []
        if self.config.get("include_non_usb"):
            collector_args = list(collector_args) + ["--all-disks"]

        queue = DeliveryQueue(
            queue_path(self.config),
            max_items=int(self.config.get("queue_max_items") or 100000),
        )
        next_collection_at = 0
        try:
            while True:
                now = time.time()
                if now >= next_collection_at:
                    try:
                        self.logger.info("collection cycle started")
                        payload = capture_collector_json(collector_args)
                        event_ids = queue.enqueue_json(payload)
                        self.logger.info(
                            "queued %s observation(s); queue_size=%s",
                            len(event_ids),
                            queue.count(),
                        )
                    except Exception:
                        self.logger.exception("collection cycle failed")
                    next_collection_at = time.time() + interval_seconds

                server_url = (self.config.get("server_url") or "").strip()
                if server_url:
                    delivered = drain_delivery_queue(
                        queue, server_url, timeout_seconds, batch_size,
                        retry_interval_seconds, retry_max_seconds, self.logger,
                    )
                    if delivered:
                        self.logger.info(
                            "delivered %s observation(s); queue_size=%s",
                            delivered,
                            queue.count(),
                        )

                wait_seconds = min(retry_interval_seconds, max(1, next_collection_at - time.time()))
                wait_result = win32event.WaitForSingleObject(
                    self.stop_event, int(wait_seconds * 1000)
                )
                if wait_result == win32event.WAIT_OBJECT_0:
                    break
        finally:
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

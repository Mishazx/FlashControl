# -*- coding: utf-8 -*-
"""Pure, stdlib-only helpers for agent heartbeat reporting."""

from __future__ import print_function

import json
import os
import uuid


def load_or_create_agent_id(path):
    try:
        with open(path, "r") as handle:
            return str(uuid.UUID(handle.read().strip()))
    except (IOError, OSError, ValueError):
        pass

    value = str(uuid.uuid4())
    temporary = path + ".tmp"
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(temporary, "w") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return value


def heartbeat_url(server_url, configured_url=""):
    if configured_url:
        return configured_url.strip()
    suffix = "/api/v1/observations"
    if server_url and server_url.rstrip("/").endswith(suffix):
        return server_url.rstrip("/")[:-len(suffix)] + "/api/v1/agents/heartbeat"
    return ""


def host_from_observation(json_text):
    try:
        try:
            from FlashControlAgent.observation_payload import expand_observations
        except ImportError:
            from observation_payload import expand_observations
        document = json.loads(json_text)
        if not isinstance(document, dict):
            return {}
        observations = expand_observations(document)
        if observations:
            host = observations[0].get("host")
            if isinstance(host, dict):
                return host
        host = document.get("host")
        return host if isinstance(host, dict) else {}
    except (TypeError, ValueError):
        return {}


def build_heartbeat(agent_id, agent_version, queue_size, host=None,
                    selected_route="direct", proxy_id=None):
    host = host or {}
    interfaces = host.get("network_interfaces") or []
    current_ips = list(host.get("ip_addresses") or [])
    for interface in interfaces:
        if not isinstance(interface, dict):
            continue
        for address in interface.get("addresses") or []:
            if isinstance(address, str) and address not in current_ips:
                current_ips.append(address)
            elif isinstance(address, dict):
                value = address.get("address") or address.get("ip")
                if value and value not in current_ips:
                    current_ips.append(value)
    return {
        "agent_id": agent_id,
        "agent_version": agent_version,
        "hostname": host.get("hostname") or os.environ.get("COMPUTERNAME") or "unknown",
        "domain": host.get("domain_name") or host.get("domain") or os.environ.get("USERDOMAIN"),
        "current_ips": current_ips,
        "queue_size": max(0, int(queue_size)),
        "selected_route": selected_route,
        "proxy_id": proxy_id,
    }


def current_ips(host):
    return build_heartbeat("00000000-0000-0000-0000-000000000000", "0", 0, host)["current_ips"]

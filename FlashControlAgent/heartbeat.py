# -*- coding: utf-8 -*-
"""Pure, stdlib-only helpers for agent heartbeat reporting."""

from __future__ import print_function

import json
import os
import socket
import uuid


def persist_agent_id(path, requested=None):
    if requested:
        value = str(uuid.UUID(str(requested).strip()))
    else:
        try:
            with open(path, "r") as handle:
                return str(uuid.UUID(handle.read().strip()))
        except (IOError, OSError, ValueError):
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


def load_or_create_agent_id(path):
    return persist_agent_id(path)


def persist_secret(path, value):
    text = str(value).strip()
    if not text:
        raise ValueError("secret must not be empty")
    temporary = path + ".tmp"
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(temporary, "w") as handle:
        handle.write(text + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return text


def forget_secret(path):
    """Remove an issued credential so the next service cycle can re-enroll."""
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def load_secret(path):
    try:
        with open(path, "r") as handle:
            value = handle.read().strip()
        return value or ""
    except (IOError, OSError):
        return ""


def delivery_credentials_configured(config):
    config = config or {}
    return bool(
        (config.get("machine_token") or "").strip()
        or (config.get("client_cert_file") or "").strip()
        or load_secret(config.get("machine_token_file") or "")
    )


def current_machine_token(config):
    config = config or {}
    configured = (config.get("machine_token") or "").strip()
    if configured:
        return configured
    return load_secret(config.get("machine_token_file") or "")


def collector_api_url(server_url, configured_url, suffix):
    if configured_url:
        return configured_url.strip()
    marker = "/api/v1/observations"
    if server_url and server_url.rstrip("/").endswith(marker):
        return server_url.rstrip("/")[:-len(marker)] + suffix
    return ""


def heartbeat_url(server_url, configured_url=""):
    return collector_api_url(server_url, configured_url, "/api/v1/agents/heartbeat")


def enroll_url(server_url, configured_url=""):
    return collector_api_url(server_url, configured_url, "/api/v1/agents/enroll")


def local_host_identity():
    hostname = os.environ.get("COMPUTERNAME") or socket.gethostname() or "unknown"
    domain = os.environ.get("USERDOMAIN")
    if domain and hostname and domain.strip().lower() == hostname.strip().lower():
        domain = None
    return {
        "hostname": hostname,
        "domain_name": domain,
        "ip_addresses": [],
    }


def build_enroll_payload(agent_id, agent_version, host=None):
    heartbeat = build_heartbeat(agent_id, agent_version, 0, host or local_host_identity())
    return {
        "agent_id": heartbeat["agent_id"],
        "agent_version": heartbeat["agent_version"],
        "hostname": heartbeat["hostname"],
        "domain": heartbeat["domain"],
        "current_ips": heartbeat["current_ips"],
    }


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
    hostname = host.get("hostname") or os.environ.get("COMPUTERNAME") or "unknown"
    # A populated host snapshot is authoritative.  On a workgroup machine it
    # intentionally has no domain; falling back to USERDOMAIN here turns the
    # workgroup name into a fictitious AD domain and prevents its heartbeat
    # from matching the computer created by observations.
    domain = host.get("domain_name") or host.get("domain")
    if domain is None and not host:
        domain = os.environ.get("USERDOMAIN")
    # Workgroup machines often expose COMPUTERNAME as USERDOMAIN.  It is not
    # an AD domain and must match the Observation's null domain.
    if domain and str(domain).strip().lower() == str(hostname).strip().lower():
        domain = None
    return {
        "agent_id": agent_id,
        "agent_version": agent_version,
        "hostname": hostname,
        "domain": domain,
        "current_ips": current_ips,
        "queue_size": max(0, int(queue_size)),
        "selected_route": selected_route,
        "proxy_id": proxy_id,
    }


def current_ips(host):
    return build_heartbeat("00000000-0000-0000-0000-000000000000", "0", 0, host)["current_ips"]

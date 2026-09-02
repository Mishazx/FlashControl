# -*- coding: utf-8 -*-
"""Route selection for direct Main or site Proxy delivery."""

from __future__ import print_function

import ipaddress


def select_proxy(proxies, current_ips):
    best = None
    best_prefix = -1
    addresses = []
    for value in current_ips or []:
        try:
            addresses.append(ipaddress.ip_address(value))
        except ValueError:
            continue
    for proxy in proxies or []:
        if not isinstance(proxy, dict) or not proxy.get("server_url"):
            continue
        for cidr in proxy.get("networks") or []:
            try:
                network = ipaddress.ip_network(cidr)
            except ValueError:
                continue
            if network.prefixlen <= best_prefix:
                continue
            if any(address.version == network.version and address in network for address in addresses):
                best, best_prefix = proxy, network.prefixlen
    return best

"""Destination checks for provider traffic.

An ambient proxy, a redirect, and a DNS name that resolves to a private or
link-local address are different destinations. They are refused before a
credential-bearing socket is opened. An address written in the provider URL
is the destination the person configured, including a loopback IP for a local
model. This module does not grant network access and does not open a socket
of its own except the resolver lookup inside ``review_destination``.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit


class EgressDenied(ValueError):
    """The configured URL is not the peer this transport may use."""


@dataclass(frozen=True)
class ReviewedDestination:
    hostname: str
    port: int
    ips: tuple[str, ...]
    scheme: str


def _special(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


def _address_is_ip(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _ips(hostname: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise EgressDenied("provider host did not resolve") from exc
    found: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address.startswith("::ffff:"):
            address = address.removeprefix("::ffff:")
        if address not in found:
            found.append(address)
    if not found:
        raise EgressDenied("provider host did not resolve")
    return tuple(found)


def review_destination(url: str) -> ReviewedDestination:
    """Refuse a proxy, a private resolution of a name, or a URL that is not HTTP(S)."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise EgressDenied("provider URL must be an HTTP(S) URL with a host")
    if parsed.username or parsed.password:
        raise EgressDenied("provider URL must not contain embedded credentials")
    proxy = urllib.request.getproxies().get(parsed.scheme)
    if proxy and not urllib.request.proxy_bypass(parsed.netloc):
        raise EgressDenied("an ambient proxy is a different destination and is not authorized")
    hostname = parsed.hostname.casefold().rstrip(".")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = _ips(hostname, port)
    if not _address_is_ip(hostname):
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise EgressDenied("provider host did not resolve") from exc
            if _special(ip):
                raise EgressDenied("provider host resolved to an unexpected private address")
    return ReviewedDestination(hostname, port, addresses, parsed.scheme)


__all__ = ["EgressDenied", "ReviewedDestination", "review_destination"]

"""Destination checks for provider traffic.

An ambient proxy, a redirect, and a DNS name that resolves to a non-global
address are different destinations. They are refused before a
credential-bearing socket is opened. An address written in the provider URL
is the destination the person configured, including a loopback IP for a local
model. ``review_destination`` only resolves. ``open_reviewed`` dials that
reviewed address; the Host header and the TLS name stay the configured hostname.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
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
    # ``not is_global`` covers CGNAT (100.64.0.0/10). The explicit flags stay
    # because some IPv6 addresses are both global and reserved or multicast.
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified or not ip.is_global)


def cleartext_loopback_host(host: str) -> bool:
    """True for ``localhost`` or an IP that is actually loopback.

    A name that merely begins with ``127.`` is a different host.
    """
    name = host.casefold().rstrip(".")
    if name == "localhost":
        return True
    try:
        return bool(ipaddress.ip_address(name).is_loopback)
    except ValueError:
        return False


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


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Dial ``peer`` while ``host`` stays the name used for the Host header."""

    def __init__(self, host, port=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None, blocksize=8192, *, peer: str):
        super().__init__(host, port, timeout, source_address, blocksize)
        self._peer = peer

    def connect(self):
        self.sock = self._create_connection(
            (self._peer, self.port), self.timeout, self.source_address)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    default_port = http.client.HTTPS_PORT

    def __init__(self, host, port=None, *, peer: str,
                 timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None,
                 context=None, blocksize=8192):
        super().__init__(host, port, timeout, source_address, blocksize, peer=peer)
        self._context = context if context is not None else ssl.create_default_context()

    def connect(self):
        super().connect()
        server_hostname = self._tunnel_host or self.host
        try:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)
        except BaseException:
            self.sock.close()
            self.sock = None
            raise


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, peer: str):
        super().__init__()
        self._peer = peer

    def http_open(self, req):
        peer = self._peer

        def factory(host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kwargs):
            return _PinnedHTTPConnection(host, peer=peer, timeout=timeout, **kwargs)

        return self.do_open(factory, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, peer: str):
        super().__init__()
        self._peer = peer

    def https_open(self, req):
        peer = self._peer

        def factory(host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, context=None, **kwargs):
            return _PinnedHTTPSConnection(
                host, peer=peer, timeout=timeout, context=context or self._context, **kwargs)

        return self.do_open(factory, req, context=self._context)


def open_reviewed(destination: ReviewedDestination,
                  redirect_handler: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
    """Opener that dials ``destination.ips[0]`` and does not use an ambient proxy."""
    peer = destination.ips[0]
    if destination.scheme == "https":
        transport = _PinnedHTTPSHandler(peer)
    elif destination.scheme == "http":
        transport = _PinnedHTTPHandler(peer)
    else:
        raise EgressDenied("provider URL must be an HTTP(S) URL with a host")
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), redirect_handler, transport)


__all__ = ["EgressDenied", "ReviewedDestination", "cleartext_loopback_host",
           "open_reviewed", "review_destination"]

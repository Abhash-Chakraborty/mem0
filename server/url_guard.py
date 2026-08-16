"""Outbound URL validation for webhook delivery.

Webhook targets are supplied by an admin and then fetched by the server, which
makes them a server-side request forgery vector: a URL like
``http://169.254.169.254/latest/meta-data/`` turns the delivery worker into a
proxy for the cloud metadata service, and ``http://127.0.0.1:5432`` lets an
endpoint probe services that are only reachable from inside the network.

Two checks, because either alone is insufficient:

* The URL is validated when it is saved, so a bad target is rejected with a
  clear message rather than failing silently later.
* The resolved address is checked again immediately before each delivery, since
  DNS is not stable - a hostname that resolved to a public address at save time
  can be repointed at a private one afterwards (a DNS rebinding attack).

Deliberately allows private targets when MEM0_ALLOW_PRIVATE_WEBHOOKS is set:
a self-hosted instance posting to another container on the same Docker network
is a legitimate and common setup, and refusing it outright would push people to
disable the guard entirely.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

ALLOW_PRIVATE = os.environ.get("MEM0_ALLOW_PRIVATE_WEBHOOKS", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeWebhookURL(ValueError):
    """The URL points somewhere the server must not be made to fetch."""


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Addresses that must never be fetched on a caller's behalf."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # 169.254.0.0/16 - cloud metadata lives here
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_addresses(host: str) -> list[str]:
    """Every address the host resolves to. Raises UnsafeWebhookURL if none."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeWebhookURL(f"Could not resolve host {host!r}.") from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise UnsafeWebhookURL(f"Host {host!r} resolved to no addresses.")
    return addresses


def validate_webhook_url(url: str, *, resolve: bool = True) -> None:
    """Raise UnsafeWebhookURL if this URL must not be fetched.

    ``resolve=False`` skips the DNS lookup and checks only the URL's shape,
    for callers that cannot afford a network round trip.
    """
    parts = urlsplit(url)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeWebhookURL(
            f"Webhook URLs must use http or https, not {parts.scheme or 'an empty scheme'}."
        )

    host = parts.hostname
    if not host:
        raise UnsafeWebhookURL("Webhook URL has no host.")

    if ALLOW_PRIVATE:
        return

    # A literal IP needs no DNS lookup, and checking it directly means a
    # resolver failure cannot be used to bypass the check.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if _is_blocked(literal):
            raise UnsafeWebhookURL(
                f"{host} is a private or reserved address. Set "
                "MEM0_ALLOW_PRIVATE_WEBHOOKS=true to allow internal targets."
            )
        return

    if not resolve:
        return

    for address in resolve_addresses(host):
        if _is_blocked(ipaddress.ip_address(address)):
            raise UnsafeWebhookURL(
                f"{host} resolves to {address}, a private or reserved address. Set "
                "MEM0_ALLOW_PRIVATE_WEBHOOKS=true to allow internal targets."
            )

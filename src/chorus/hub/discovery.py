"""Find Harmony Hubs on the local network over SSDP.

Hub-based remotes (Hub, Elite, Companion, Ultimate, Smart Control) keep
their configuration on the hub rather than in the remote, and the hub speaks
a local API -- so unlike the USB remotes, these never needed the cloud at
all once set up.
"""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass

SSDP_ADDRESS = "239.255.255.250"
SSDP_PORT = 1900
#: The hub's own SSDP service type.
HARMONY_ST = "urn:myharmony-com:device:harmony:1"

_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDRESS}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    f"ST: {HARMONY_ST}\r\n"
    "\r\n"
)


@dataclass(frozen=True)
class DiscoveredHub:
    """A hub that answered an SSDP search."""

    address: str
    friendly_name: str = ""
    uuid: str = ""
    location: str = ""
    raw: str = ""

    def __str__(self) -> str:
        label = self.friendly_name or "Harmony Hub"
        return f"{label} at {self.address}"


def _parse_headers(payload: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in payload.splitlines()[1:]:
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return headers


def discover(timeout: float = 4.0, *, retries: int = 2) -> list[DiscoveredHub]:
    """Broadcast an SSDP search and collect the hubs that reply.

    Returns an empty list if nothing answers -- which on a network with
    client isolation or across VLANs is common even when a hub is present.
    In that case connect by IP address directly.
    """
    found: dict[str, DiscoveredHub] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)

    try:
        for _ in range(max(1, retries)):
            try:
                sock.sendto(_MSEARCH.encode(), (SSDP_ADDRESS, SSDP_PORT))
            except OSError:
                continue

        deadline_sock = sock
        while True:
            try:
                data, addr = deadline_sock.recvfrom(4096)
            except TimeoutError:
                break
            except OSError:
                break

            payload = data.decode("utf-8", errors="replace")
            if HARMONY_ST not in payload and "harmony" not in payload.lower():
                continue

            headers = _parse_headers(payload)
            address = addr[0]
            uuid = headers.get("usn", "")
            match = re.search(r"uuid:([0-9a-fA-F-]+)", uuid)
            found[address] = DiscoveredHub(
                address=address,
                friendly_name=headers.get("friendlyname", ""),
                uuid=match.group(1) if match else "",
                location=headers.get("location", ""),
                raw=payload,
            )
    finally:
        sock.close()

    return sorted(found.values(), key=lambda h: h.address)

"""A minimal RFC 6455 WebSocket client.

Written against the standard library so that talking to a Harmony Hub needs
no third-party packages. It implements exactly the subset the hub's API
uses: a client-side handshake, masked text frames, fragment reassembly, and
ping/pong.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
from urllib.parse import urlparse

from ..errors import HubError

#: The magic value RFC 6455 appends before hashing the client key.
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WebSocket:
    """A synchronous WebSocket client connection."""

    def __init__(self, url: str, *, origin: str = "", timeout: float = 10.0):
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss"):
            raise HubError(f"unsupported WebSocket scheme {parsed.scheme!r}")
        if parsed.scheme == "wss":
            raise HubError(
                "wss:// is not supported; Harmony Hubs serve plain ws:// on "
                "port 8088"
            )

        self.host = parsed.hostname or ""
        self.port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        self._buffer = b""
        self._closed = False
        try:
            self._sock = socket.create_connection(
                (self.host, self.port), timeout=timeout
            )
        except OSError as exc:
            raise HubError(
                f"could not connect to {self.host}:{self.port}: {exc}"
            ) from exc
        self._sock.settimeout(timeout)
        self._handshake(path, origin)

    # -- handshake --------------------------------------------------------

    def _handshake(self, path: str, origin: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        if origin:
            lines.append(f"Origin: {origin}")
        request = "\r\n".join(lines) + "\r\n\r\n"
        self._sock.sendall(request.encode())

        header = self._read_until(b"\r\n\r\n")
        text = header.decode("latin-1")
        status = text.split("\r\n", 1)[0]
        if "101" not in status:
            raise HubError(
                f"WebSocket upgrade refused: {status.strip()!r}. If this is a "
                "Harmony Hub, check the IP address and that firmware is "
                "4.15.206 or newer."
            )

        expected = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode()).digest()
        ).decode()
        for line in text.split("\r\n"):
            if line.lower().startswith("sec-websocket-accept:"):
                if line.partition(":")[2].strip() != expected:
                    raise HubError("WebSocket handshake key mismatch")
                break

    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self._buffer:
            chunk = self._recv()
            if not chunk:
                raise HubError("connection closed during handshake")
        head, _, rest = self._buffer.partition(marker)
        self._buffer = rest
        return head + marker

    def _recv(self) -> bytes:
        try:
            chunk = self._sock.recv(65536)
        except TimeoutError as exc:
            raise HubError("timed out waiting for the hub") from exc
        except OSError as exc:
            raise HubError(f"socket error: {exc}") from exc
        self._buffer += chunk
        return chunk

    def _need(self, count: int) -> bytes:
        while len(self._buffer) < count:
            if not self._recv():
                raise HubError("connection closed mid-frame")
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    # -- frames -----------------------------------------------------------

    def send(self, payload: str, opcode: int = OP_TEXT) -> None:
        """Send one masked frame. Clients must always mask (RFC 6455 §5.3)."""
        if self._closed:
            raise HubError("WebSocket is closed")
        data = payload.encode("utf-8")
        header = bytearray([0x80 | opcode])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)

        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        try:
            self._sock.sendall(bytes(header) + masked)
        except OSError as exc:
            raise HubError(f"send failed: {exc}") from exc

    def recv(self, timeout: float | None = None) -> str | None:
        """Receive one message, reassembling fragments.

        Returns None when the peer closes the connection. Answers pings
        automatically.
        """
        if timeout is not None:
            self._sock.settimeout(timeout)

        chunks: list[bytes] = []
        message_opcode: int | None = None

        while True:
            first, second = self._need(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F

            if length == 126:
                (length,) = struct.unpack("!H", self._need(2))
            elif length == 127:
                (length,) = struct.unpack("!Q", self._need(8))

            mask = self._need(4) if masked else b""
            payload = self._need(length) if length else b""
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

            if opcode == OP_CLOSE:
                self._closed = True
                return None
            if opcode == OP_PING:
                self.send(payload.decode("utf-8", "replace"), OP_PONG)
                continue
            if opcode == OP_PONG:
                continue

            if opcode != OP_CONTINUATION:
                message_opcode = opcode
            chunks.append(payload)

            if fin:
                data = b"".join(chunks)
                if message_opcode == OP_BINARY:
                    return data.decode("utf-8", "replace")
                return data.decode("utf-8", "replace")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.send("", OP_CLOSE)
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass

    def __enter__(self) -> WebSocket:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

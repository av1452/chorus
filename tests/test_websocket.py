"""WebSocket client tests against a scripted server."""

import base64
import hashlib
import socket
import struct
import threading

import pytest

from harmonyforge.errors import HubError
from harmonyforge.hub.websocket import OP_TEXT, WebSocket

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class ScriptedServer:
    """Accepts one connection, completes the handshake, runs a script."""

    def __init__(self, script, *, refuse=False):
        self.script = script
        self.refuse = refuse
        self.received = []
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        conn, _ = self._sock.accept()
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                request += chunk

            if self.refuse:
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return

            key = next(
                line.split(":", 1)[1].strip()
                for line in request.decode().split("\r\n")
                if line.lower().startswith("sec-websocket-key")
            )
            accept = base64.b64encode(
                hashlib.sha1((key + WS_GUID).encode()).digest()
            ).decode()
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )
            self.script(conn, self)
        finally:
            conn.close()
            self._sock.close()

    @staticmethod
    def read_client_frame(conn):
        """Read one masked client frame and return its unmasked payload."""
        header = conn.recv(2)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", conn.recv(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", conn.recv(8))[0]
        mask = conn.recv(4)
        data = b""
        while len(data) < length:
            data += conn.recv(length - len(data))
        return bytes(b ^ mask[i % 4] for i, b in enumerate(data))

    @staticmethod
    def text(payload: bytes, *, fin=True, opcode=OP_TEXT):
        first = (0x80 if fin else 0x00) | opcode
        if len(payload) < 126:
            return bytes([first, len(payload)]) + payload
        return bytes([first, 126]) + struct.pack("!H", len(payload)) + payload


def test_handshake_masking_and_echo():
    def script(conn, server):
        server.received.append(ScriptedServer.read_client_frame(conn))
        conn.sendall(ScriptedServer.text(b"pong"))

    server = ScriptedServer(script)
    with WebSocket(f"ws://127.0.0.1:{server.port}/", origin="http://sleekxmpp") as ws:
        ws.send('{"hello":"wörld"}')
        assert ws.recv(timeout=5) == "pong"
    server.thread.join(timeout=5)
    assert server.received[0].decode() == '{"hello":"wörld"}'


def test_fragment_reassembly():
    def script(conn, server):
        conn.sendall(ScriptedServer.text(b"he", fin=False))
        conn.sendall(ScriptedServer.text(b"llo ", fin=False, opcode=0x0))
        conn.sendall(ScriptedServer.text(b"world", fin=True, opcode=0x0))

    server = ScriptedServer(script)
    with WebSocket(f"ws://127.0.0.1:{server.port}/") as ws:
        assert ws.recv(timeout=5) == "hello world"


def test_ping_is_answered_transparently():
    def script(conn, server):
        conn.sendall(bytes([0x89, 0x00]))  # ping
        server.received.append(ScriptedServer.read_client_frame(conn))  # our pong
        conn.sendall(ScriptedServer.text(b"after-ping"))

    server = ScriptedServer(script)
    with WebSocket(f"ws://127.0.0.1:{server.port}/") as ws:
        assert ws.recv(timeout=5) == "after-ping"
    server.thread.join(timeout=5)


def test_extended_length_payload():
    big = b"y" * 500

    def script(conn, server):
        conn.sendall(ScriptedServer.text(big))

    server = ScriptedServer(script)
    with WebSocket(f"ws://127.0.0.1:{server.port}/") as ws:
        assert ws.recv(timeout=5) == big.decode()


def test_close_frame_returns_none():
    def script(conn, server):
        conn.sendall(bytes([0x88, 0x00]))

    server = ScriptedServer(script)
    with WebSocket(f"ws://127.0.0.1:{server.port}/") as ws:
        assert ws.recv(timeout=5) is None


def test_refused_upgrade_is_reported():
    server = ScriptedServer(lambda c, s: None, refuse=True)
    with pytest.raises(HubError, match="upgrade refused"):
        WebSocket(f"ws://127.0.0.1:{server.port}/")


def test_unreachable_host_is_reported():
    with pytest.raises(HubError, match="could not connect"):
        WebSocket("ws://127.0.0.1:1/", timeout=1.0)


def test_wss_and_bad_scheme_are_rejected():
    with pytest.raises(HubError, match="not supported"):
        WebSocket("wss://example.invalid/")
    with pytest.raises(HubError, match="unsupported WebSocket scheme"):
        WebSocket("http://example.invalid/")


def test_send_after_close_raises():
    server = ScriptedServer(lambda c, s: c.sendall(bytes([0x88, 0x00])))
    ws = WebSocket(f"ws://127.0.0.1:{server.port}/")
    ws.recv(timeout=5)
    with pytest.raises(HubError, match="closed"):
        ws.send("nope")

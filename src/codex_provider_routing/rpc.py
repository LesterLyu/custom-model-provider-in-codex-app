"""Small WebSocket JSON-RPC client, including Codex proxy's raw stdio tunnel."""
import base64
import contextlib
import hashlib
import json
import os
import select
import socket
import struct
import subprocess
import time


class ProxyTransport:
    def __init__(self, cli, home):
        env = dict(os.environ, CODEX_HOME=str(home))
        self.proc = subprocess.Popen([str(cli), "app-server", "proxy"], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0)
        self.timeout = 15

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        view = memoryview(data)
        while view:
            written = os.write(self.proc.stdin.fileno(), view)
            if written <= 0:
                raise EOFError("Proxy closed its input")
            view = view[written:]

    def recv(self, count):
        if not select.select([self.proc.stdout], [], [], self.timeout)[0]:
            raise TimeoutError("Codex proxy timed out")
        return os.read(self.proc.stdout.fileno(), count)

    def close(self):
        self.proc.stdin.close()
        self.proc.stdout.close()
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


class Client:
    def __init__(self, path=None, transport=None):
        self.sock = transport or socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.buffer = b""
        self.seq = 0
        self.closed = False
        self.sock.settimeout(15)
        try:
            if transport is None:
                self.sock.connect(str(path))
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall(("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                               "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                               f"Sec-WebSocket-Key: {key}\r\n\r\n").encode())
            while b"\r\n\r\n" not in self.buffer:
                self._more(4096)
                if len(self.buffer) > 65536:
                    raise RuntimeError("Oversized WebSocket handshake")
            header, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            headers = {k.strip().lower(): v.strip() for line in header.split(b"\r\n")[1:]
                       if b":" in line for k, v in [line.split(b":", 1)]}
            if not header.startswith(b"HTTP/1.1 101 ") or headers.get(b"sec-websocket-accept") != accept:
                raise RuntimeError("Invalid WebSocket upgrade response")
            self.rpc("initialize", {"clientInfo": {"name": "provider_routing", "version": "0.1.0"},
                                    "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
        except BaseException:
            self.close()
            raise

    def _more(self, count):
        data = self.sock.recv(count)
        if not data:
            raise EOFError("Codex closed the connection")
        self.buffer += data

    def read(self, count):
        while len(self.buffer) < count:
            self._more(max(4096, count - len(self.buffer)))
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def frame(self, payload, opcode=1):
        size = len(payload)
        header = bytes([0x80 | opcode, 0x80 | size]) if size < 126 else (
            bytes([0x80 | opcode, 0xfe]) + struct.pack("!H", size) if size < 65536 else
            bytes([0x80 | opcode, 0xff]) + struct.pack("!Q", size))
        mask = os.urandom(4)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, message):
        self.frame(json.dumps(message).encode())

    def receive(self):
        parts = []
        total = 0
        while True:
            a, b = self.read(2)
            size = b & 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            total += size
            if total > 32 * 1024 * 1024:
                raise RuntimeError("Oversized control message")
            mask = self.read(4) if b & 128 else None
            payload = self.read(size)
            if mask:
                payload = bytes(x ^ mask[i % 4] for i, x in enumerate(payload))
            opcode = a & 15
            if opcode == 8:
                raise EOFError("Codex sent a close frame")
            if opcode == 9:
                self.frame(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise RuntimeError("Unexpected control message type")
            parts.append(payload)
            if a & 128:
                return json.loads(b"".join(parts))

    def rpc(self, method, params):
        self.seq += 1
        request_id = f"provider-routing:{self.seq}"
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = self.receive()
            if isinstance(response, dict) and response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError("Codex RPC failed: " + method)
                return response["result"]
        raise TimeoutError(method)

    def close(self):
        if not self.closed:
            self.closed = True
            with contextlib.suppress(OSError, EOFError):
                self.frame(b"", opcode=8)
            self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

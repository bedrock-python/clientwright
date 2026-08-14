"""Fault-injecting HTTP origin on the standard library, for conformance tests.

Routes:
- ``/echo``                      200 with a small JSON body (method, path, headers echo)
- ``/status/{code}``             responds with that status
- ``/slow/{seconds}``            sleeps, then 200
- ``/redirect/{n}``              302 chain of n hops ending at /echo
- ``/redirect-loop``             302 to itself forever
- ``/flaky/{key}/{fails}``       first {fails} requests per key answer 503, then 200
- ``/retry-after/{seconds}``     503 with a Retry-After header
- ``/disconnect``                closes the connection without a response

Chaos routes (mid-stream and protocol-level faults):
- ``/hang-body/{seconds}``           200 announcing 10 bytes: 3 arrive, the rest after the stall
- ``/drop-body``                     200 announcing 10 bytes but the connection dies after 3
- ``/garbage``                       raw non-HTTP bytes instead of a status line
- ``/reset``                         hard TCP reset (SO_LINGER 0) instead of a response
- ``/flaky-disconnect/{key}/{fails}``  first {fails} requests per key drop the connection, then 200
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: OriginServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _reply(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self) -> None:
        server = self.server
        with server.lock:
            server.requests.append((self.command, self.path))
        # ALWAYS drain the request body: on keep-alive reuse, unread body bytes
        # would be parsed as the start of the next request line.
        length = int(self.headers.get("Content-Length") or 0)
        request_body = self.rfile.read(length) if length else b""
        parts = [part for part in self.path.split("?")[0].split("/") if part]
        if not parts or parts[0] == "echo":
            payload = {
                "method": self.command,
                "path": self.path,
                "headers": {name.lower(): value for name, value in self.headers.items()},
                "body": request_body.decode("utf-8", errors="replace"),
            }
            self._reply(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})
            return
        if parts[0] == "status":
            self._reply(int(parts[1]))
            return
        if parts[0] == "slow":
            time.sleep(float(parts[1]))
            self._reply(200, b"slow")
            return
        if parts[0] == "redirect":
            hops = int(parts[1])
            target = "/echo" if hops <= 1 else f"/redirect/{hops - 1}"
            self._reply(302, headers={"Location": target})
            return
        if parts[0] == "redirect-loop":
            self._reply(302, headers={"Location": "/redirect-loop"})
            return
        if parts[0] == "flaky":
            key, fails = parts[1], int(parts[2])
            with server.lock:
                seen = server.flaky_counters.get(key, 0)
                server.flaky_counters[key] = seen + 1
            if seen < fails:
                self._reply(503, b"flaky")
            else:
                self._reply(200, b"recovered")
            return
        if parts[0] == "retry-after":
            self._reply(503, b"", {"Retry-After": parts[1]})
            return
        if parts[0] == "disconnect":
            self.close_connection = True
            self.connection.close()
            return
        if parts[0] == "hang-body":
            body = b"0123456789"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body[:3])
            self.wfile.flush()
            time.sleep(float(parts[1]))
            try:
                self.wfile.write(body[3:])
            except OSError:  # the client gave up mid-stall; routine for this route
                self.close_connection = True
            return
        if parts[0] == "drop-body":
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.write(b"abc")
            self.wfile.flush()
            self.close_connection = True
            self.connection.close()
            return
        if parts[0] == "garbage":
            self.close_connection = True
            self.wfile.write(b"\x16\x03\x01 banana instead of a status line\r\n\r\n")
            self.wfile.flush()
            self.connection.close()
            return
        if parts[0] == "reset":
            self.close_connection = True
            # SO_LINGER with a zero timeout turns close() into a TCP RST.
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            self.connection.close()
            return
        if parts[0] == "flaky-disconnect":
            key, fails = parts[1], int(parts[2])
            with server.lock:
                seen = server.flaky_counters.get(key, 0)
                server.flaky_counters[key] = seen + 1
            if seen < fails:
                self.close_connection = True
                self.connection.close()
                return
            self._reply(200, b"recovered")
            return
        self._reply(404)

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()


class OriginServer(ThreadingHTTPServer):
    """Context-managed origin bound to an ephemeral localhost port."""

    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        """Silence per-connection tracebacks: aborted clients are the point here."""
        return None

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.Lock()
        self.requests: list[tuple[str, str]] = []
        self.flaky_counters: dict[str, int] = {}
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        raw_host, port = self.server_address[0], self.server_address[1]
        host = raw_host.decode() if isinstance(raw_host, bytes) else raw_host
        return f"http://{host}:{port}"

    def request_count(self, path_prefix: str) -> int:
        with self.lock:
            return sum(1 for _, path in self.requests if path.startswith(path_prefix))

    def __enter__(self) -> OriginServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.shutdown()
        self.server_close()


__all__ = ["OriginServer"]

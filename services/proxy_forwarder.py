"""Local authenticated proxy forwarder to avoid browser auth popups."""

from __future__ import annotations

import base64
import logging
import select
import socket
import socketserver
import ssl
import threading
from typing import Optional

from core.proxy_manager import parse_proxy_parts

logger = logging.getLogger(__name__)


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ForwarderHandler(socketserver.StreamRequestHandler):
    """Handle a single browser connection and relay it via the upstream proxy."""

    timeout = 20

    def handle(self) -> None:
        try:
            request_line = self.rfile.readline(65536)
            if not request_line:
                return

            parts = request_line.decode("latin1", errors="replace").rstrip("\r\n").split(" ", 2)
            if len(parts) != 3:
                return

            method, target, version = parts
            headers = self._read_headers()

            if method.upper() == "CONNECT":
                self._handle_connect(target, version, headers)
            else:
                self._handle_http(method, target, version, headers)
        except Exception as exc:
            logger.debug("Local proxy forwarder handler error: %s", exc)

    def _read_headers(self) -> list[str]:
        headers: list[str] = []
        while True:
            line = self.rfile.readline(65536)
            if line in (b"", b"\r\n", b"\n"):
                break
            headers.append(line.decode("latin1", errors="replace").rstrip("\r\n"))
        return headers

    def _read_body(self, headers: list[str]) -> bytes:
        content_length = 0
        for header in headers:
            if ":" not in header:
                continue
            name, value = header.split(":", 1)
            if name.strip().lower() == "content-length":
                try:
                    content_length = int(value.strip())
                except (TypeError, ValueError):
                    content_length = 0
                break
        return self.rfile.read(content_length) if content_length > 0 else b""

    def _open_upstream(self) -> socket.socket:
        upstream = socket.create_connection(
            (self.server.upstream_host, self.server.upstream_port),
            timeout=20,
        )
        if self.server.upstream_scheme == "https":
            context = ssl.create_default_context()
            upstream = context.wrap_socket(
                upstream,
                server_hostname=self.server.upstream_host,
            )
        return upstream

    def _build_header_block(self, headers: list[str], close_connection: bool) -> str:
        filtered: list[str] = []
        for header in headers:
            if ":" not in header:
                continue
            name, value = header.split(":", 1)
            lowered = name.strip().lower()
            if lowered in {"proxy-authorization", "proxy-connection", "connection"}:
                continue
            filtered.append(f"{name.strip()}: {value.strip()}")

        if close_connection:
            filtered.append("Connection: close")
            filtered.append("Proxy-Connection: close")

        filtered.append(f"Proxy-Authorization: {self.server.proxy_auth_header}")
        return "\r\n".join(filtered) + "\r\n\r\n"

    def _read_response_head(self, upstream: socket.socket) -> bytes:
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = upstream.recv(4096)
            if not chunk:
                break
            response += chunk
            if len(response) > 65536:
                break
        return response

    def _handle_connect(self, target: str, version: str, headers: list[str]) -> None:
        upstream = self._open_upstream()
        try:
            request = (
                f"CONNECT {target} {version}\r\n"
                f"Host: {target}\r\n"
                f"{self._build_header_block(headers, close_connection=False)}"
            )
            upstream.sendall(request.encode("latin1", errors="replace"))
            response_head = self._read_response_head(upstream)
            if response_head:
                self.connection.sendall(response_head)
            if not (
                response_head.startswith(b"HTTP/1.1 200")
                or response_head.startswith(b"HTTP/1.0 200")
            ):
                return
            self._pipe_bidirectional(self.connection, upstream)
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def _handle_http(self, method: str, target: str, version: str, headers: list[str]) -> None:
        upstream = self._open_upstream()
        try:
            body = self._read_body(headers)
            request = (
                f"{method} {target} {version}\r\n"
                f"{self._build_header_block(headers, close_connection=True)}"
            ).encode("latin1", errors="replace") + body
            upstream.sendall(request)
            while True:
                chunk = upstream.recv(65536)
                if not chunk:
                    break
                self.connection.sendall(chunk)
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    def _pipe_bidirectional(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets = [client, upstream]
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 20)
            if errored:
                return
            if not readable:
                return
            for sock in readable:
                try:
                    data = sock.recv(65536)
                except Exception:
                    return
                if not data:
                    return
                other = upstream if sock is client else client
                try:
                    other.sendall(data)
                except Exception:
                    return


class _ForwarderServer(_ThreadingTCPServer):
    def __init__(self, proxy_url: str):
        parts = parse_proxy_parts(proxy_url)
        scheme = str(parts["scheme"] or "http").lower()
        if scheme not in {"http", "https"}:
            raise ValueError(f"Unsupported upstream proxy scheme for local forwarder: {scheme}")

        username = str(parts["username"] or "")
        if not username:
            raise ValueError("Authenticated proxy forwarder requires a proxy username.")

        password = str(parts["password"] or "")
        self.upstream_scheme = scheme
        self.upstream_host = str(parts["host"] or "")
        self.upstream_port = int(parts["port"] or 0)
        self.proxy_auth_header = (
            "Basic "
            + base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        )
        super().__init__(("127.0.0.1", 0), _ForwarderHandler)


class AuthenticatedProxyForwarder:
    """Expose an unauthenticated local proxy that forwards through an authenticated upstream proxy."""

    def __init__(self, proxy_url: str) -> None:
        self.proxy_url = proxy_url
        self._server: Optional[_ForwarderServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def local_proxy_url(self) -> str:
        if not self._server:
            raise RuntimeError("Forwarder has not been started.")
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> "AuthenticatedProxyForwarder":
        if self._server:
            return self
        self._server = _ForwarderServer(self.proxy_url)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="autopixel-proxy-forwarder",
            daemon=True,
        )
        self._thread.start()
        logger.info("Started local proxy forwarder at %s", self.local_proxy_url)
        return self

    def stop(self) -> None:
        if not self._server:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2)
            self._server = None
            self._thread = None


__all__ = ["AuthenticatedProxyForwarder"]

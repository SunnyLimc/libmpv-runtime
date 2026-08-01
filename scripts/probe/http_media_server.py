from __future__ import annotations

import argparse
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import unquote, urlsplit


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    """HTTP fixture server whose loopback bind never depends on DNS."""

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class Handler(BaseHTTPRequestHandler):
    root: Path

    def do_GET(self) -> None:
        self._serve(include_body=True)

    def do_HEAD(self) -> None:
        self._serve(include_body=False)

    def _serve(self, *, include_body: bool) -> None:
        requested = unquote(urlsplit(self.path).path).lstrip("/")
        path = (self.root / requested).resolve()
        if self.root not in path.parents or not path.is_file():
            self.send_error(404)
            return
        size = path.stat().st_size
        start = 0
        end = size - 1
        status = 200
        value = self.headers.get("Range")
        if value:
            match = re.fullmatch(r"bytes=([0-9]+)-([0-9]*)", value)
            if not match:
                self.send_error(416)
                return
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else end
            if start > end or end >= size:
                self.send_error(416)
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not include_body:
            return
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                block = source.read(min(64 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", required=True, type=Path)
    arguments = parser.parse_args()
    Handler.root = arguments.root.resolve()
    server = LocalThreadingHTTPServer(("127.0.0.1", arguments.port), Handler)
    arguments.port_file.write_text(str(server.server_port), encoding="ascii")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

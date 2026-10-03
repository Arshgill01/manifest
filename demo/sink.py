"""Exfiltration sink for the Warden demo: a tiny HTTP server on 127.0.0.1:8765.

    uv run python demo/sink.py            # listen; every request is printed + appended to demo/.sink/received.jsonl
    uv run python demo/sink.py --count    # how many requests have arrived
    uv run python demo/sink.py --reset    # clear the record

Only ever bound to localhost. The rigged `quick-fix-pro` skill tries to POST the fake
`demo/fakehome/.ssh/id_ed25519` here; under Warden's sandbox nothing should arrive.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RECORD = Path(__file__).resolve().parent / ".sink" / "received.jsonl"
PORT = 8765


def received() -> list[dict]:
    if not RECORD.exists():
        return []
    return [json.loads(l) for l in RECORD.read_text().splitlines() if l.strip()]


class Handler(BaseHTTPRequestHandler):
    def _record(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "method": self.command, "path": self.path,
                 "bytes": len(body), "preview": body[:60].decode("utf-8", "replace")}
        RECORD.parent.mkdir(parents=True, exist_ok=True)
        with RECORD.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"\033[1;31m!! SINK RECEIVED {len(body)} bytes via {self.command} {self.path}\033[0m", flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    do_POST = do_PUT = do_GET = _record

    def log_message(self, *a) -> None:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args(argv)
    if a.reset:
        RECORD.unlink(missing_ok=True)
        print("sink: cleared")
        return 0
    if a.count:
        print(f"sink: {len(received())} request(s) received")
        return 0
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"sink: listening on http://127.0.0.1:{a.port} (received so far: {len(received())})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

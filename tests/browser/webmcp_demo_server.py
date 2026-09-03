"""Range-capable static server for the WebMCP demo smoke test.

Chromium reports ``seekable: [0, 0]`` for media served without HTTP Range
support and silently ignores seeks, which breaks the playback round trip
the smoke test verifies (v0.10 plan section 17.5: the deployed host must
support Range). Python's built-in ``http.server`` does not implement
Range, so CI and local verification use this small stdlib server instead:

    python tests/browser/webmcp_demo_server.py --port 8770 --directory build/webmcp-demo
"""

from __future__ import annotations

import argparse
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RANGE_HEADER = re.compile(r"bytes=(\d*)-(\d*)$")


class RangeFileHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path) or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        content_type = self.guess_type(path) or "application/octet-stream"
        match = RANGE_HEADER.fullmatch((self.headers.get("Range") or "").strip())
        if match is None:
            handle = open(path, "rb")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return handle

        start = int(match.group(1) or 0)
        end = int(match.group(2) or size - 1)
        end = min(end, size - 1)
        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        handle = open(path, "rb")
        handle.seek(start)
        self._range_length = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._range_length))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return handle

    def copyfile(self, source, outputfile):
        length = getattr(self, "_range_length", None)
        if length is None:
            super().copyfile(source, outputfile)
            return
        remaining = length
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        self._range_length = None

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep CI logs quiet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--directory", default="build/webmcp-demo")
    args = parser.parse_args()

    class BoundHandler(RangeFileHandler):
        def __init__(self, *pos, **kwargs):
            super().__init__(*pos, directory=args.directory, **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), BoundHandler)
    print(f"serving {args.directory} on http://127.0.0.1:{args.port} (Range capable)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

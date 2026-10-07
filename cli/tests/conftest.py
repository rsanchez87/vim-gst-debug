import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                     "body": body})
        status, payload = self.server.reply
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def completion(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.requests, srv.reply = [], (200, completion("{}"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()


SAMPLE = """\
0:00:00.100000000 10 0xaaa INFO  filesrc gstfilesrc.c:465:gst_file_src_start:<filesrc0> opening file /home/alice/clip.mp4
0:00:00.200000000 10 0xaaa DEBUG basesrc gstbasesrc.c:1:fn:<filesrc0> noise
0:00:00.300000000 10 0xaaa WARN  filesrc gstfilesrc.c:553:gst_file_src_start:<filesrc0> error: No such file "/home/alice/clip.mp4"
0:00:00.400000000 10 0xaaa WARN  structure gstfoo.c:1:retry: retry attempt 11
0:00:00.500000000 10 0xaaa WARN  structure gstfoo.c:1:retry: retry attempt 22
0:00:00.600000000 10 0xaaa ERROR GST_PIPELINE grammar.y:1:parse: failed to connect to 10.1.2.3:554 user:pw@host
not a log line
"""


@pytest.fixture
def logfile(tmp_path):
    p = tmp_path / "gst.log"
    p.write_text(SAMPLE)
    return str(p)

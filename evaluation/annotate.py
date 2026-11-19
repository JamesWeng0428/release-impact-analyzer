"""Local, one-review-at-a-time annotation UI with atomic CSV autosave.

Run: python -m evaluation.annotate
"""

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
import tempfile
import webbrowser

from evaluation.retrieval import ANNOTATION_FIELDS, SNAPSHOT_FILES, digest, load_queries


class AnnotationStore:
    def __init__(self, workspace: Path, assessor="james", *, demo=False):
        self.workspace = workspace.resolve()
        self.path = self.workspace / "judgments.csv"
        if not assessor.strip():
            raise ValueError("assessor must not be empty")
        self.assessor = assessor.strip()
        self.demo = demo
        self.provenance = "synthetic" if demo else "human"
        manifest = json.loads((self.workspace / "manifest.json").read_text())
        for name in SNAPSHOT_FILES:
            if digest(self.workspace / name) != manifest["hashes"][name]:
                raise ValueError(f"snapshot changed: {name}")
        self.dataset = manifest["hashes"]["pool.csv"]
        self.splits = {q["id"]: q["split"] for q in load_queries(self.workspace / "queries.jsonl")}
        with (self.workspace / "pool.csv").open(encoding="utf-8", newline="") as stream:
            self.pool = {(r["query_id"], r["review_id"]): r for r in csv.DictReader(stream)}
        self.read()

    def read(self):
        content = self.path.read_bytes()
        reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
        self.fields = reader.fieldnames
        if not self.fields or not set(ANNOTATION_FIELDS) <= set(self.fields):
            raise ValueError("judgments.csv is missing required annotation columns")
        rows = list(reader)
        seen = set()
        for row in rows:
            if None in row or any(not isinstance(row.get(field), str) for field in ANNOTATION_FIELDS):
                raise ValueError("malformed judgments.csv row; all annotation columns must be present")
            pair = row["query_id"], row["review_id"]
            if pair not in self.pool or pair in seen:
                raise ValueError("judgments contain unknown or duplicate pairs")
            seen.add(pair)
            if any(row[field] != self.pool[pair][field] for field in ANNOTATION_FIELDS[:6]):
                raise ValueError("judgment source text differs from the frozen pool")
            if row["relevance"].strip():
                if row["relevance"] not in ("0", "1", "2"):
                    raise ValueError("invalid existing relevance grade")
                if row["provenance"] != self.provenance or not row["assessor"].strip():
                    raise ValueError("use a blank or human-only sheet; AI judgments are not shown here")
        if seen != set(self.pool):
            raise ValueError("judgments.csv must contain the complete frozen pool")
        self.rows, self.revision = rows, hashlib.sha256(content).hexdigest()
        return content

    def state(self):
        self.read()
        # Only source text and the user's labels leave the server. Never rankings/AI labels.
        return {"revision": self.revision, "dataset": self.dataset,
                "assessor": self.assessor, "demo": self.demo,
                "rows": [{**{key: row[key] for key in ANNOTATION_FIELDS[:7]},
                          "split": self.splits[row["query_id"]]} for row in self.rows]}

    def save(self, payload):
        # Serialize cooperating server processes as well as stale browser tabs.
        with (self.workspace / ".annotation.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._save(payload)

    def _save(self, payload):
        original = self.read()
        if payload.get("revision") != self.revision:
            raise Conflict("进度已在另一个页面或文件中更新。请刷新后再选择，当前选择尚未保存。")
        grade = payload.get("relevance")
        if type(grade) is not int or grade not in (0, 1, 2):
            raise ValueError("relevance must be 0, 1 or 2")
        pair = payload.get("query_id"), payload.get("review_id")
        if pair not in self.pool:
            raise ValueError("unknown query-review pair")
        for row in self.rows:
            if (row["query_id"], row["review_id"]) == pair:
                row.update(relevance=str(grade), assessor=self.assessor, provenance=self.provenance)
                break
        # Keep the initial sheet for recovery; never overwrite an earlier backup.
        backup = self.workspace / "judgments.before-annotation.csv"
        if not backup.exists():
            with backup.open("xb") as stream:
                stream.write(original)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                             dir=self.workspace, prefix=".annotation-", delete=False) as stream:
                temporary = Path(stream.name)
                writer = csv.DictWriter(stream, fieldnames=self.fields)
                writer.writeheader()
                writer.writerows(self.rows)
                stream.flush()
                os.fsync(stream.fileno())
            if digest(self.path) != self.revision:
                raise Conflict("文件已更新，请刷新后重试。当前选择尚未保存。")
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return self.state()


class Conflict(ValueError):
    pass


def make_server(store, port=8765):
    token = secrets.token_hex(32)
    html = Path(__file__).with_name("annotation.html").read_text(encoding="utf-8").replace("__TOKEN__", token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, kind="application/json; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {"error": "Local access only"})
            try:
                if self.path == "/":
                    self.respond(200, html, "text/html; charset=utf-8")
                elif self.path == "/api/state":
                    self.respond(200, store.state())
                else:
                    self.respond(404, {"error": "Not found"})
            except (OSError, ValueError, KeyError) as error:
                self.respond(400, {"error": str(error)})

        def do_POST(self):
            origin = self.headers.get("Origin")
            if (not self.valid_host() or self.headers.get("X-Annotation-Token") != token or
                    (origin is not None and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"})):
                return self.respond(403, {"error": "Invalid local session"})
            if self.path != "/api/label":
                return self.respond(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("request must be an object")
                self.respond(200, store.save(payload))
            except Conflict as error:
                self.respond(409, {"error": str(error)})
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.respond(400, {"error": str(error)})

    return HTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("evaluation/workspace"))
    parser.add_argument("--assessor", default="james")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the page in your default browser")
    parser.add_argument("--demo", action="store_true", help="write synthetic provenance; use only a disposable demo workspace")
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        store = AnnotationStore(args.workspace, args.assessor, demo=args.demo)
        server = make_server(store, args.port)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Annotation page: {url}\nAutosave: {store.path}\nPress Ctrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

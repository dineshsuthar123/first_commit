"""Independent process: transaction commit precedes every successful HTTP response."""
import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

from engine.models import Operation


def connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS captures (
      effectId INTEGER PRIMARY KEY AUTOINCREMENT, operationId TEXT NOT NULL,
      orderId TEXT NOT NULL, amountMinor INTEGER NOT NULL CHECK(amountMinor > 0),
      currency TEXT NOT NULL, idempotencyKey TEXT UNIQUE)""")
    db.commit()
    return db


def charge(db, body):
    key = body.pop("idempotencyKey", None)
    op = Operation.model_validate(body)
    if key is not None and (not isinstance(key, str) or not 1 <= len(key) <= 200):
        raise ValueError("invalid idempotency key")
    with db:
        db.execute("BEGIN IMMEDIATE")
        if key is not None:
            previous = db.execute("SELECT * FROM captures WHERE idempotencyKey=?", (key,)).fetchone()
            if previous:
                if any(previous[k] != v for k, v in op.model_dump().items()):
                    return 409, {"error": "idempotency key reused with different request"}
                return 200, {**dict(previous), "deduplicated": True}
        row = db.execute("""INSERT INTO captures(operationId,orderId,amountMinor,currency,idempotencyKey)
            VALUES(?,?,?,?,?) RETURNING *""", (*op.model_dump().values(), key)).fetchone()
    return 201, {**dict(row), "deduplicated": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/ledger":
            self.reply(200, [dict(r) for r in self.server.db.execute("SELECT * FROM captures ORDER BY effectId")])
        elif self.path == "/health":
            self.reply(200, {"healthy": True})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/charge":
            return self.reply(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("invalid request size")
            status, result = charge(self.server.db, json.loads(self.rfile.read(size)))
            self.reply(status, result)
        except (ValueError, TypeError) as e:
            self.reply(400, {"error": str(e)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.db = connect(args.db)
    print(json.dumps({"type": "ready", "port": server.server_port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

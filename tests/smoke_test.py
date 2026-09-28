#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test for Muse File Bridge. Standard library only.

Spins up server/muse-file-api.py on a temp port with an isolated HOME, then
exercises every endpoint: auth, health, list, read (text/binary), write,
mkdir, traversal rejection, read-only mode, token rotation, audit log,
atomic writes, client --allow-http behavior, and rate limiting.

Run:  python tests/smoke_test.py
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.normpath(os.path.join(HERE, "..", "server", "muse-file-api.py"))
CLIENT = os.path.normpath(os.path.join(HERE, "..", "client", "pcfile.py"))
PORT = 18793

passed = failed = 0


def check(name: str, cond: bool):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


def req(url: str, token: str | None = None, body: dict | None = None):
    data = (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(url, method="POST" if body is not None else "GET",
                               data=data)
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode())
        except Exception:
            detail = {}
        return e.code, detail


def start_server(home: str, read_only: bool):
    cfg = {"port": PORT, "read_only": read_only,
           "roots": {"test": os.path.join(home, "data")}}
    os.makedirs(os.path.join(home, ".muse-bridge"), exist_ok=True)
    with open(os.path.join(home, ".muse-bridge", "config.json"), "w") as f:
        json.dump(cfg, f)
    env = dict(os.environ, HOME=home)
    proc = subprocess.Popen(
        [sys.executable, SERVER, "--log-file",
         os.path.join(home, ".muse-bridge", "server.log")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    token_file = os.path.join(home, ".muse-bridge", "token")
    for _ in range(100):
        if os.path.exists(token_file):
            break
        time.sleep(0.1)
    with open(token_file) as f:
        token = f.read().strip()
    base = f"http://127.0.0.1:{PORT}"
    for _ in range(100):
        try:
            s, _ = req(base + "/api/health", token)
            if s == 200:
                return proc, base, token
        except Exception:
            pass
        time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("server did not come up")


def main() -> int:
    home = tempfile.mkdtemp(prefix="bridge-smoke-")
    os.makedirs(os.path.join(home, "data"))
    proc, base, token = start_server(home, read_only=False)
    try:
        # --- auth ---
        s, _ = req(base + "/api/health", "wrong-token")
        check("bad token -> 401", s == 401)
        s, _ = req(base + "/api/health")
        check("missing token -> 401", s == 401)

        # --- health ---
        s, h = req(base + "/api/health", token)
        check("health ok", s == 200 and h["roots"] == ["test"]
              and h["read_only"] is False and h.get("version") == "0.3")

        # --- write/read text ---
        s, _ = req(base + "/api/write", token,
                   {"root": "test", "path": "a.txt",
                    "content": "hello", "encoding": "text"})
        check("write text", s == 200)
        s, r = req(base + "/api/read?root=test&path=a.txt", token)
        check("read text back",
              s == 200 and r["encoding"] == "text" and r["content"] == "hello")

        # --- write/read binary ---
        blob = bytes(range(256))
        s, _ = req(base + "/api/write", token,
                   {"root": "test", "path": "sub/b.bin",
                    "content": base64.b64encode(blob).decode(),
                    "encoding": "base64"})
        check("write binary (auto mkdir)", s == 200)
        s, r = req(base + "/api/read?root=test&path=sub/b.bin", token)
        check("read binary back",
              s == 200 and r["encoding"] == "base64"
              and base64.b64decode(r["content"]) == blob)

        # --- mkdir/list ---
        s, _ = req(base + "/api/mkdir", token,
                   {"root": "test", "path": "newdir"})
        s, l = req(base + "/api/list?root=test&path=", token)
        names = {e["name"] for e in l["entries"]}
        check("mkdir + list", s == 200 and "newdir" in names
              and "a.txt" in names)

        # --- traversal / bad paths ---
        s, _ = req(base + "/api/read?root=test&path=" +
                   urllib.parse.quote("../secret"), token)
        check("path traversal rejected", s == 400)
        s, _ = req(base + "/api/read?root=test&path=" +
                   urllib.parse.quote("/etc/hostname"), token)
        check("absolute path rejected", s == 400)
        s, _ = req(base + "/api/read?root=nope&path=x", token)
        check("unknown root rejected", s == 400)

        # --- no temp files left behind (atomic write) ---
        leftovers = []
        for dp, _, fns in os.walk(os.path.join(home, "data")):
            leftovers += [f for f in fns if f.startswith(".bridge-")]
        check("no temp files left", not leftovers)

        # --- client: http refused without --allow-http ---
        p = subprocess.run(
            [sys.executable, CLIENT, "--base-url", base, "--token", token,
             "health"], capture_output=True, text=True)
        check("client refuses plain http by default", p.returncode != 0)

        # --- client: sync works with --allow-http ---
        src = os.path.join(home, "src")
        os.makedirs(os.path.join(src, "sub"))
        with open(os.path.join(src, "x.txt"), "w") as f:
            f.write("sync-me")
        with open(os.path.join(src, "sub", "y.bin"), "wb") as f:
            f.write(b"\x00\x01\x02")
        p = subprocess.run(
            [sys.executable, CLIENT, "--allow-http", "--base-url", base,
             "--token", token, "sync", src, "test", "synced"],
            capture_output=True, text=True)
        ok = (p.returncode == 0
              and open(os.path.join(home, "data", "synced", "x.txt")).read()
              == "sync-me")
        check("client sync", ok)

        # --- token rotation (new token is NOT in the response, only in the file) ---
        s, r = req(base + "/api/rotate-token", token, {})
        check("rotate-token ok", s == 200 and r.get("ok") is True)
        check("rotate-token leaks no token", "token" not in r)
        with open(os.path.join(home, ".muse-bridge", "token")) as f:
            new_token = f.read().strip()
        check("new token differs", len(new_token) > 20 and new_token != token)
        s, _ = req(base + "/api/health", token)
        check("old token dead after rotation", s == 401)
        s, _ = req(base + "/api/health", new_token)
        check("new token works", s == 200)
        token = new_token

        # --- client rotate-token ---
        p = subprocess.run(
            [sys.executable, CLIENT, "--allow-http", "--base-url", base,
             "--token", token, "rotate-token"],
            capture_output=True, text=True)
        print(f"DEBUG client rc={p.returncode} stdout={p.stdout[-200:]!r} "
              f"stderr={p.stderr[-300:]!r}", flush=True)
        with open(os.path.join(home, ".muse-bridge", "token")) as f:
            token = f.read().strip()
        s, hb = req(base + "/api/health", token)
        print(f"DEBUG health s={s} body={str(hb)[:120]!r}", flush=True)
        check("client rotate-token", p.returncode == 0 and s == 200)

        # --- audit log ---
        entries = []
        with open(os.path.join(home, ".muse-bridge", "audit.log")) as f:
            for line in f:
                entries.append(json.loads(line))
        writes = [e for e in entries
                  if e["endpoint"] == "/api/write" and e["code"] == 200]
        denied = [e for e in entries if e["code"] == 401]
        check("audit log has write entries",
              writes and all(e["root"] == "test" and e["bytes"] for e in writes))
        check("audit log records 401s", len(denied) >= 2)

        # --- rate limit (1000/min) ---
        limited = 0
        for _ in range(1005):
            s, _ = req(base + "/api/health", token)
            if s == 429:
                limited += 1
        check("rate limit kicks in", limited > 0)
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    # --- read-only mode (fresh process => fresh rate-limit bucket) ---
    proc, base, token = start_server(home, read_only=True)
    try:
        s, h = req(base + "/api/health", token)
        check("read_only advertised in health",
              s == 200 and h["read_only"] is True)
        s, _ = req(base + "/api/write", token,
                   {"root": "test", "path": "no.txt",
                    "content": "x", "encoding": "text"})
        check("write refused in read-only mode", s == 403)
        s, _ = req(base + "/api/mkdir", token,
                   {"root": "test", "path": "nope"})
        check("mkdir refused in read-only mode", s == 403)
        s, _ = req(base + "/api/read?root=test&path=a.txt", token)
        check("read still works in read-only mode", s == 200)
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    log = os.path.join(home, ".muse-bridge", "server.log")
    check("--log-file written", os.path.getsize(log) > 0)
    shutil.rmtree(home, ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

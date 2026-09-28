#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone client for Muse File Bridge.

Talk to muse-file-api.py running on your Windows PC (exposed via Cloudflare Tunnel).

Auth: bearer token via --token or the MUSE_BRIDGE_TOKEN environment variable.
URL:  --base-url or the MUSE_BRIDGE_URL environment variable.

Examples:
    export MUSE_BRIDGE_TOKEN="paste-your-token-here"
    export MUSE_BRIDGE_URL="https://bridge.yourdomain.com"

    python pcfile.py health
    python pcfile.py list projects
    python pcfile.py list projects sub/dir
    python pcfile.py read projects notes/todo.txt
    python pcfile.py write projects notes/todo.txt ./todo.txt
    python pcfile.py mkdir projects new-folder
    python pcfile.py sync ./my-plugin plugins my-plugin

Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def get_token(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get("MUSE_BRIDGE_TOKEN", "").strip()
    if not token:
        raise SystemExit("missing token: pass --token or set MUSE_BRIDGE_TOKEN")
    return token


def get_base_url(args: argparse.Namespace) -> str:
    url = (args.base_url or os.environ.get("MUSE_BRIDGE_URL", "")).strip().rstrip("/")
    if not url:
        raise SystemExit("missing base url: pass --base-url or set MUSE_BRIDGE_URL")
    if not url.startswith("https://"):
        print("warning: base url is not https; the token will travel in cleartext",
              file=sys.stderr)
    return url


def call(base_url: str, token: str, method: str, path: str,
         params: dict | None = None, body: dict | None = None,
         timeout: int = 30) -> tuple[int, object]:
    url = base_url + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = (json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None else None)
    req = urllib.request.Request(url, method=method, data=data)
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        return e.code, {"http_error": e.code, "detail": detail}
    except Exception as e:  # noqa: BLE001 - network errors become a readable message
        return 0, {"error": f"cannot reach the server: {e}"}


def _remote_join(*parts: str) -> str:
    """Join remote path segments with '/', dropping empties."""
    return "/".join(p.strip("/") for p in parts if p and p.strip("/"))


def cmd_sync(base_url: str, token: str, local_dir: str, root: str,
             remote_dir: str) -> int:
    """Upload a whole local folder to the PC, preserving structure."""
    local_dir = os.path.abspath(local_dir)
    if not os.path.isdir(local_dir):
        print(f"error: not a directory: {local_dir}", file=sys.stderr)
        return 1
    n_files = n_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(local_dir):
        rel = os.path.relpath(dirpath, local_dir).replace(os.sep, "/")
        rel = "" if rel == "." else rel
        rdir = _remote_join(remote_dir, rel)
        status, data = call(base_url, token, "POST", "/api/mkdir",
                            body={"root": root, "path": rdir})
        if status != 200:
            print(f"error: mkdir failed for {rdir}: {data}", file=sys.stderr)
            return 1
        for name in filenames:
            with open(os.path.join(dirpath, name), "rb") as f:
                raw = f.read()
            rfile = _remote_join(remote_dir, rel, name)
            try:
                body = {"root": root, "path": rfile,
                        "content": raw.decode("utf-8"), "encoding": "text"}
            except UnicodeDecodeError:
                body = {"root": root, "path": rfile,
                        "content": base64.b64encode(raw).decode(),
                        "encoding": "base64"}
            status, data = call(base_url, token, "POST", "/api/write",
                                body=body)
            if status != 200:
                print(f"error: write failed for {rfile}: {data}",
                      file=sys.stderr)
                return 1
            n_files += 1
            n_bytes += len(raw)
            print(f"  ok {rfile} ({len(raw)} bytes)")
    print(f"synced {n_files} files, {n_bytes} bytes -> {root}:{remote_dir or '/'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Muse File Bridge client")
    ap.add_argument("--base-url", help="tunnel URL, e.g. https://bridge.yourdomain.com")
    ap.add_argument("--token", help="access token (or set MUSE_BRIDGE_TOKEN)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health", help="liveness check + exposed roots")
    p = sub.add_parser("list", help="list a directory")
    p.add_argument("root")
    p.add_argument("path", nargs="?", default="")
    p = sub.add_parser("read", help="read a file")
    p.add_argument("root")
    p.add_argument("path")
    p = sub.add_parser("write", help="write a local file to the PC")
    p.add_argument("root")
    p.add_argument("remote_path")
    p.add_argument("local_file")
    p = sub.add_parser("mkdir", help="create a directory")
    p.add_argument("root")
    p.add_argument("remote_path")
    p = sub.add_parser("sync", help="upload a whole local folder to the PC")
    p.add_argument("local_dir", help="local folder to upload")
    p.add_argument("root")
    p.add_argument("remote_dir", help="destination folder on the PC")

    args = ap.parse_args()
    try:
        base_url = get_base_url(args)
        token = get_token(args)

        if args.cmd == "health":
            status, data = call(base_url, token, "GET", "/api/health")
        elif args.cmd == "list":
            status, data = call(base_url, token, "GET", "/api/list",
                               {"root": args.root, "path": args.path})
        elif args.cmd == "read":
            status, data = call(base_url, token, "GET", "/api/read",
                               {"root": args.root, "path": args.path})
        elif args.cmd == "write":
            with open(args.local_file, "rb") as f:
                raw = f.read()
            try:
                body = {"root": args.root, "path": args.remote_path,
                        "content": raw.decode("utf-8"), "encoding": "text"}
            except UnicodeDecodeError:
                body = {"root": args.root, "path": args.remote_path,
                        "content": base64.b64encode(raw).decode(),
                        "encoding": "base64"}
            status, data = call(base_url, token, "POST", "/api/write", body=body)
        elif args.cmd == "mkdir":
            status, data = call(base_url, token, "POST", "/api/mkdir",
                               body={"root": args.root, "path": args.remote_path})
        elif args.cmd == "sync":
            return cmd_sync(base_url, token, args.local_dir,
                            args.root, args.remote_dir)
        else:
            ap.error("unknown command")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())

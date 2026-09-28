#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Muse File Bridge - Windows 本地文件 API 服务端
================================================
跑在你的 Windows 电脑上,给 Muse 提供受控的文件读写能力。

安全设计:
  - 只监听 127.0.0.1(本机),公网流量只能经由你自己开的 Cloudflare 隧道进来,
    且全程是 Cloudflare 的 TLS 加密。
  - 每个请求都要带 Authorization: Bearer <token>,token 首次运行时自动生成,
    存在你用户目录下的 .muse-bridge/token,只有你本机能看到。
    可随时调 POST /api/rotate-token 轮换(旧令牌立即失效)。
  - 只能操作 config.json 里 roots 白名单中的目录;路径穿越(../)会被直接拒绝。
    首次运行默认只开放一个空的 ~/Documents/MuseBridge,且为只读模式。
  - 每个请求限流(默认每 IP 每分钟 1000 次),超了返回 429。
    注意: 经 Cloudflare 隧道进来的请求在服务端看来都是 127.0.0.1,
    所以这是整条隧道共享的桶,不是按公网来源限的。
  - 所有请求记审计日志(.muse-bridge/audit.log): 时间、接口、目录、路径、结果码。
  - 写文件是原子操作(临时文件 + 替换),不会留下半截文件。

安装运行(只需一次):
  推荐: 下载本仓库后,在 PowerShell 里运行仓库根目录的 install.ps1,
  它会自动检查 Python、下载 cloudflared、生成令牌、建隧道,
  并把本服务和隧道都注册成开机(登录)自启动。详见 README。
  手动安装:
  1. 安装 Python 3.9+: https://www.python.org/downloads/ (安装时勾选 "Add python.exe to PATH")
  2. 把本脚本放到一个固定位置,例如 D:\\Tools\\muse-file-api.py
  3. 双击运行,或在 PowerShell 里运行: python D:\\Tools\\muse-file-api.py
     后台无窗口运行: pythonw D:\\Tools\\muse-file-api.py --log-file %USERPROFILE%\\.muse-bridge\\server.log
  4. 首次运行会打印一串访问令牌(只显示这一次)。等 Muse 发你安全卡片后,
     把这串令牌填进卡片里 —— 不要发在聊天记录里。
  5. 用记事本打开 %USERPROFILE%\\.muse-bridge\\config.json,
     把 roots 改成你想让 Muse 访问的文件夹,例如:
         {"port": 18790, "roots": {"projects": "D:\\\\Projects", "plugins": "D:\\\\MyPlugins"}}
     默认 read_only=true(只读,写/建目录会被拒绝);确认要让 Muse 写文件时再改成 false。
     改完后重启本脚本生效。

配合 Cloudflare 隧道(另开一个终端):
  下载 cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  命名隧道(稳定地址,推荐):
      cloudflared tunnel login
      cloudflared tunnel create muse-bridge
      cloudflared tunnel route dns muse-bridge muse-bridge.你的域名.com
      cloudflared tunnel run --url http://127.0.0.1:18790 muse-bridge
  把最后的公网地址告诉 Muse,Muse 会发你安全卡片并验证连通。

接口(均为 Muse 调用,全部需要鉴权):
  GET  /api/health?                  -> {"ok": true, "version": "0.3",
                                        "roots": [...], "read_only": bool}
  GET  /api/list?root=NAME&path=REL  -> 目录列表
  GET  /api/read?root=NAME&path=REL  -> 读文件(文本直接返回,二进制转 base64)
  POST /api/write  {root, path, content, encoding} -> 写文件(自动建父目录,原子写入)
  POST /api/mkdir  {root, path}      -> 建目录
  POST /api/rotate-token             -> 轮换令牌(旧令牌立即失效;新令牌只写本机
                                        token 文件,不在响应里返回,防聊天记录泄漏)

  只读模式(read_only=true)下 write/mkdir 返回 403;超限流返回 429。
  审计日志记在 %USERPROFILE%\.muse-bridge\audit.log。
  给 Muse 用的对接说明见仓库根目录 CONNECTOR-BRIEF.md。
"""

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

APP_DIR = os.path.join(os.path.expanduser("~"), ".muse-bridge")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
TOKEN_PATH = os.path.join(APP_DIR, "token")
AUDIT_PATH = os.path.join(APP_DIR, "audit.log")
MAX_READ_BYTES = 2 * 1024 * 1024    # 单次读取上限 2MB
MAX_WRITE_BYTES = 10 * 1024 * 1024  # 单次写入上限 10MB
VERSION = "0.3"  # 协议版本, /api/health 返回,改协议时递增
RATE_LIMIT = 1000  # 每个 IP 每 RATE_WINDOW 秒最多请求数
RATE_WINDOW = 60   # 秒
_rate = {}
_rate_lock = threading.Lock()


def check_rate(ip: str) -> bool:
    """简易滑窗限流,超了返回 False。"""
    now = time.monotonic()
    with _rate_lock:
        start, count = _rate.get(ip, (now, 0))
        if now - start >= RATE_WINDOW:
            start, count = now, 0
        count += 1
        _rate[ip] = (start, count)
        return count <= RATE_LIMIT


def windows_documents_dir():
    """Windows 上取真正的「文档」文件夹(和安装脚本的 GetFolderPath 对齐)。

    失败时返回 None,调用方回退到 ~/Documents。ctypes 仍是标准库。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD),
                        ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        # FOLDERID_Documents = FDD39AD0-238F-46AF-ADB4-6C85480369C7
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                   (ctypes.c_ubyte * 8)(0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        sh = ctypes.windll.shell32.SHGetKnownFolderPath
        sh.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                       wintypes.HANDLE, ctypes.POINTER(wintypes.LPWSTR)]
        sh.restype = wintypes.HRESULT
        out = wintypes.LPWSTR()
        if sh(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0 and out.value:
            docs = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return docs
    except Exception:
        pass
    return None


def load_config():
    """返回 (port, roots, read_only)。

    首次运行生成默认配置: 只开放一个空的 ~/Documents/MuseBridge 目录,
    且默认为只读模式,避免误把整个用户目录交出去。
    """
    os.makedirs(APP_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        docs = windows_documents_dir() or os.path.join(os.path.expanduser("~"),
                                                       "Documents")
        bridge_dir = os.path.join(docs, "MuseBridge")
        os.makedirs(bridge_dir, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"port": 18790, "read_only": True,
                       "roots": {"bridge": bridge_dir}},
                      f, ensure_ascii=False, indent=2)
        print(f"已生成配置文件: {CONFIG_PATH}")
        print("  默认只开放一个空的 MuseBridge 目录(只读模式)。")
        print("  用记事本按需修改 roots / read_only,改完重启本脚本生效。")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    roots = {}
    for name, p in cfg.get("roots", {}).items():
        p = os.path.expandvars(os.path.expanduser(p))
        rp = os.path.realpath(p)
        if not os.path.isdir(rp):
            print(f"警告: root '{name}' 路径不存在,已跳过: {p}")
            continue
        roots[name] = rp
    if not roots:
        print("错误: 没有可用的目录白名单,请先编辑 config.json 再运行。")
        sys.exit(1)
    return cfg.get("port", 18790), roots, bool(cfg.get("read_only", False))


def load_token():
    """返回 (token, 是否本次新生成)。"""
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return f.read().strip(), False
    tok = secrets.token_urlsafe(32)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(tok)
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return tok, True


class Handler(BaseHTTPRequestHandler):
    server_version = "MuseBridge/" + VERSION  # 和协议版本保持一致

    def log_message(self, fmt, *args):
        sys.stderr.write("[bridge] " + fmt % args + "\n")

    # ---- helpers ----
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self._audit(code)

    def _audit(self, code):
        """审计日志(JSON Lines): 时间、客户端、接口、鉴权、root、相对路径、结果码。"""
        info = getattr(self, "_audit_info", None) or {}
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "client": self.client_address[0],
            "method": self.command,
            "endpoint": info.get("endpoint"),
            "authed": bool(info.get("authed")),
            "root": info.get("root"),
            "path": info.get("rel"),
            "code": code,
        }
        if info.get("bytes") is not None:
            entry["bytes"] = info["bytes"]
        try:
            with open(AUDIT_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _authed(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:].strip(), self.server.token)

    def _resolve(self, root_name, rel):
        """把 (root, 相对路径) 解析为绝对路径;非法返回 (None, 错误信息)。"""
        roots = self.server.roots
        if root_name not in roots:
            return None, "unknown root"
        if os.path.isabs(rel):
            return None, "path must be relative"
        base = roots[root_name]
        # realpath 同时消解 .. 和符号链接,之后必须仍在 base 之内
        target = os.path.realpath(os.path.join(base, rel))
        if target != base and not target.startswith(base + os.sep):
            return None, "path escapes root"
        return target, None

    # ---- GET ----
    def do_GET(self):
        self._audit_info = {"endpoint": urlparse(self.path).path}
        if not check_rate(self.client_address[0]):
            return self._send(429, {"error": "rate limit exceeded"})
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        self._audit_info["authed"] = True
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/api/health":
            return self._send(200, {"ok": True, "version": VERSION,
                                   "roots": sorted(self.server.roots),
                                   "read_only": self.server.read_only})

        if u.path == "/api/list":
            root_name, rel = q.get("root", [""])[0], q.get("path", [""])[0]
            target, err = self._resolve(root_name, rel)
            if err:
                return self._send(400, {"error": err})
            self._audit_info.update(root=root_name, rel=rel)
            if not os.path.isdir(target):
                return self._send(404, {"error": "not a directory"})
            entries = []
            try:
                with os.scandir(target) as it:
                    for e in it:
                        try:
                            st = e.stat(follow_symlinks=False)
                            entries.append({
                                "name": e.name,
                                "type": "dir" if e.is_dir(follow_symlinks=False) else "file",
                                "size": st.st_size,
                                "mtime": st.st_mtime,
                            })
                        except OSError:
                            continue
            except OSError as exc:
                return self._send(500, {"error": str(exc)})
            entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
            return self._send(200, {"entries": entries})

        if u.path == "/api/read":
            root_name, rel = q.get("root", [""])[0], q.get("path", [""])[0]
            target, err = self._resolve(root_name, rel)
            if err:
                return self._send(400, {"error": err})
            self._audit_info.update(root=root_name, rel=rel)
            if not os.path.isfile(target):
                return self._send(404, {"error": "not a file"})
            size = os.path.getsize(target)
            if size > MAX_READ_BYTES:
                return self._send(413, {"error": f"file too large ({size} bytes)"})
            with open(target, "rb") as f:
                data = f.read()
            self._audit_info["bytes"] = len(data)
            try:
                return self._send(200, {"encoding": "text", "content": data.decode("utf-8")})
            except UnicodeDecodeError:
                return self._send(200, {"encoding": "base64",
                                        "content": base64.b64encode(data).decode()})

        return self._send(404, {"error": "not found"})

    # ---- POST ----
    def do_POST(self):
        self._audit_info = {"endpoint": urlparse(self.path).path}
        if not check_rate(self.client_address[0]):
            return self._send(429, {"error": "rate limit exceeded"})
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        self._audit_info["authed"] = True
        u = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_WRITE_BYTES + 4096:
            return self._send(413, {"error": "payload too large"})
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            return self._send(400, {"error": "invalid json"})

        if u.path == "/api/rotate-token":
            # 轮换令牌: 旧令牌立即失效。新令牌只写本机 token 文件,
            # 不在响应里返回 —— 令牌永远不经过聊天/日志明文传输。
            # 轮换后请从 %USERPROFILE%\.muse-bridge\token 把新令牌抄到安全卡片。
            new_tok = secrets.token_urlsafe(32)
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(new_tok)
            try:
                os.chmod(TOKEN_PATH, 0o600)
            except OSError:
                pass
            self.server.token = new_tok
            return self._send(200, {"ok": True})

        if u.path in ("/api/write", "/api/mkdir") and self.server.read_only:
            return self._send(403, {"error": "read-only mode "
                                             "(set read_only=false in config.json)"})

        if u.path == "/api/write":
            root_name, rel = body.get("root", ""), body.get("path", "")
            target, err = self._resolve(root_name, rel)
            if err:
                return self._send(400, {"error": err})
            self._audit_info.update(root=root_name, rel=rel)
            enc = body.get("encoding", "text")
            try:
                data = (body.get("content", "").encode("utf-8") if enc == "text"
                        else base64.b64decode(body.get("content", "")))
            except (ValueError, binascii.Error):
                return self._send(400, {"error": "bad content encoding"})
            if len(data) > MAX_WRITE_BYTES:
                return self._send(413, {"error": "content too large"})
            if os.path.isdir(target):
                return self._send(400, {"error": "target is a directory"})
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # 原子写入: 先写临时文件再替换,崩溃也不会留下半截文件
            fd, tmp = tempfile.mkstemp(dir=parent or None,
                                       prefix=".bridge-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            self._audit_info["bytes"] = len(data)
            return self._send(200, {"ok": True, "bytes": len(data)})

        if u.path == "/api/mkdir":
            root_name, rel = body.get("root", ""), body.get("path", "")
            target, err = self._resolve(root_name, rel)
            if err:
                return self._send(400, {"error": err})
            self._audit_info.update(root=root_name, rel=rel)
            os.makedirs(target, exist_ok=True)
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser(description="Muse File Bridge server")
    ap.add_argument("--log-file", default=None,
                    help="append stdout/stderr here (for background runs with pythonw)")
    args = ap.parse_args()
    if args.log_file:
        # 行缓冲,崩溃时也能留下最后几行日志
        log = open(args.log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = log
        sys.stderr = log
    port, roots, read_only = load_config()
    token, is_new = load_token()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token = token
    server.roots = roots
    server.read_only = read_only
    print("=" * 64)
    print("Muse File Bridge 已启动")
    print(f"  监听: http://127.0.0.1:{port} (仅本机)")
    print(f"  只读模式: {'开(写/建目录会被拒绝)' if read_only else '关'}")
    print("  开放目录:")
    for name, p in roots.items():
        print(f"    {name} -> {p}")
    print(f"  配置文件: {CONFIG_PATH}")
    if is_new:
        print("-" * 64)
        print("  首次运行,已生成访问令牌(只显示这一次,请妥善保管):")
        print(f"  {token}")
        print("  等 Muse 发你安全卡片后,把上面这串填进去。不要发在聊天里。")
    print("=" * 64)
    print("下一步: 另开一个终端运行 cloudflared,把本机端口暴露到公网。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()

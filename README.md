# Muse File Bridge

[中文版](README_zh-CN.md)

Let an AI assistant — or any HTTP client — securely read and write files on your Windows PC, exposed to the internet through a Cloudflare Tunnel.

No Git round-trips, no polling: files land on your disk in real time.

## Why not MCP?

MCP servers only serve MCP clients. If your assistant can't speak MCP (or simply can't reach your machine), this plain HTTPS API is the pragmatic alternative: anything that can do HTTPS with a bearer token can use it.

## Architecture

```
Windows PC                                              Internet               Client
┌──────────────────────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│ muse-file-api.py                 │     │  Cloudflare Tunnel   │     │ pcfile.py        │
│ listens on 127.0.0.1:18790 only  │◄────│  (TLS, your domain)  │◄────│ or curl /        │
│ whitelisted folders only         │     │                      │     │ any HTTP client  │
└──────────────────────────────────┘     └──────────────────────┘     └──────────────────┘
```

## Quickstart

### 1. Server (Windows)

Requires Python 3.9+.

```powershell
python server\muse-file-api.py
```

The first run prints an access token — save it, it's shown only once. Then edit `%USERPROFILE%\.muse-bridge\config.json` and set `roots` to the folders you want to expose:

```json
{
  "port": 18790,
  "roots": {
    "projects": "D:\\Projects",
    "plugins": "D:\\MyPlugins"
  }
}
```

Restart the script after editing.

### 2. Tunnel

Install `cloudflared` ([download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)), then:

```powershell
cloudflared tunnel login
cloudflared tunnel create muse-bridge
cloudflared tunnel route dns muse-bridge bridge.yourdomain.com
cloudflared tunnel run --url http://127.0.0.1:18790 muse-bridge
```

### 3. Client

```bash
export MUSE_BRIDGE_TOKEN="<token from step 1>"
export MUSE_BRIDGE_URL="https://bridge.yourdomain.com"

python client/pcfile.py health
python client/pcfile.py list projects
python client/pcfile.py read projects notes/todo.txt
python client/pcfile.py write projects notes/todo.txt ./todo.txt
python client/pcfile.py mkdir projects new-folder
```

## API reference

Every endpoint requires `Authorization: Bearer <token>`.

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/health` | Liveness check, lists exposed roots |
| GET | `/api/list?root=NAME&path=REL` | List directory entries |
| GET | `/api/read?root=NAME&path=REL` | Read a file (UTF-8 text, or base64 for binary) |
| POST | `/api/write` | JSON `{root, path, content, encoding}` — writes a file, creating parent dirs |
| POST | `/api/mkdir` | JSON `{root, path}` — creates a directory |

Limits: 2 MB per read, 10 MB per write. There is intentionally no delete endpoint.

## Security model

- The server binds to `127.0.0.1` only — unreachable from your LAN, let alone the internet, except through your own tunnel.
- Every request needs the bearer token (compared in constant time). The token lives in `%USERPROFILE%\.muse-bridge\token` on your PC and is never committed anywhere.
- Only directories listed in `roots` are visible. `..` traversal, absolute paths and symlink escapes are rejected (paths are resolved against their real path before checking).
- The tunnel provides TLS. A named tunnel gives you a stable address; a `trycloudflare.com` quick tunnel also works for a first try, but its address changes on every restart.

## Project layout

```
server/muse-file-api.py   Windows file API server (Python standard library only)
client/pcfile.py          Standalone client (Python standard library only)
```

## License

MIT — see [LICENSE](LICENSE).

# Muse File Bridge

[中文版](README_zh-CN.md)

Let **Muse** — your personal AI assistant — get real hands on your Windows PC: securely read and write files in whitelisted folders, exposed to the internet through a Cloudflare Tunnel.

No Git round-trips, no polling: files land on your disk in real time.

Made for Muse first: the installer, the docs, and [CONNECTOR-BRIEF.md](CONNECTOR-BRIEF.md) (a paste-ready setup brief for Muse) all assume Muse on the other end. The API itself is plain HTTPS + bearer token, so any HTTP client can use it too.

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

**Recommended — one-click install.** Download this repo (Code → Download ZIP), unzip, then in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

It checks Python 3.9+ (auto-installs it via winget if missing), installs `cloudflared` via winget, generates your token, creates the config, then offers two tunnel modes — a stable **named tunnel** or a throwaway **quick tunnel** for a first try — and finally registers **both** the API server and the tunnel to auto-start at logon — no console windows, logs go to `%USERPROFILE%\.muse-bridge\server.log`, failed tasks restart automatically. No admin rights needed.

Your token is saved to `%USERPROFILE%\.muse-bridge\token` — hand it to your assistant when asked, never paste it into chat. Re-running the script later updates the installed server.

**Manual setup**, if you prefer:

```powershell
python server\muse-file-api.py
```

The first run prints an access token — save it, it's shown only once. It also generates a default config that exposes **only an empty `Documents\MuseBridge` folder, in read-only mode** — safe to run as-is. To expose more, edit `%USERPROFILE%\.muse-bridge\config.json`:

```json
{
  "port": 18790,
  "read_only": false,
  "roots": {
    "projects": "D:\\Projects",
    "plugins": "D:\\MyPlugins"
  }
}
```

`read_only` defaults to `true` (writes are rejected with `403`); set it to `false` when you actually want the assistant to write files. Restart the script after editing.

### 2. Tunnel

Install `cloudflared` ([download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)), then:

```powershell
cloudflared tunnel login
cloudflared tunnel create muse-bridge
cloudflared tunnel route dns muse-bridge bridge.yourdomain.com
cloudflared tunnel run --url http://127.0.0.1:18790 muse-bridge
```

### Auto-start and updates

`install.ps1` registers two Scheduled Tasks — `MuseFileBridge API` and `MuseFileBridge Tunnel` — that start at logon and restart on failure. Manage them in Task Scheduler (`taskschd.msc`); to update the installed server, just re-download the repo and re-run `install.ps1`. Remove everything with:

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
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
python client/pcfile.py sync ./my-plugin plugins my-plugin   # upload a whole folder
```

On Windows PowerShell:

```powershell
$env:MUSE_BRIDGE_TOKEN="<token from step 1>"
$env:MUSE_BRIDGE_URL="https://bridge.yourdomain.com"

python client\pcfile.py health
python client\pcfile.py sync .\my-plugin plugins my-plugin
```

The client refuses plain `http://` URLs — pass `--allow-http` only for local testing against `127.0.0.1`.

## API reference

Every endpoint requires `Authorization: Bearer <token>`.

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/health` | Liveness check, lists exposed roots and protocol `version` |
| GET | `/api/list?root=NAME&path=REL` | List directory entries (capped at 5000, `truncated: true` when capped) |
| GET | `/api/read?root=NAME&path=REL` | Read a file (UTF-8 text, or base64 for binary) |
| POST | `/api/write` | JSON `{root, path, content, encoding}` — writes a file, creating parent dirs |
| POST | `/api/mkdir` | JSON `{root, path}` — creates a directory |
| POST | `/api/rotate-token` | Rotates the token — the old one stops working immediately. The new token is written only to the PC's token file and is **never** returned in the response (so it can't leak through chat) |

Limits: 2 MB per read, 10 MB per write, ~1000 requests/minute **shared by all tunnel traffic** (the server sees every tunnelled request as `127.0.0.1`; `429` when exceeded). In read-only mode (`read_only: true` in `config.json`), `write`/`mkdir` return `403`. There is intentionally no delete endpoint.

Every request is audit-logged on the PC (`%USERPROFILE%\.muse-bridge\audit.log`, JSON lines): timestamp, endpoint, root, relative path, status code.

Setting up Muse to use this API? Paste [CONNECTOR-BRIEF.md](CONNECTOR-BRIEF.md) into it — it's a ready-made setup brief.

## Security model

- The server binds to `127.0.0.1` only — unreachable from your LAN, let alone the internet, except through your own tunnel.
- Every request needs the bearer token (compared in constant time). The token lives in `%USERPROFILE%\.muse-bridge\token` on your PC and is never committed anywhere. Rotate it anytime with `POST /api/rotate-token` (no restart needed).
- Only directories listed in `roots` are visible. `..` traversal, absolute paths and symlink escapes are rejected (paths are resolved against their real path before checking). The default config exposes only an empty `Documents\MuseBridge` folder.
- New installs default to **read-only mode** — reads work, writes are rejected — until you set `read_only: false` in `config.json`. Recommended for the first connection to any assistant.
- Requests are rate-limited (~1000/min, shared by all tunnel traffic since the server sees it all as `127.0.0.1`) and audit-logged (`audit.log`): time, endpoint, root, path, status code — so you can always see what an assistant read or wrote.
- Writes are atomic (temp file + replace), so an interrupted transfer never leaves a half-written file.
- The tunnel provides TLS. A named tunnel gives you a stable address; the installer can also spin up a `trycloudflare.com` quick tunnel for a first try, but its address changes on every restart.

## Troubleshooting

- **`401 unauthorized`** — the token the client uses doesn't match `%USERPROFILE%\.muse-bridge\token` on the PC. Copy it again (don't paste it into chat — use your assistant's secure credential flow).
- **Client can't reach the server** — the PC is asleep/off, or a task isn't running. Check Task Scheduler → `MuseFileBridge API` / `MuseFileBridge Tunnel` → Last Run Result, and `%USERPROFILE%\.muse-bridge\server.log`.
- **Tunnel address changed** — you recreated the tunnel; update `MUSE_BRIDGE_URL` (or your assistant's stored URL) to the new hostname.
- **Port already in use** — change `port` in `%USERPROFILE%\.muse-bridge\config.json` and restart the `MuseFileBridge API` task (the tunnel command uses the same port).
- **Rotate the token** — `python client/pcfile.py rotate-token` (needs `MUSE_BRIDGE_TOKEN`/`MUSE_BRIDGE_URL` set). The old token dies immediately; copy the new one from `%USERPROFILE%\.muse-bridge\token` into the client side — it is never printed or returned over the API.
- **Writes rejected with `403`** — the server is in read-only mode. Set `read_only: false` in `%USERPROFILE%\.muse-bridge\config.json` and restart the `MuseFileBridge API` task.
- **What did the assistant touch?** — check `%USERPROFILE%\.muse-bridge\audit.log` (one JSON object per line).
- **`tunnel route dns` fails** — the domain's DNS zone must be on the Cloudflare account you logged into.

## Project layout

```
install.ps1               One-click installer: Python check (auto-install via winget),
                          cloudflared, token, config, named or trial tunnel,
                          auto-start tasks (Windows)
uninstall.ps1             Removes the auto-start tasks (Windows)
CONNECTOR-BRIEF.md        Paste-ready brief for wiring an AI assistant to this API
server/muse-file-api.py   Windows file API server (Python standard library only)
client/pcfile.py          Standalone client (Python standard library only)
tests/smoke_test.py       End-to-end smoke test, standard library only
CHANGELOG.md              Release notes
```

## License

MIT — see [LICENSE](LICENSE).

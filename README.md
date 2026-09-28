# Muse File Bridge

[中文版](README_zh-CN.md)

**One sentence: let Muse read and write files in specific folders on your Windows PC.**

You say "write me a Python script and put it in my Documents" — seconds later the file is on your disk. No more copy-pasting code out of chat.

```
Windows PC                               Internet                     Client              
┌──────────────────────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│ muse-file-api.py                 │     │  Cloudflare Tunnel   │     │ pcfile.py        │
│ listens on 127.0.0.1:18790 only  │◄────│  (TLS, your domain)  │◄────│ or curl /        │
│ whitelisted folders only         │     │                      │     │ any HTTP client  │
└──────────────────────────────────┘     └──────────────────────┘     └──────────────────┘
```

Made for Muse first: the installer, the docs, and [CONNECTOR-BRIEF.md](CONNECTOR-BRIEF.md) (a paste-ready setup brief for Muse) all assume Muse on the other end. The API itself is plain HTTPS + bearer token, so any HTTP client can use it too.

## Before you start

- A Windows 10/11 PC, connected to the internet
- About 10 minutes
- No admin rights needed, no Python knowledge needed

## Setup

### Step 1 — Download

Click **Code → Download ZIP** at the top right of this page, then unzip it anywhere (D:, C:, wherever — just remember where).

### Step 2 — Run the one-click installer

Open the unzipped folder (the one containing `install.ps1`), right-click an empty spot and choose "**Open in Terminal**" (Windows 11; on Windows 10, hold **Shift**, right-click, and choose "**Open PowerShell window here**"), then paste the following and press Enter:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> No terminal option in the right-click menu? Open PowerShell from the Start menu, then `cd` into the unzipped folder, e.g.:
> ```powershell
> cd D:\muse-file-bridge-main\muse-file-bridge-main
> ```

The script installs Python and cloudflared automatically (via winget). It will ask a few questions:

| Prompt | Recommendation |
| ------ | -------------- |
| Which directories may Muse access? (comma-separated, Enter for default) | **Press Enter.** The default is `Documents\MuseBridge`, which the script creates automatically |
| Allow Muse to write files? First time, read-only is recommended [y/N] | **Type `n` on first install.** Read-only is the safe default; writes can be enabled later |
| Tunnel mode: [1] named tunnel (stable, needs a domain) [2] quick tunnel (throwaway) | **Choose `2` for a first try.** Choose 1 later when you have your own domain on Cloudflare |

Choosing `2` (quick tunnel): at the end you will receive an address like `https://random-words.trycloudflare.com`. **It changes every time the PC restarts** — suitable for evaluation only.
Choosing `1` (named tunnel): a browser window will open for Cloudflare login and authorization; you will then enter a public hostname (e.g. `bridge.yourdomain.com`).

"**All done!**" indicates a successful install. The installer registers two auto-start tasks (`MuseFileBridge API` and `MuseFileBridge Tunnel`) — no console windows; they run silently in the background and restart on failure.

> **Note**: when the PC sleeps or you sign out, both tasks stop and Muse loses connection — this is the most common cause of sudden disconnects. For always-on use: Settings → System → Power, set sleep to "Never", and stay signed in (locking the screen is fine; signing out is not).

### Step 3 — Send the address to Muse

Send the public address (the full `https://...`) to Muse.

Muse will send you a **secure card**. Open this file in Notepad:

```
C:\Users\YourName\.muse-bridge\token
```

Copy the long token and paste it into the card. **The token is a password: enter it into the card only, never paste it into chat** (the card is encrypted end-to-end; chat is not).

### Step 4 — Verify

First confirm the server is alive locally (run in PowerShell):

```powershell
$t = (Get-Content "$env:USERPROFILE\.muse-bridge\token" -Raw).Trim()
Invoke-RestMethod -Headers @{Authorization = "Bearer $t"} http://127.0.0.1:18790/api/health
```

`ok : True` means the server is fine (replace `18790` if you changed the port). Then open your public address in a browser: a `401` means the tunnel is through (it's just missing the token); a timeout means the tunnel isn't up or the PC is asleep.

If both look good, tell Muse: "list the files in my bridge folder".

If you chose read-only in step 2 (typed `n`), write attempts will be rejected — this is expected behavior, indicating the read-only protection is active. To enable writes later: open `C:\Users\YourName\.muse-bridge\config.json` in Notepad, change `read_only` to `false`, save; then open Task Scheduler (search `taskschd.msc` in the Start menu), find `MuseFileBridge API`, right-click → Restart.

## What you can count on

- **Muse only sees folders you approve.** If you only opened `Documents\MuseBridge`, your Desktop, Downloads, and everything else on D: are invisible and inaccessible. `..` traversal, absolute paths, and symlink escapes are rejected. This is a hard server-side restriction.
- **The server only listens locally.** It binds to `127.0.0.1` — unreachable from your LAN or the internet except through your own tunnel.
- **The token is a password.** It exists only in the token file on your PC (file permissions restricted to your user) and is entered into the secure card. Rotate it anytime with `python client/pcfile.py rotate-token` — the old token is invalidated immediately; the new one is written only to your PC's file.
- **Read-only by default.** Start in read-only mode, confirm the assistant behaves as expected, then enable writes manually.
- **Everything is logged.** Every read and write is recorded in `C:\Users\YourName\.muse-bridge\audit.log` (one JSON object per line) for later review.
- **Writes are atomic.** An interrupted transfer never leaves a half-written file.
- **Muse cannot delete your files.** There is intentionally no delete endpoint.
- **Clean uninstall supported.** See "Uninstall" below.

## Uninstall

1. Open the folder you unzipped earlier (the one containing `uninstall.ps1`), right-click an empty spot and choose "**Open in Terminal**" (Windows 11; on Windows 10, hold **Shift**, right-click → "**Open PowerShell window here**"), then run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
   ```

2. The script first removes the two auto-start tasks (`MuseFileBridge API` and `MuseFileBridge Tunnel`); the service stops immediately.
3. It then asks whether to also delete `C:\Users\YourName\.muse-bridge` (configuration, whitelist, and token):
   - Type `y`: everything is deleted and unrecoverable. A future reinstall will start fresh.
   - Press Enter (`n`): configuration and token are kept. Re-running `install.ps1` later resumes without reconfiguration.

**What uninstall does not remove:**

- Your whitelisted folders themselves (e.g. files inside `Documents\MuseBridge`) — the uninstaller never touches your files.
- Python and cloudflared — both are general-purpose tools that other software may use.

**Optional**: if you created a named tunnel and want to remove it from Cloudflare as well:

```powershell
cloudflared tunnel delete muse-bridge
```

(Quick tunnels expire automatically when stopped — no action needed.)

> If the unzipped folder was already deleted, remove manually: search `taskschd.msc` in the Start menu to open Task Scheduler, find `MuseFileBridge API` and `MuseFileBridge Tunnel`, right-click → Delete; then manually delete the `C:\Users\YourName\.muse-bridge` folder if you want the configuration gone too.

## Advanced

### Why not MCP?

MCP servers only serve MCP clients. If your assistant can't speak MCP (or simply can't reach your machine), this plain HTTPS API is the pragmatic alternative: anything that can do HTTPS with a bearer token can use it.

### Manual setup (if you'd rather do it yourself)

```powershell
python server\muse-file-api.py
```

The first run generates an access token and prints it — save it, it's shown only once. It also writes a default config that exposes **only an empty `Documents\MuseBridge` folder, in read-only mode** — safe to run as-is. To expose more, edit `%USERPROFILE%\.muse-bridge\config.json`:

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

Restart the script after editing. Manual tunnel setup:

```powershell
cloudflared tunnel login
cloudflared tunnel create muse-bridge
cloudflared tunnel route dns muse-bridge bridge.yourdomain.com
cloudflared tunnel run --url http://127.0.0.1:18790 muse-bridge
```

### Client (for assistants / developers)

Windows PowerShell:

```powershell
$env:MUSE_BRIDGE_TOKEN="<the token from step 3>"
$env:MUSE_BRIDGE_URL="https://bridge.yourdomain.com"

python client\pcfile.py health
python client\pcfile.py list projects
python client\pcfile.py read projects notes/todo.txt
python client\pcfile.py write projects notes/todo.txt ./todo.txt
python client\pcfile.py mkdir projects new-folder
python client\pcfile.py sync .\my-plugin plugins my-plugin   # upload a whole folder
```

Linux / macOS:

```bash
export MUSE_BRIDGE_TOKEN="<the token from step 3>"
export MUSE_BRIDGE_URL="https://bridge.yourdomain.com"

python client/pcfile.py health
python client/pcfile.py list projects
python client/pcfile.py read projects notes/todo.txt
python client/pcfile.py write projects notes/todo.txt ./todo.txt
python client/pcfile.py mkdir projects new-folder
python client/pcfile.py sync ./my-plugin plugins my-plugin   # upload a whole folder
```

The client refuses plain `http://` URLs — pass `--allow-http` only for local testing against `127.0.0.1`.

### API reference

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

Setting up Muse to use this API? Paste [CONNECTOR-BRIEF.md](CONNECTOR-BRIEF.md) into it — it's a ready-made setup brief.

### Troubleshooting

| Symptom | What to do |
| ------- | ---------- |
| Installer throws ParserErrors / garbled Chinese | The ZIP is outdated. Download the latest release (script encoding issue fixed) |
| `401 unauthorized` | The client's token doesn't match `%USERPROFILE%\.muse-bridge\token` on the PC. Copy it again (never paste into chat — use the assistant's secure card flow) |
| Client can't reach the server | First confirm the PC isn't asleep and the user is still signed in (most common cause). Then check Task Scheduler → `MuseFileBridge API` / `MuseFileBridge Tunnel` → Last Run Result, and `%USERPROFILE%\.muse-bridge\server.log` |
| Tunnel address changed | You're on a quick tunnel; its address changes on restart. Send the new address to your assistant. For a stable address, re-run the installer and pick a named tunnel |
| Port already in use | Change `port` in `%USERPROFILE%\.muse-bridge\config.json` and restart the `MuseFileBridge API` task (the tunnel command uses the same port) |
| Rotate the token | `python client/pcfile.py rotate-token` (needs token/URL set). The old token dies immediately; copy the new one from `%USERPROFILE%\.muse-bridge\token` — it is never printed or returned over the API |
| Writes rejected with `403` | The server is in read-only mode. Set `read_only: false` in `%USERPROFILE%\.muse-bridge\config.json` and restart the `MuseFileBridge API` task |
| What did the assistant touch? | Check `%USERPROFILE%\.muse-bridge\audit.log` (one JSON object per line) |
| `tunnel route dns` fails | The domain's DNS zone must be on the Cloudflare account you logged into |

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

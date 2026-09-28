# CONNECTOR-BRIEF.md

> 把下面英文部分整个粘贴给 Muse（建 Custom Connector 时用）。中文说明只给人看，不用粘贴。
>
> Paste the English section below into Muse when creating a Custom Connector for this project.

---

# Muse File Bridge — Connector Brief

## What this is

Muse File Bridge exposes a Windows PC's whitelisted folders over HTTPS through a Cloudflare Tunnel, so an AI assistant can list, read, and write real files on that PC. The server (`server/muse-file-api.py`) listens on `127.0.0.1` only; the tunnel provides TLS and the public address.

## Connection

- **Base URL**: `https://<the user's tunnel hostname>` (e.g. `https://bridge.example.com`). The user provides this.
- **Auth**: `Authorization: Bearer <token>` header on every request. The token lives in `%USERPROFILE%\.muse-bridge\token` on the user's PC.
- **Credential handling**: never ask the user to paste the token into chat. Collect it through the platform's secure credential flow and store it as a bearer credential for this connector's host only.

## API reference

All endpoints require the bearer token. `root` is a whitelisted folder name (from `/api/health`), `path` is always relative — absolute paths and `..` traversal are rejected with `400`.

| Method | Path | Request | Response |
| ------ | ---- | ------- | -------- |
| GET | `/api/health` | — | `{"ok": true, "version": "0.3", "roots": ["projects", ...], "read_only": false}` |
| GET | `/api/list?root=NAME&path=REL` | — | `{"entries": [{"name", "type": "file\|dir", "size", "mtime"}], "truncated": false}` — truncated=true means the listing was capped at 5000 entries |
| GET | `/api/read?root=NAME&path=REL` | — | `{"encoding": "text", "content": "..."}` or `{"encoding": "base64", "content": "..."}` |
| POST | `/api/write` | `{"root", "path", "content", "encoding": "text\|base64"}` | `{"ok": true, "bytes": N}` — creates parent dirs, atomic replace |
| POST | `/api/mkdir` | `{"root", "path"}` | `{"ok": true}` |
| POST | `/api/rotate-token` | — | `{"ok": true}` — old token dies immediately; the new token is written **only** to the server's local token file and is **never** returned in the response |

Error codes: `400` bad request · `401` bad token · `403` read-only mode (`write`/`mkdir` refused) · `404` not found · `413` too large · `429` rate limited.

## Token handling (hard rules)

- **Never display, repeat, or paste any token into chat**, and never write one into a skill, doc, or log. Tokens travel only through the platform's secure credential flow.
- This applies doubly to rotation: `/api/rotate-token` deliberately does **not** return the new token. After rotating, ask the user to copy it from `%USERPROFILE%\.muse-bridge\token` on their PC into the credential store themselves.

## Limits & behavior rules

- Single read ≤ 2 MB, single write ≤ 10 MB. There is intentionally no delete endpoint.
- Rate limit: ~1000 requests/minute, **shared by all tunnel traffic** — the server sees every tunnelled request as `127.0.0.1`, so this is not per-public-IP limiting. Fine for one user; do not assume it stops a determined scanner.
- `read_only` may be `true` on first connection: reads work, `write`/`mkdir` return `403`. If the user wants writes, tell them to set `read_only=false` in `%USERPROFILE%\.muse-bridge\config.json` and restart the `MuseFileBridge API` scheduled task — do not work around it.
- Every request is audit-logged on the PC (`%USERPROFILE%\.muse-bridge\audit.log`): timestamp, endpoint, root, path, status code. If the user asks "what did you change?", this log is the source of truth.
- Reads: prefer `list` before `read` to avoid guessing paths. Binary files come back base64-encoded — decode before use, encode before `write`.
- Writes: prefer the `sync`-style flow for whole folders (mkdir + write per file). Writes are atomic (temp file + replace), so a killed transfer never leaves a half-written file.
- Token rotation: call `/api/rotate-token` when the token may have leaked, then have the user copy the new token from `%USERPROFILE%\.muse-bridge\token` into the credential store. You lose access until they do — that is intentional.

## First-connection checklist

1. Ask the user for the tunnel's public HTTPS hostname.
2. Collect the bearer token via the secure credential flow (never in chat).
3. Call `GET /api/health` to verify connectivity and list available roots.
4. Note `read_only`: if `true`, say so and offer read-only help until the user enables writes.

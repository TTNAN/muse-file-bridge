# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.1] - 2026-09-28

### Fixed

- `install.ps1` / `uninstall.ps1`: added UTF-8 BOM and fixed two PowerShell
  5.1 syntax errors (`if` used as an expression). The installer previously
  failed with `ParserError` on Chinese Windows running PowerShell 5.1.
- `install.ps1`: folder ACL setup now passes the user's SID to `icacls`
  instead of parsing its output — Windows usernames containing spaces
  (e.g. `Haonan Tong`) no longer break the install.

### Changed

- READMEs restructured: one Mermaid diagram up top (replaces the ASCII
  diagram, which misaligned wherever Chinese characters were rendered),
  an `English | 简体中文` language switcher, unbroken 4-step install with a
  prompt table, a single consolidated safety section ("What you can count
  on"), local health-check command, sleep/sign-out note (being unreachable
  during sleep is normal; no need to disable sleep), Windows 11 Terminal
  instructions, PowerShell-first client examples, FAQ as a table.
  "Why not MCP" moved to Advanced. English + Chinese.

## [1.0.0] - 2026-09-28

First public release: give Muse real hands on your Windows PC —
read and write whitelisted folders through a Cloudflare Tunnel.

### Added

- `server/muse-file-api.py`: stdlib-only local file API
  (`health` / `list` / `read` / `write` / `mkdir` / `rotate-token`).
- `install.ps1`: one-click Windows installer. Installs Python 3.12 and
  cloudflared via winget, finds a real Python (via `py.exe -3`, skips the
  WindowsApps store stub), generates the Bearer token, walks through the
  directory whitelist, offers trial or named tunnel mode, waits up to 30 s
  for the API to become healthy, and registers logon scheduled tasks with
  restart-on-failure. Writes `config.json` without a UTF-8 BOM and reads
  it back with `utf-8-sig` on the server, so PowerShell 5.1 BOM files load.
- `uninstall.ps1`: removes scheduled tasks, scripts and local data.
- `client/pcfile.py`: stdlib-only client
  (`health` / `list` / `read` / `write` / `mkdir` / `sync` / `rotate-token`);
  refuses plain HTTP unless `--allow-http` is passed.
- `tests/smoke_test.py`: 33 end-to-end checks, run by GitHub Actions on
  every push.
- `CONNECTOR-BRIEF.md`: paste-ready setup brief for connecting Muse.
- Bilingual docs: `README.md` (English) + `README_zh-CN.md`.
- `/api/list` caps results at 5000 entries and reports `truncated: true`
  when capped (entries are deterministically sorted: directories first,
  then by name).
- Audit log rotation: `audit.log` rotates at 10 MB, keeping 3 old files
  (`audit.log.1` … `audit.log.3`).
- Server response header identifies as `MuseBridge/<protocol-version>`
  (currently `MuseBridge/0.3`).

### Security

- Bearer token auth; the token lives only in a file on the PC and is
  never pasted into chat.
- Token file ACL restricted to the current user on every install.
- Directory whitelist; absolute paths, `..` and symlink escapes are
  rejected.
- Read-only by default; writes require explicit opt-in during install.
- Single-read 2 MB cap, single-write 10 MB cap, no delete endpoint.
- Atomic writes (temporary file + `os.replace`).
- Token rotation: the new token is written only to the local token file,
  never returned by the API or printed to the terminal.
- Per-IP rate limiting (~1000 requests/minute, shared across the tunnel).

### Fixed

- Generated tokens never start with `-`: previously about 1 in 64 tokens
  broke the client's `--token <value>` form (argparse mistook the token
  for an option flag). Tokens issued before this fix that start with `-`
  still work via `--token=<value>` or the `MUSE_BRIDGE_TOKEN` env var.

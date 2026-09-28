# Muse File Bridge

[English](README.md)

让 AI 助手（或任何 HTTP 客户端）通过 Cloudflare 隧道，安全地读写你 Windows 电脑上的文件。

不用经过 Git 中转、不用轮询：文件实时直写到你的硬盘上。

## 为什么不用 MCP？

MCP server 只能被 MCP client 调用。如果你的助手不会说 MCP（或者根本连不上你的电脑），这个普通的 HTTPS API 就是更务实的选择：任何能发 HTTPS + 带 bearer token 的客户端都能用。

## 架构

```
Windows 电脑                                        公网                 客户端
┌──────────────────────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│ muse-file-api.py                 │     │  Cloudflare Tunnel   │     │ pcfile.py        │
│ 只监听 127.0.0.1:18790           │◄────│  (TLS, 你的域名)     │◄────│ 或 curl /        │
│ 仅开放白名单目录                 │     │                      │     │ 任何 HTTP 客户端 │
└──────────────────────────────────┘     └──────────────────────┘     └──────────────────┘
```

## 快速开始

### 1. 服务端（Windows）

**推荐——一键安装。** 下载本仓库（Code → Download ZIP），解压后在 PowerShell 里运行：

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

它会自动检查 Python 3.9+（缺失时用 winget 自动装）、用 winget 装 `cloudflared`、生成令牌、创建配置，然后让你二选一：稳定的**命名隧道**，或先体验一把的**临时隧道**，最后把**服务端和隧道都注册成登录自启动**——无黑窗口、日志写到 `%USERPROFILE%\.muse-bridge\server.log`、挂了自动重启。不需要管理员权限。

令牌保存在 `%USERPROFILE%\.muse-bridge\token`——等助手问你要时再给，绝不要贴进聊天记录。以后想更新已安装的服务端，重下仓库再跑一遍 `install.ps1` 就行。

**手动安装**（如果你更喜欢自己动手）：

```powershell
python server\muse-file-api.py
```

首次运行会打印一串访问令牌——记下来，只显示这一次。同时会生成默认配置：**只开放一个空的 `文档\MuseBridge` 目录，而且是只读模式**——直接跑也安全。想开放更多，用记事本打开 `%USERPROFILE%\.muse-bridge\config.json`：

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

`read_only` 默认 `true`（写操作会被拒绝并返回 `403`）；确认要让助手写文件时再改成 `false`。改完重启脚本生效。

### 2. 隧道

安装 `cloudflared`（[下载地址](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)），然后：

```powershell
cloudflared tunnel login
cloudflared tunnel create muse-bridge
cloudflared tunnel route dns muse-bridge bridge.你的域名.com
cloudflared tunnel run --url http://127.0.0.1:18790 muse-bridge
```

### 开机自启动和更新

`install.ps1` 会注册两个计划任务——`MuseFileBridge API` 和 `MuseFileBridge Tunnel`，用户登录即启动、挂了自动重启。在任务计划程序（`taskschd.msc`）里管理；更新服务端时重下仓库再跑一遍 `install.ps1` 即可。一键卸载：

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

### 3. 客户端

```bash
export MUSE_BRIDGE_TOKEN="<第 1 步记下的令牌>"
export MUSE_BRIDGE_URL="https://bridge.你的域名.com"

python client/pcfile.py health
python client/pcfile.py list projects
python client/pcfile.py read projects notes/todo.txt
python client/pcfile.py write projects notes/todo.txt ./todo.txt
python client/pcfile.py mkdir projects new-folder
python client/pcfile.py sync ./my-plugin plugins my-plugin   # 上传整个文件夹
```

Windows PowerShell 里这样设环境变量：

```powershell
$env:MUSE_BRIDGE_TOKEN="<第 1 步记下的令牌>"
$env:MUSE_BRIDGE_URL="https://bridge.你的域名.com"

python client\pcfile.py health
python client\pcfile.py sync .\my-plugin plugins my-plugin
```

客户端拒绝明文 `http://` 地址——只有本地对着 `127.0.0.1` 测试时才加 `--allow-http`。

## API 说明

所有接口都需要在请求头带 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/api/health` | 存活检查，返回开放的目录白名单 |
| GET | `/api/list?root=NAME&path=REL` | 列目录 |
| GET | `/api/read?root=NAME&path=REL` | 读文件（UTF-8 文本直接返回，二进制转 base64） |
| POST | `/api/write` | JSON `{root, path, content, encoding}` —— 写文件，自动创建父目录 |
| POST | `/api/mkdir` | JSON `{root, path}` —— 建目录 |
| POST | `/api/rotate-token` | 轮换令牌——旧令牌立即失效。新令牌只写进电脑上的 token 文件，**不会在响应里返回**（防止经聊天记录泄漏） |

限制：单次读取 2 MB，单次写入 10 MB，每分钟约 1000 次请求（**整条隧道共享**——服务端看到的隧道请求全是 `127.0.0.1`，超了返回 `429`）。只读模式（`config.json` 里 `read_only: true`）下 `write`/`mkdir` 返回 `403`。特意没有提供删除接口。

所有请求都会记审计日志（电脑上 `%USERPROFILE%\.muse-bridge\audit.log`，每行一个 JSON）：时间、接口、目录、相对路径、结果码。

想让某个 AI 助手对接这个 API？把 [CONNECTOR-BRIEF.md](CONNECTOR-BRIEF.md) 整个粘贴给它。

## 安全模型

- 服务端只绑定 `127.0.0.1`——除了经由你自己的隧道，局域网和公网都连不进来。
- 每个请求都要带 bearer token（常量时间比较）。令牌只存在你电脑 `%USERPROFILE%\.muse-bridge\token` 里，绝不会被提交到仓库。随时可以调 `POST /api/rotate-token` 轮换，不用重启。
- 只能访问 `roots` 白名单里的目录。`..` 穿越、绝对路径、符号链接逃逸都会被拦截（先解析成真实路径再校验）。默认配置只开放一个空的 `文档\MuseBridge`。
- 新装默认是**只读模式**——能读不能写——确认要让助手写文件时再把 `config.json` 里的 `read_only` 改成 `false`。第一次对接任何助手都建议先只读。
- 请求限流（每分钟约 1000 次，整条隧道共享——服务端看到的隧道请求全是 `127.0.0.1`）+ 审计日志（`audit.log`：时间、接口、目录、路径、结果码）——助手读了写了什么，随时可查。
- 写文件是原子操作（临时文件 + 替换），传一半断掉也不会留下半截文件。
- 隧道提供 TLS。命名隧道地址稳定；安装脚本也能起一个 `trycloudflare.com` 临时隧道先体验，但每次重启地址都会变。

## 常见问题

- **报 `401 unauthorized`**——客户端用的令牌和电脑上 `%USERPROFILE%\.muse-bridge\token` 对不上。重新复制一次（别贴进聊天，用助手的安全卡片流程）。
- **客户端连不上服务端**——电脑休眠/关机了，或者某个计划任务没跑起来。去任务计划程序看 `MuseFileBridge API` / `MuseFileBridge Tunnel` 的"上次运行结果"，以及 `%USERPROFILE%\.muse-bridge\server.log` 日志。
- **隧道地址变了**——你重建过隧道；把 `MUSE_BRIDGE_URL`（或助手存的地址）更新成新域名。
- **端口被占用**——改 `%USERPROFILE%\.muse-bridge\config.json` 里的 `port`，重启 `MuseFileBridge API` 任务（隧道命令里是同一个端口）。
- **换令牌**——`python client/pcfile.py rotate-token`（需先设好 `MUSE_BRIDGE_TOKEN`/`MUSE_BRIDGE_URL`）。旧令牌立即失效；新令牌只写在电脑 `%USERPROFILE%\.muse-bridge\token` 里，API 不返回、终端不打印，自己去文件里抄，然后更新客户端那边。
- **写操作被拒绝（`403`）**——服务端在只读模式。把 `%USERPROFILE%\.muse-bridge\config.json` 里的 `read_only` 改成 `false`，重启 `MuseFileBridge API` 任务。
- **助手到底动了哪些文件？**——看 `%USERPROFILE%\.muse-bridge\audit.log`，每行一个 JSON。
- **`tunnel route dns` 失败**——该域名的 DNS zone 必须在你登录的那个 Cloudflare 账号下。

## 项目结构

```
install.ps1               一键安装:检查 Python(缺失自动装)、装 cloudflared、生成令牌、
                          建配置、命名或临时隧道、注册自启动任务 (Windows)
uninstall.ps1             删除自启动任务 (Windows)
CONNECTOR-BRIEF.md        给 AI 助手看的对接说明(可直接粘贴)
server/muse-file-api.py   Windows 文件 API 服务端（仅用 Python 标准库）
client/pcfile.py          独立客户端（仅用 Python 标准库）
tests/smoke_test.py       端到端冒烟测试（仅用 Python 标准库）
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。

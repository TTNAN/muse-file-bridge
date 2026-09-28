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

它会自动检查 Python 3.9+、用 winget 装 `cloudflared`、生成令牌、创建配置、引导你建隧道，然后把**服务端和隧道都注册成登录自启动**——无黑窗口、日志写到 `%USERPROFILE%\.muse-bridge\server.log`、挂了自动重启。不需要管理员权限。

令牌保存在 `%USERPROFILE%\.muse-bridge\token`——等助手问你要时再给，绝不要贴进聊天记录。

**手动安装**（如果你更喜欢自己动手）：

```powershell
python server\muse-file-api.py
```

首次运行会打印一串访问令牌——记下来，只显示这一次。然后用记事本打开 `%USERPROFILE%\.muse-bridge\config.json`，把 `roots` 改成你想开放的文件夹：

```json
{
  "port": 18790,
  "roots": {
    "projects": "D:\\Projects",
    "plugins": "D:\\MyPlugins"
  }
}
```

改完重启脚本生效。

### 2. 隧道

安装 `cloudflared`（[下载地址](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)），然后：

```powershell
cloudflared tunnel login
cloudflared tunnel create muse-bridge
cloudflared tunnel route dns muse-bridge bridge.你的域名.com
cloudflared tunnel run --url http://127.0.0.1:18790 muse-bridge
```

### 开机自启动

`install.ps1` 会注册两个计划任务——`MuseBridge API` 和 `MuseBridge Tunnel`，用户登录即启动、挂了自动重启。在任务计划程序（`taskschd.msc`）里管理，或一键卸载：

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

## API 说明

所有接口都需要在请求头带 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/api/health` | 存活检查，返回开放的目录白名单 |
| GET | `/api/list?root=NAME&path=REL` | 列目录 |
| GET | `/api/read?root=NAME&path=REL` | 读文件（UTF-8 文本直接返回，二进制转 base64） |
| POST | `/api/write` | JSON `{root, path, content, encoding}` —— 写文件，自动创建父目录 |
| POST | `/api/mkdir` | JSON `{root, path}` —— 建目录 |

限制：单次读取 2 MB，单次写入 10 MB。特意没有提供删除接口。

## 安全模型

- 服务端只绑定 `127.0.0.1`——除了经由你自己的隧道，局域网和公网都连不进来。
- 每个请求都要带 bearer token（常量时间比较）。令牌只存在你电脑 `%USERPROFILE%\.muse-bridge\token` 里，绝不会被提交到仓库。
- 只能访问 `roots` 白名单里的目录。`..` 穿越、绝对路径、符号链接逃逸都会被拦截（先解析成真实路径再校验）。
- 隧道提供 TLS。命名隧道地址稳定；`trycloudflare.com` 的临时隧道也能先体验，但每次重启地址都会变。

## 常见问题

- **报 `401 unauthorized`**——客户端用的令牌和电脑上 `%USERPROFILE%\.muse-bridge\token` 对不上。重新复制一次（别贴进聊天，用助手的安全卡片流程）。
- **客户端连不上服务端**——电脑休眠/关机了，或者某个计划任务没跑起来。去任务计划程序看 `MuseBridge API` / `MuseBridge Tunnel` 的"上次运行结果"，以及 `%USERPROFILE%\.muse-bridge\server.log` 日志。
- **隧道地址变了**——你重建过隧道；把 `MUSE_BRIDGE_URL`（或助手存的地址）更新成新域名。
- **端口被占用**——改 `%USERPROFILE%\.muse-bridge\config.json` 里的 `port`，重启 `MuseBridge API` 任务（隧道命令里是同一个端口）。
- **换令牌**——停掉 `MuseBridge API` 任务，删掉 `%USERPROFILE%\.muse-bridge\token`，再启动任务，会生成新令牌（无窗口运行时直接打开 token 文件看），然后更新客户端那边。
- **`tunnel route dns` 失败**——该域名的 DNS zone 必须在你登录的那个 Cloudflare 账号下。

## 项目结构

```
install.ps1               一键安装:检查 Python、装 cloudflared、生成令牌、
                          建配置、引导建隧道、注册自启动任务 (Windows)
uninstall.ps1             删除自启动任务 (Windows)
server/muse-file-api.py   Windows 文件 API 服务端（仅用 Python 标准库）
client/pcfile.py          独立客户端（仅用 Python 标准库）
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。

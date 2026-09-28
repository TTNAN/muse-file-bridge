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

需要 Python 3.9+。

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

### 3. 客户端

```bash
export MUSE_BRIDGE_TOKEN="<第 1 步记下的令牌>"
export MUSE_BRIDGE_URL="https://bridge.你的域名.com"

python client/pcfile.py health
python client/pcfile.py list projects
python client/pcfile.py read projects notes/todo.txt
python client/pcfile.py write projects notes/todo.txt ./todo.txt
python client/pcfile.py mkdir projects new-folder
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

## 项目结构

```
server/muse-file-api.py   Windows 文件 API 服务端（仅用 Python 标准库）
client/pcfile.py          独立客户端（仅用 Python 标准库）
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。

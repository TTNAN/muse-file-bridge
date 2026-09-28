# Muse File Bridge

[English](README.md)

**一句话：让 Muse 能直接读写你 Windows 电脑上指定文件夹里的文件。**

你说"帮我写个 Python 脚本放 Documents 里"，几秒钟后文件就出现在你电脑上了——不用再从聊天记录里复制粘贴代码。

**原理（30 秒看懂）：**

1. 你电脑上跑一个小服务，它只认你批准的文件夹，别的一概不碰。
2. Cloudflare 隧道给这个服务一个加密的公网地址（跟 https 网站一样，传输全程加密）。
3. Muse 拿着令牌（相当于密码，只有你有）经隧道来读写文件。

为 Muse 而造：安装脚本、文档、[CONNECTOR-BRIEF.md](CONNECTOR-BRIEF.md)（给 Muse 的粘贴即用对接说明）都是按 Muse 在对面来写的。API 本身是普通 HTTPS + 令牌，任何 HTTP 客户端也都能用。

## 开始之前，你需要

- 一台 Windows 10/11 电脑，连着网
- 10 分钟时间
- 不需要管理员权限，不需要懂 Python

## 安装：跟着做就行

### 第 1 步：下载代码

点本页面右上角 **Code → Download ZIP**，下载后解压（放 D 盘、C 盘都行，记住位置）。

### 第 2 步：运行一键安装

打开解压出来的文件夹（能看到 `install.ps1` 的那一层），在空白处按住 **Shift + 右键**，选择"**在此处打开 PowerShell 窗口**"，粘贴下面这行，回车：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> 如果右键菜单里没有"在此处打开 PowerShell 窗口"：点开始菜单搜 `powershell` 打开它，再用 `cd` 进到解压的文件夹，例如：
> ```powershell
> cd D:\muse-file-bridge-main\muse-file-bridge-main
> ```

安装脚本会自动装好 Python 和 cloudflared（走 winget，不用你操心）。中间会问你几个问题，照下面选就行：

| 它问你 | 你怎么选 |
| ------ | -------- |
| 允许 Muse 访问哪些目录？逗号分隔多个，直接回车用默认 | **直接回车**。默认是 `文档\MuseBridge`，脚本会自动建好这个空文件夹 |
| 允许 Muse 写入文件吗？第一次建议选否（只读模式）[y/N] | **第一次输入 `n`**。只读最安全，先让 Muse 读；以后想让它写文件再改 |
| 隧道模式：[1] 命名隧道（长期稳定，需域名） [2] 临时隧道（快速试用） | **先体验选 `2`**。选 1 需要你有一个自己的域名（且 DNS 在 Cloudflare），长期用再换 |

选 `2`（临时隧道）：装完最后会显示一个 `https://一串随机字符.trycloudflare.com` 的地址——**这个地址每次重启电脑都会变**，只适合先体验。
选 `1`（命名隧道）：中间会弹浏览器让你登录 Cloudflare 并授权，最后让你填一个公网域名（比如 `bridge.你的域名.com`）。

看到绿色的"**全部完成！**"就是装好了。你电脑上多了两个开机自启动任务（`MuseFileBridge API` 和 `MuseFileBridge Tunnel`），平时没有黑窗口，安静在后台跑，挂了会自动重启。

### 第 3 步：把地址发给 Muse，连上

把上一步得到的公网地址（`https://...` 那一整串）发给 Muse。

Muse 会发你一张**安全卡片**。你用记事本打开这个文件：

```
C:\Users\你的用户名\.muse-bridge\token
```

把里面那一长串令牌复制，填进安全卡片提交。**令牌相当于密码，只填进卡片，绝不要贴进聊天记录**（卡片是加密直传的，聊天记录不是）。

### 第 4 步：试一下

跟 Muse 说："列一下我 bridge 文件夹里有什么"。

如果第 2 步选的是只读（输入了 `n`），让 Muse 写文件会被拒绝——这是正常的，说明保护在生效。想开写入：用记事本打开 `C:\Users\你的用户名\.muse-bridge\config.json`，把 `read_only` 改成 `false`，保存；然后点开始菜单搜 `taskschd.msc` 打开任务计划程序，找到 `MuseFileBridge API`，右键"重新启动"。

## 安全吗？大白话版

- **Muse 只能看到你批准的文件夹。** 比如你只开放了 `文档\MuseBridge`，那桌面、下载、D 盘其他地方它都看不到、摸不着。这是服务端的硬限制，不是靠"自觉"。
- **令牌就是密码。** 只存在你电脑上那个 token 文件里，只填进安全卡片。想换就换：`python client/pcfile.py rotate-token`，旧的立刻作废，新的只写进你电脑上的文件。
- **默认只读。** 第一次先只读，确认 Muse 的行为符合预期，再亲手打开写入。
- **所有操作都有账本。** Muse 读了哪个、写了哪个文件，都记在 `C:\Users\你的用户名\.muse-bridge\audit.log` 里（每行一条），随时可查。
- **Muse 删不了你的文件。** 服务端故意没做删除接口。
- **不想用了就卸。** 见下面的"卸载"章节，一条命令清干净。

## 进阶：技术细节

### 架构

```
Windows 电脑                                        公网                 客户端
┌──────────────────────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│ muse-file-api.py                 │     │  Cloudflare Tunnel   │     │ pcfile.py        │
│ 只监听 127.0.0.1:18790           │◄────│  (TLS, 你的域名)     │◄────│ 或 curl /        │
│ 仅开放白名单目录                 │     │                      │     │ 任何 HTTP 客户端 │
└──────────────────────────────────┘     └──────────────────────┘     └──────────────────┘
```

### 为什么不用 MCP？

MCP server 只能被 MCP client 调用。如果你的助手不会说 MCP（或者根本连不上你的电脑），这个普通的 HTTPS API 就是更务实的选择：任何能发 HTTPS + 带令牌的客户端都能用。

### 手动安装（不喜欢一键脚本的人）

```powershell
python server\muse-file-api.py
```

首次运行会生成访问令牌并打印出来——记下来，只显示这一次。同时会生成默认配置：**只开放一个空的 `文档\MuseBridge` 目录，而且是只读模式**——直接跑也安全。想开放更多，编辑 `%USERPROFILE%\.muse-bridge\config.json`：

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

改完重启脚本生效。隧道手动搭建：

```powershell
cloudflared tunnel login
cloudflared tunnel create muse-bridge
cloudflared tunnel route dns muse-bridge bridge.你的域名.com
cloudflared tunnel run --url http://127.0.0.1:18790 muse-bridge
```

### 客户端（给助手 / 开发者用）

```bash
export MUSE_BRIDGE_TOKEN="<第 3 步填进卡片的令牌>"
export MUSE_BRIDGE_URL="https://bridge.你的域名.com"

python client/pcfile.py health
python client/pcfile.py list projects
python client/pcfile.py read projects notes/todo.txt
python client/pcfile.py write projects notes/todo.txt ./todo.txt
python client/pcfile.py mkdir projects new-folder
python client/pcfile.py sync ./my-plugin plugins my-plugin   # 上传整个文件夹
```

客户端拒绝明文 `http://` 地址——只有本地对着 `127.0.0.1` 测试时才加 `--allow-http`。

### API 说明

所有接口都需要在请求头带 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/api/health` | 存活检查，返回开放的目录白名单和协议 `version` |
| GET | `/api/list?root=NAME&path=REL` | 列目录（最多 5000 条，超限截断并标记 `truncated: true`） |
| GET | `/api/read?root=NAME&path=REL` | 读文件（UTF-8 文本直接返回，二进制转 base64） |
| POST | `/api/write` | JSON `{root, path, content, encoding}` —— 写文件，自动创建父目录 |
| POST | `/api/mkdir` | JSON `{root, path}` —— 建目录 |
| POST | `/api/rotate-token` | 轮换令牌——旧令牌立即失效。新令牌只写进电脑上的 token 文件，**不会在响应里返回**（防止经聊天记录泄漏） |

限制：单次读取 2 MB，单次写入 10 MB，每分钟约 1000 次请求（**整条隧道共享**——服务端看到的隧道请求全是 `127.0.0.1`，超了返回 `429`）。只读模式下 `write`/`mkdir` 返回 `403`。特意没有提供删除接口。

想让 Muse 对接这个 API？把 [CONNECTOR-BRIEF.md](CONNECTOR-BRIEF.md) 整个粘贴给它就行。

### 安全模型（完整版）

- 服务端只绑定 `127.0.0.1`——除了经由你自己的隧道，局域网和公网都连不进来。
- 每个请求都要带令牌（常量时间比较）。令牌只存在你电脑 `%USERPROFILE%\.muse-bridge\token` 里，文件权限仅限当前用户。随时可以调 `POST /api/rotate-token` 轮换，不用重启。
- 只能访问 `roots` 白名单里的目录。`..` 穿越、绝对路径、符号链接逃逸都会被拦截（先解析成真实路径再校验）。默认配置只开放一个空的 `文档\MuseBridge`。
- 新装默认**只读模式**——能读不能写——直到你把 `config.json` 里的 `read_only` 改成 `false`。第一次对接任何助手都建议先只读。
- 请求限流（每分钟约 1000 次，整条隧道共享）+ 审计日志（`audit.log`，10 MB 自动轮转保留 3 份）：时间、接口、目录、路径、结果码——助手读了写了什么，随时可查。
- 写文件是原子操作（临时文件 + 替换），传一半断掉也不会留下半截文件。
- 隧道提供 TLS。命名隧道地址稳定；安装脚本也能起一个 `trycloudflare.com` 临时隧道先体验，但每次重启地址都会变。

## 常见问题

- **安装脚本报一堆 ParserError / 中文乱码**——你下的是旧版 ZIP。重新下载最新版（已修复脚本编码问题）。
- **报 `401 unauthorized`**——客户端用的令牌和电脑上 `%USERPROFILE%\.muse-bridge\token` 对不上。重新复制一次（别贴进聊天，用助手的安全卡片流程）。
- **客户端连不上服务端**——电脑休眠/关机了，或者某个计划任务没跑起来。去任务计划程序看 `MuseFileBridge API` / `MuseFileBridge Tunnel` 的"上次运行结果"，以及 `%USERPROFILE%\.muse-bridge\server.log` 日志。
- **隧道地址变了**——你用的是临时隧道，重启后地址会变；把新地址发给助手更新。长期用请重跑安装选命名隧道。
- **端口被占用**——改 `%USERPROFILE%\.muse-bridge\config.json` 里的 `port`，重启 `MuseFileBridge API` 任务（隧道命令里是同一个端口）。
- **换令牌**——`python client/pcfile.py rotate-token`（需先设好令牌和地址）。旧令牌立即失效；新令牌只写在电脑 `%USERPROFILE%\.muse-bridge\token` 里，API 不返回、终端不打印，自己去文件里抄。
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
CHANGELOG.md              版本更新记录
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。

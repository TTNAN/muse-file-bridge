#Requires -Version 5.1
<#
.SYNOPSIS
    Muse File Bridge 一键安装脚本 (Windows)。

.DESCRIPTION
    1. 检查 Python 3.9+,缺失时尝试用 winget 自动安装
    2. 通过 winget 安装 cloudflared(若缺失)
    3. 安装服务端脚本到 %USERPROFILE%\.muse-bridge\
    4. 生成访问令牌(只存本机),创建 config.json 目录白名单
    5. 隧道二选一: 命名隧道(长期稳定)或临时隧道(快速试用)
    6. 注册两条登录自启动计划任务: MuseFileBridge API / MuseFileBridge Tunnel
       (后台无窗口运行,日志写 server.log / tunnel.log,失败自动重启)

    不需要管理员权限。重跑本脚本可更新已安装的服务端。卸载请运行 uninstall.ps1。
#>

$ErrorActionPreference = "Stop"

$BridgeHome = Join-Path $env:USERPROFILE ".muse-bridge"
$ServerFile = Join-Path $BridgeHome "muse-file-api.py"
$TokenFile  = Join-Path $BridgeHome "token"
$ConfigFile = Join-Path $BridgeHome "config.json"
$LogFile    = Join-Path $BridgeHome "server.log"
$TunnelLog  = Join-Path $BridgeHome "tunnel.log"
$TunnelName = "muse-bridge"
$Port       = 18790
$TaskApi    = "MuseFileBridge API"
$TaskTunnel = "MuseFileBridge Tunnel"

function Write-Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }
function Refresh-PathEnv {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}
function Write-Utf8NoBom($Path, $Text) {
    # PowerShell 5.1 的 Set-Content -Encoding UTF8 会带 BOM,Python 的 json.load(encoding="utf-8")
    # 遇到 BOM 直接抛 JSONDecodeError,而 PowerShell 自己读没事,导致"安装成功但服务起不来"。
    # 用 .NET 直接写无 BOM 的 UTF-8(pwsh 7 才有 -Encoding utf8NoBOM)。
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

# ---------- 1. Python ----------
Write-Step "检查 Python"
function Get-RealPython {
    # py 启动器优先: 直接问它真正的解释器路径
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $p = (& $pyLauncher.Source -3 -c "import sys; print(sys.executable)" 2>$null).Trim()
            if ($p -and (Test-Path $p) -and $p -notlike "*WindowsApps*") { return $p }
        } catch { }
    }
    # PATH 里的 python.exe 逐个试,跳过微软商店占位符
    foreach ($c in (Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if ($c.Source -like "*WindowsApps*") { continue }  # 商店占位符,不是真解释器
        try {
            $v = (& $c.Source --version 2>&1).ToString()
            if ($v -match "^Python \d") { return $c.Source }
        } catch { }
    }
    return $null
}
$pyExe = Get-RealPython
if (-not $pyExe) {
    Write-Host "没找到真正的 Python,尝试用 winget 安装 Python 3.12..."
    try {
        winget install --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
        Refresh-PathEnv
        $pyExe = Get-RealPython
    } catch { $pyExe = $null }
}
if (-not $pyExe) {
    throw "还是没找到 python.exe。请手动安装 Python 3.9+(安装时勾选 'Add python.exe to PATH')后重跑本脚本。"
}
$ver = (& $pyExe --version 2>&1).ToString()
if ($ver -match "Python (\d+)\.(\d+)") {
    if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 9)) {
        throw "Python 版本太旧 ($ver),需要 3.9+。"
    }
} else {
    throw "无法识别 Python 版本: $ver"
}
Write-Host "OK: $ver ($pyExe)"
$pythonw = Join-Path (Split-Path $pyExe -Parent) "pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "没找到 pythonw.exe,请完整重装一次 Python。" }

# ---------- 2. cloudflared ----------
Write-Step "检查 cloudflared"
New-Item -ItemType Directory -Force -Path $BridgeHome | Out-Null
$cf = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Host "没找到 cloudflared,尝试用 winget 安装..."
    try {
        winget install --id Cloudflare.cloudflared --silent --accept-source-agreements --accept-package-agreements
        Refresh-PathEnv
        $cf = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    } catch { $cf = $null }
}
if (-not $cf) {
    throw "没装上 cloudflared。请手动安装(Cloudflare 官网下载页搜 cloudflared),装好后重跑本脚本。"
}
$Cloudflared = $cf.Source
Write-Host "OK: $Cloudflared"

# ---------- 3. 服务端脚本 ----------
Write-Step "安装服务端"
$src = Join-Path $PSScriptRoot "server\muse-file-api.py"
if (-not (Test-Path $src)) { throw "找不到 $src,请在解压后的仓库根目录运行本脚本。" }
Copy-Item -Path $src -Destination $ServerFile -Force
Write-Host "OK: $ServerFile (重跑本脚本即可更新)"

# ---------- 4. 令牌 ----------
Write-Step "访问令牌"
if (Test-Path $TokenFile) {
    Write-Host "令牌已存在,跳过生成。"
    # 旧版安装曾把 token 设成只读 (R),补成 (R,W) 以免 /api/rotate-token 写不进去
    try { icacls $TokenFile /inheritance:r /grant:r "$env:USERNAME:(R,W)" | Out-Null } catch { }
} else {
    # token 首字符避开 '-',否则客户端 --token <值> 会被 argparse 当成选项
    do {
        $token = (& $pyExe -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
    } while ($token.StartsWith("-"))
    Set-Content -Path $TokenFile -Value $token -NoNewline -Encoding Ascii
    try { icacls $TokenFile /inheritance:r /grant:r "$env:USERNAME:(R,W)" | Out-Null } catch { }
    Write-Host "已生成新令牌,保存在: $TokenFile (仅你可读写,供服务端轮换令牌时写入)"
}
Write-Host "等 Muse 发你安全卡片后,把这个文件里的令牌填进去。不要发在聊天里。"

# ---------- 5. 白名单配置 ----------
Write-Step "目录白名单"
if (-not (Test-Path $ConfigFile)) {
    $defaultRoot = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "MuseBridge"
    $answer = Read-Host "允许 Muse 访问哪些目录? 逗号分隔多个,直接回车用默认 [$defaultRoot]"
    if ([string]::IsNullOrWhiteSpace($answer)) { $dirs = @($defaultRoot) } else { $dirs = $answer -split "," }
    $roots = @{}
    foreach ($d in $dirs) {
        $d = $d.Trim().Trim('"')
        if (-not $d) { continue }
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        $key = ((Split-Path $d -Leaf).ToLower() -replace "[^a-z0-9_]+", "_")
        if (-not $key) { $key = "root" }
        $base = $key; $i = 1
        while ($roots.ContainsKey($key)) { $i++; $key = "$base$i" }
        $roots[$key] = $d
        Write-Host "  $key -> $d"
    }
    if ($roots.Count -eq 0) { throw "没有有效的目录,安装中止。" }
    $roAnswer = Read-Host "允许 Muse 写入文件吗? 第一次建议选否(只读模式,随时可改) [y/N]"
    $readOnly = -not ($roAnswer -match "^[Yy]")
    $json = (@{ port = $Port; read_only = $readOnly; roots = $roots } | ConvertTo-Json -Depth 3)
    Write-Utf8NoBom $ConfigFile $json  # 无 BOM,Python 才能读
    Write-Host "已生成: $ConfigFile (只读模式: $(if ($readOnly) { '开' } else { '关' }))。以后用记事本改,改完重启 '$TaskApi' 任务生效。"
} else {
    Write-Host "config.json 已存在,跳过。"
    try {
        $cfg = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        $homeDir = $env:USERPROFILE.TrimEnd("\")
        $wide = @()
        foreach ($prop in $cfg.roots.PSObject.Properties) {
            if ($prop.Value.TrimEnd("\") -ieq $homeDir) { $wide += $prop.Name }
        }
        if ($wide.Count -gt 0) {
            Write-Warning "检测到白名单包含整个用户目录 ($($wide -join ', ')),风险较高。"
            $fix = Read-Host "是否收窄为仅 Documents\MuseBridge? [Y/n]"
            if ($fix -notmatch "^[Nn]") {
                $defaultRoot = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "MuseBridge"
                New-Item -ItemType Directory -Force -Path $defaultRoot | Out-Null
                $cfg.roots = @{ bridge = $defaultRoot }
                Write-Utf8NoBom $ConfigFile ($cfg | ConvertTo-Json -Depth 3)  # 无 BOM
                Write-Host "已收窄白名单,重启 '$TaskApi' 任务生效。"
            }
        }
    } catch { Write-Warning "config.json 解析失败,跳过检查。" }
}

# ---------- 6. 隧道 ----------
Write-Step "Cloudflare 隧道"
$hostname = $null
$trial = $false
$mode = Read-Host "隧道模式: [1] 命名隧道(长期稳定,需域名,推荐) [2] 临时隧道(快速试用,地址重启就变) [1]"
if ($mode -eq "2") {
    $trial = $true
    Write-Host "试用模式: 将使用临时隧道地址(每次重启都会变,仅适合验证)。"
    $tunnelArgs = "--logfile `"$TunnelLog`" tunnel --url http://127.0.0.1:$Port"  # --logfile 是全局参数,必须放子命令前面
} else {
    $exists = $false
    try {
        $listJson = (& $Cloudflared tunnel list --output json 2>$null | Out-String)
        if ($listJson.Trim().StartsWith("[")) {
            $exists = (($listJson | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName } | Measure-Object).Count -gt 0)
        }
    } catch { }
    if (-not $exists) {
        $tl = (& $Cloudflared tunnel list 2>&1 | Out-String)
        if ($tl -match [regex]::Escape($TunnelName)) { $exists = $true }
    }
    if ($exists) {
        Write-Host "隧道 '$TunnelName' 已存在,跳过创建。"
    } else {
        Write-Host "浏览器即将打开 Cloudflare 登录页,请登录并授权(选择你的域名所在的账号)..."
        & $Cloudflared tunnel login
        & $Cloudflared tunnel create $TunnelName
    }
    $hostname = Read-Host "给隧道绑定的公网域名 (例如 bridge.你的域名.com,回车跳过)"
    if (-not [string]::IsNullOrWhiteSpace($hostname)) {
        $hostname = $hostname.Trim()
        try {
            & $Cloudflared tunnel route dns $TunnelName $hostname
            Write-Host "OK: https://$hostname -> http://127.0.0.1:$Port"
        } catch {
            Write-Warning "自动绑定 DNS 失败,请手动执行: cloudflared tunnel route dns $TunnelName $hostname"
            Write-Warning "要求: 该域名的 DNS zone 必须在你刚才登录的 Cloudflare 账号下。"
        }
    } else {
        Write-Warning "已跳过域名绑定,稍后手动执行: cloudflared tunnel route dns $TunnelName <你的域名>"
    }
    $tunnelArgs = "--logfile `"$TunnelLog`" tunnel run $TunnelName --url http://127.0.0.1:$Port"  # --logfile 是全局参数,必须放子命令前面
}

# ---------- 7. 自启动计划任务 ----------
Write-Step "注册登录自启动"
# 用当前登录身份的规范名: 微软账号/AAD 机器上 USERDOMAIN\USERNAME 可能对不上 SID
$taskUser = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).Name

$apiAction = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$ServerFile`" --log-file `"$LogFile`""
$apiTrigger = New-ScheduledTaskTrigger -AtLogOn
$apiPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$apiSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
try {
    Register-ScheduledTask -TaskName $TaskApi -Action $apiAction -Trigger $apiTrigger -Principal $apiPrincipal -Settings $apiSettings -Force -Description "Muse File Bridge: 本地文件 API (127.0.0.1:$Port)" | Out-Null
} catch {
    throw "注册计划任务 '$TaskApi' 失败: $($_.Exception.Message)`n当前用户: $taskUser。请确认以本地用户身份运行 PowerShell,或手动在任务计划程序里创建。"
}

$tunAction = New-ScheduledTaskAction -Execute $Cloudflared -Argument $tunnelArgs -WorkingDirectory (Split-Path $Cloudflared -Parent)
$tunTrigger = New-ScheduledTaskTrigger -AtLogOn
$tunPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$tunSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$tunDesc = if ($trial) { "Muse File Bridge: Cloudflare 临时隧道" } else { "Muse File Bridge: Cloudflare 隧道" }
try {
    Register-ScheduledTask -TaskName $TaskTunnel -Action $tunAction -Trigger $tunTrigger -Principal $tunPrincipal -Settings $tunSettings -Force -Description $tunDesc | Out-Null
} catch {
    throw "注册计划任务 '$TaskTunnel' 失败: $($_.Exception.Message)`n当前用户: $taskUser。请确认以本地用户身份运行 PowerShell,或手动在任务计划程序里创建。"
}
Write-Host "OK: 已注册 '$TaskApi' 与 '$TaskTunnel'(用户登录时自动启动,无窗口,失败自动重启)"

# 个别系统会把 0 当成默认 72 小时,装完确认「运行超过以下时间后停止」是关闭的
foreach ($t in @($TaskApi, $TaskTunnel)) {
    $limit = (Get-ScheduledTask -TaskName $t).Settings.ExecutionTimeLimit
    if ($limit -and $limit -ne "PT0S") {
        Write-Warning "任务 '$t' 的执行时间限制是 $limit,可能被系统自动杀掉。请在任务计划程序里把「如果任务运行超过以下时间就停止」关掉。"
    }
}

# ---------- 8. 立即启动并验证 ----------
Write-Step "启动并验证"
Start-ScheduledTask -TaskName $TaskApi
Write-Host "等待 API 启动(Defender 首次扫描 pythonw 可能较慢,最多等 30 秒)..."
$token = (Get-Content $TokenFile -Raw).Trim()
$health = $null
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 5
        break
    } catch { Start-Sleep -Seconds 2 }
}
if ($health) {
    $ro = if ($health.read_only) { "开" } else { "关" }
    Write-Host ("OK: API 存活,开放目录: " + ($health.roots -join ", ") + ",只读模式: $ro")
} else {
    Write-Warning "API 30 秒内没起来,看日志排查: $LogFile"
}
Start-ScheduledTask -TaskName $TaskTunnel
Write-Host "隧道启动中..."

if ($trial) {
    Write-Host "等待临时隧道地址..."
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-Path $TunnelLog) {
            $m = Select-String -Path $TunnelLog -Pattern "https://[a-zA-Z0-9-]+\.trycloudflare\.com" | Select-Object -Last 1
            if ($m) { $hostname = $m.Matches[0].Value -replace "^https://", ""; break }
        }
    }
    if ($hostname) {
        Write-Host "临时地址: https://$hostname (重启后会变,长期用请重跑安装选命名隧道)" -ForegroundColor Yellow
    } else {
        Write-Warning "没抓到临时地址,看日志: $TunnelLog"
    }
}

Write-Host "`n全部完成!" -ForegroundColor Green
Write-Host "  令牌文件: $TokenFile"
Write-Host "  日志文件: $LogFile"
Write-Host "  审计日志: $(Join-Path $BridgeHome 'audit.log')"
if ($hostname) {
    Write-Host "  接下来: 把 https://$hostname 发给 Muse,Muse 会发你安全卡片收令牌并验证连通。"
} else {
    Write-Host "  接下来: 先绑定域名,再把公网地址发给 Muse。"
}

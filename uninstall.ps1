#Requires -Version 5.1
<#
.SYNOPSIS
    卸载 Muse File Bridge 的开机自启动任务。
.DESCRIPTION
    删除计划任务 "MuseBridge API" 与 "MuseBridge Tunnel",
    可选是否一并删除 %USERPROFILE%\.muse-bridge (配置、白名单、令牌)。
#>

$ErrorActionPreference = "Stop"

foreach ($name in @("MuseBridge API", "MuseBridge Tunnel")) {
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($t) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "已删除计划任务: $name"
    } else {
        Write-Host "计划任务不存在,跳过: $name"
    }
}

$bridgeHome = Join-Path $env:USERPROFILE ".muse-bridge"
$answer = Read-Host "是否一并删除 $bridgeHome (含配置、白名单和令牌,不可恢复)? [y/N]"
if ($answer -match "^[Yy]") {
    Remove-Item -Recurse -Force $bridgeHome
    Write-Host "已删除 $bridgeHome"
} else {
    Write-Host "保留 $bridgeHome。以后想重装,直接再运行 install.ps1 即可。"
}

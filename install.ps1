<#
.SYNOPSIS
  知识图谱系统一键安装脚本（PowerShell 薄封装，逻辑在 install.py）
.EXAMPLE
  .\install.ps1
  .\install.ps1 -TargetPath C:\path\to\project
  .\install.ps1 -TargetPath C:\path\to\project -KgDir .claude/kg
#>
param(
  [string]$TargetPath = ".",
  [string]$KgDir = ".claude/kg"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$py = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if ($null -eq $py) {
  Write-Error "需要 Python 3（工具脚本运行时依赖），请先安装"
  exit 1
}
& $py.Source -X utf8 (Join-Path $ScriptDir "install.py") $TargetPath --kg-dir $KgDir
exit $LASTEXITCODE

# 用 Windows 自带的 C# 编译器生成单文件安装包。
#   先确保 ..\dist\Pomodoro\ 存在，再运行本脚本。
# 产物：..\dist\Pomodoro-Setup.exe
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$dist = Join-Path $root 'dist'
$app = Join-Path $dist 'Pomodoro'
$staging = Join-Path $here 'staging'
$payload = Join-Path $staging 'payload.zip'
$output = Join-Path $dist 'Pomodoro-Setup.exe'

if (-not (Test-Path (Join-Path $app 'Pomodoro.exe'))) {
    throw "找不到 $app\Pomodoro.exe，先用 flet pack -D 打包应用"
}

New-Item -ItemType Directory -Force -Path $staging | Out-Null

if (-not (Test-Path $payload)) {
    Write-Host '正在压缩应用文件…'
    Compress-Archive -Path $app -DestinationPath $payload -CompressionLevel Optimal -Force
}
Write-Host ("payload: {0:N1} MB" -f ((Get-Item $payload).Length / 1MB))

$csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$fw = Split-Path -Parent $csc

$refs = @(
    'System.dll', 'System.Core.dll', 'System.Windows.Forms.dll', 'System.Drawing.dll',
    'System.IO.Compression.dll', 'System.IO.Compression.FileSystem.dll', 'Microsoft.CSharp.dll'
)
$cscArgs = @()
$cscArgs += '/target:winexe'
$cscArgs += '/codepage:65001'
$cscArgs += '/optimize+'
$cscArgs += '/nologo'
foreach ($name in $refs) { $cscArgs += ('/r:' + (Join-Path $fw $name)) }
$cscArgs += ('/resource:' + $payload)
$cscArgs += ('/win32icon:' + (Join-Path $root 'assets\icon.ico'))
$cscArgs += ('/out:' + $output)
$cscArgs += (Join-Path $here 'Installer.cs')
Write-Host '正在编译安装程序…'
& $csc $cscArgs
if ($LASTEXITCODE -ne 0) { throw "csc 编译失败（退出码 $LASTEXITCODE）" }

Write-Host ("生成: {0}  ({1:N1} MB)" -f $output, ((Get-Item $output).Length / 1MB))
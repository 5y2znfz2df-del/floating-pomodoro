@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
title 悬浮番茄钟 - 安装

set "SRC=%~dp0Pomodoro"
set "DEST=%LOCALAPPDATA%\Programs\Pomodoro"

echo.
echo   悬浮番茄钟 - 安装
echo   --------------------------------
echo.

if not exist "%SRC%\Pomodoro.exe" (
    echo   错误：找不到 "%SRC%\Pomodoro.exe"
    echo   请把这个 cmd 和 Pomodoro 文件夹放在一起。
    echo.
    pause
    exit /b 1
)

echo   正在复制到 %DEST% ...
if exist "%DEST%" rd /s /q "%DEST%" 2>nul
mkdir "%DEST%" 2>nul
xcopy "%SRC%" "%DEST%" /E /I /Y /Q >nul

if not exist "%DEST%\Pomodoro.exe" (
    echo.
    echo   复制失败。可能是安全软件拦住了写入。
    echo   可以先用绿色版：直接双击 Pomodoro\Pomodoro.exe
    echo.
    pause
    exit /b 1
)

echo   正在创建快捷方式 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%DEST%'; $e=Join-Path $d 'Pomodoro.exe'; $s=New-Object -ComObject WScript.Shell; $l=$s.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '悬浮番茄钟.lnk')); $l.TargetPath=$e; $l.WorkingDirectory=$d; $l.IconLocation=($e+',0'); $l.Save(); $m=Join-Path ([Environment]::GetFolderPath('Programs')) '悬浮番茄钟'; New-Item -ItemType Directory -Force -Path $m | Out-Null; $l2=$s.CreateShortcut((Join-Path $m '悬浮番茄钟.lnk')); $l2.TargetPath=$e; $l2.WorkingDirectory=$d; $l2.IconLocation=($e+',0'); $l2.Save()"

if errorlevel 1 echo   快捷方式创建失败（不影响使用）

echo.
echo   安装完成，正在启动 ...
start "" "%DEST%\Pomodoro.exe"
timeout /t 2 >nul
exit /b 0
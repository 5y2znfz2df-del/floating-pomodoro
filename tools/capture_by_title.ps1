# Capture a window by exact title, honouring DPI.
#   powershell -File tools/capture_by_title.ps1 -Title "番茄钟" -Out shot.png
# ASCII-only source on purpose (PowerShell 5.1 parses .ps1 as GBK without a BOM).
param(
    [Parameter(Mandatory = $true)][string]$Title,
    [string]$Out = "shot.png"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class ByTitle {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr p);
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
[void][ByTitle]::SetProcessDPIAware()

$script:t = [IntPtr]::Zero
$script:wanted = $Title
$cb = [ByTitle+EnumWindowsProc]{
    param($hWnd, $lParam)
    if ([ByTitle]::IsWindowVisible($hWnd)) {
        $sb = New-Object System.Text.StringBuilder 512
        [void][ByTitle]::GetWindowText($hWnd, $sb, 512)
        if ($sb.ToString() -eq $script:wanted) {
            $script:t = $hWnd
            return $false
        }
    }
    return $true
}
[void][ByTitle]::EnumWindows($cb, [IntPtr]::Zero)

if ($script:t -eq [IntPtr]::Zero) {
    Write-Output "window not found: $Title"
    exit 1
}

[void][ByTitle]::SetForegroundWindow($script:t)
Start-Sleep -Milliseconds 700
$r = New-Object ByTitle+RECT
[void][ByTitle]::GetWindowRect($script:t, [ref]$r)
$w = $r.Right - $r.Left
$h = $r.Bottom - $r.Top
if ($w -le 0 -or $h -le 0) { Write-Output "bad size ${w}x${h}"; exit 1 }

$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
$g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output "captured ${w}x${h} at $($r.Left),$($r.Top) -> $Out"

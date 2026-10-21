"""Windows 原生窗口特效：亚克力模糊 + 圆角。

Flet 本身没有暴露「背景模糊」能力，这里直接调 DWM / user32 的接口
给窗口加一层毛玻璃，配合 Flet 里的半透明容器，就能做出接近
macOS/iOS 液态玻璃的观感。

所有函数都是「尽力而为」：非 Windows、系统版本不支持、调用失败时，
一律静默返回 False，程序照常运行（只是退回不透明的普通窗口）。
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

# SetWindowCompositionAttribute 的 AccentState
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

WCA_ACCENT_POLICY = 19

# DwmSetWindowAttribute 的两个属性编号
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38

DWMWCP_ROUND = 2


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", wintypes.DWORD),
        ("AccentFlags", wintypes.DWORD),
        ("GradientColor", wintypes.DWORD),
        ("AnimationId", wintypes.DWORD),
    ]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attrib", wintypes.DWORD),
        ("pvData", ctypes.c_void_p),
        ("cbData", ctypes.c_size_t),
    ]


def find_window(title: str, timeout: float = 6.0) -> int | None:
    """按标题找窗口句柄；窗口刚创建时可能出现得晚，所以带重试。"""
    if not IS_WINDOWS:
        return None

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value == title and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        found.clear()
        user32.EnumWindows(WNDENUMPROC(_callback), 0)
        if found:
            return found[0]
        time.sleep(0.25)
    return None


def enable_acrylic(hwnd: int, tint: tuple[int, int, int] = (18, 18, 20), alpha: int = 168) -> bool:
    """把窗口背景换成亚克力（毛玻璃）。alpha 0-255，越大越不透明。"""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_attr = user32.SetWindowCompositionAttribute
        set_attr.argtypes = [wintypes.HWND, ctypes.POINTER(_WINDOWCOMPOSITIONATTRIBDATA)]
        set_attr.restype = wintypes.BOOL

        r, g, b = tint
        # GradientColor 是 AABBGGRR 顺序
        gradient = (alpha << 24) | (b << 16) | (g << 8) | r
        policy = _ACCENT_POLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 2, gradient, 0)
        data = _WINDOWCOMPOSITIONATTRIBDATA(
            WCA_ACCENT_POLICY,
            ctypes.cast(ctypes.byref(policy), ctypes.c_void_p),
            ctypes.sizeof(policy),
        )
        return bool(set_attr(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def disable_acrylic(hwnd: int) -> bool:
    return enable_acrylic_state(hwnd, ACCENT_DISABLED)


def window_rect(title: str) -> tuple[int, int, int, int] | None:
    """取窗口的 (left, top, width, height)。

    本进程没有声明 DPI 感知，取到的是逻辑坐标，和 Flet 的窗口坐标系一致。
    """
    hwnd = find_window(title, timeout=1.0)
    if not hwnd:
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
        return (
            rect.left,
            rect.top,
            rect.right - rect.left,
            rect.bottom - rect.top,
        )
    except Exception:
        return None


def enable_acrylic_state(hwnd: int, state: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        policy = _ACCENT_POLICY(state, 0, 0, 0)
        data = _WINDOWCOMPOSITIONATTRIBDATA(
            WCA_ACCENT_POLICY,
            ctypes.cast(ctypes.byref(policy), ctypes.c_void_p),
            ctypes.sizeof(policy),
        )
        return bool(user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def enable_rounded_corners(hwnd: int) -> bool:
    """Windows 11 的窗口圆角；系统不支持时返回 False。"""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        dwm = ctypes.WinDLL("dwmapi")
        pref = ctypes.c_int(DWMWCP_ROUND)
        hr = dwm.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
        return hr == 0
    except Exception:
        return False


def set_backdrop(hwnd: int, kind: int = 3) -> bool:
    """DWM_SYSTEMBACKDROP_TYPE：2=Mica，3=Acrylic，4=Mica Alt（Win11 22H2+）。"""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        dwm = ctypes.WinDLL("dwmapi")
        value = ctypes.c_int(kind)
        hr = dwm.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        return hr == 0
    except Exception:
        return False


def make_frameless(hwnd: int) -> bool:
    """去掉窗口标题栏和调整边框。

    Flet 的 `window.frameless` 在某些环境里不会真正生效（窗口仍然带着
    WS_CAPTION），一开透明背景，系统的「最小化/最大化/关闭」三个按钮就露出来了。
    这里直接从 Win32 层把边框样式摘掉。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        GWL_STYLE = -16
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)
        new_style = style & ~WS_CAPTION & ~WS_THICKFRAME
        if new_style == style:
            return True
        user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE, new_style)
        user32.SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return True
    except Exception:
        return False


def apply_glass(title: str, tint: tuple[int, int, int] = (18, 18, 20), alpha: int = 168) -> dict:
    """一次性把无边框 + 毛玻璃 + 圆角都加上，返回每步的结果，方便打日志。

    注意：这里刻意**不**调用 set_backdrop()。给无边框窗口设置
    DWMWA_SYSTEMBACKDROP_TYPE，Windows 会顺手把原生标题栏画回来，
    和 frameless 冲突。亚克力 + 圆角已经够用。
    """
    hwnd = find_window(title)
    result = {"hwnd": hwnd, "frameless": False, "acrylic": False, "rounded": False}
    if not hwnd:
        return result
    result["frameless"] = make_frameless(hwnd)
    result["acrylic"] = enable_acrylic(hwnd, tint, alpha)
    result["rounded"] = enable_rounded_corners(hwnd)
    return result

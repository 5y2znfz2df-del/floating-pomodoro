"""flet_win_effects —— 给 Flet 的 Windows 窗口加原生特效。

只做四件事，全部通过 ctypes 直接调 Win32 / DWM 接口：

* **亚克力模糊**（Acrylic）—— ``SetWindowCompositionAttribute`` + ``ACCENT_ENABLE_ACRYLICBLURBEHIND``
* **无边框**—— 摘掉 ``WS_CAPTION`` / ``WS_THICKFRAME`` 样式
* **圆角**—— ``DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE)``
* **窗口几何读取**—— 拿 ``(left, top, width, height)``，给逐帧动画用

依赖：只用标准库（``ctypes`` / ``sys`` / ``time``）。**不依赖 flet**，也不依赖任何第三方包，
所以在非 Flet 的 Python 程序里同样能用。

设计原则：**尽力而为**。非 Windows、系统版本不支持、句柄拿不到、调用失败时，
每个函数都静默返回 ``False``（或 ``None``），不抛异常、不中断调用方。
这样调用方可以无脑调用，特效没挂上也只是一扇普通的窗口。

已验证：Windows 11（10.0.28000）。Windows 10 1803+ 按微软文档支持亚克力，但本项目未实测。
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

__all__ = [
    "IS_WINDOWS",
    "find_window",
    "window_rect",
    "make_frameless",
    "enable_acrylic",
    "disable_acrylic",
    "enable_acrylic_state",
    "enable_rounded_corners",
    "set_backdrop",
    "apply_glass",
]

IS_WINDOWS = sys.platform == "win32"
"""当前进程是否跑在 Windows 上。所有函数内部都会先看这个开关。"""

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
    """按窗口标题精确匹配，返回 HWND。

    参数:
        title: 窗口标题，必须完全一致（区分大小写）。
        timeout: 最长等待秒数。窗口刚创建时可能还没出现，所以内部每 250ms 重试一次。

    返回:
        找到返回 ``int`` 句柄；超时或非 Windows 返回 ``None``。

    失败行为:
        不抛异常。非 Windows 直接返回 ``None``。

    已验证:
        Windows 11（10.0.28000）—— 对 Flet 的无边框窗口可正常命中。
    """
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


def window_rect(title: str) -> tuple[int, int, int, int] | None:
    """读取窗口的 ``(left, top, width, height)``。

    用来做逐帧窗口动画：先记下原位，动画结束后再搬回去。

    参数:
        title: 窗口标题。

    返回:
        四元组；窗口不存在或读取失败返回 ``None``。

    失败行为:
        不抛异常，只返回 ``None``。

    注意:
        坐标是「逻辑像素」——本库没有声明 DPI 感知，系统会把物理坐标换算成逻辑坐标，
        这和 Flet 的 ``page.window`` 坐标系是一致的，可以直接互相赋值。

    已验证:
        Windows 11（10.0.28000）+ 150% 缩放，与 Flet 坐标系对齐。
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


def make_frameless(hwnd: int) -> bool:
    """摘掉窗口的标题栏和可调整边框。

    Flet 的 ``window.frameless = True`` 在部分环境里不会真正生效（窗口仍然带着
    ``WS_CAPTION``）。一旦页面背景设为透明，系统的「最小化 / 最大化 / 关闭」
    三个按钮就会直接露在内容上方。这里从 Win32 层再摘一次。

    参数:
        hwnd: 窗口句柄（``find_window`` 的返回值）。

    返回:
        成功或本来就没有边框时返回 ``True``；失败返回 ``False``。

    失败行为:
        静默返回 ``False``，窗口保持原样（带标题栏）。

    已验证:
        Windows 11（10.0.28000）—— 对 Flet 0.28 窗口生效，``WS_CAPTION`` 被清除。
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


def enable_acrylic(
    hwnd: int,
    tint: tuple[int, int, int] = (18, 18, 20),
    alpha: int = 168,
) -> bool:
    """给窗口挂上亚克力（Acrylic）毛玻璃。

    参数:
        hwnd: 窗口句柄。
        tint: 底色 RGB 元组，``(18, 18, 20)`` 是接近黑色的深灰。
        alpha: 0–255，越大越不透明。实测 130–170 之间观感最好；
            太高会盖住后面的桌面，太低文字会看不清。

    返回:
        成功返回 ``True``，失败返回 ``False``。

    失败行为:
        静默返回 ``False``。Windows 10 1803 以下、远程桌面会话、被组策略禁用时都可能失败，
        此时窗口保持不透明，功能不受影响。

    已验证:
        Windows 11（10.0.28000）—— 截图确认能透出并模糊化背后的桌面。
        Windows 10 未实测。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_attr = user32.SetWindowCompositionAttribute
        set_attr.argtypes = [wintypes.HWND, ctypes.POINTER(_WINDOWCOMPOSITIONATTRIBDATA)]
        set_attr.restype = wintypes.BOOL

        r, g, b = tint
        # GradientColor 是 AABBGGRR 顺序，不是常见的 RRGGBB
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
    """取消窗口上的毛玻璃，恢复成普通不透明窗口。

    参数:
        hwnd: 窗口句柄。

    返回:
        成功返回 ``True``，失败返回 ``False``。

    失败行为:
        静默返回 ``False``。
    """
    return enable_acrylic_state(hwnd, ACCENT_DISABLED)


def enable_acrylic_state(hwnd: int, state: int) -> bool:
    """直接设置 AccentState，用于切换或关闭特效。

    一般不需要直接调用：切到亚克力用 :func:`enable_acrylic`，关掉用 :func:`disable_acrylic`。

    参数:
        hwnd: 窗口句柄。
        state: ``ACCENT_DISABLED``(0) 关闭、``ACCENT_ENABLE_BLURBEHIND``(3) 普通模糊、
            ``ACCENT_ENABLE_ACRYLICBLURBEHIND``(4) 亚克力。

    返回:
        成功返回 ``True``，失败返回 ``False``。

    失败行为:
        静默返回 ``False``。
    """
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
    """把窗口本身裁成圆角（Windows 11 特性）。

    参数:
        hwnd: 窗口句柄。

    返回:
        成功返回 ``True``，失败返回 ``False``。

    失败行为:
        静默返回 ``False``。Windows 10 上没有这个 DWM 属性，会直接失败并保持直角，
        此时可以改用 Flet 容器自己的 ``border_radius``（但外圈透明区域会是方的）。

    已验证:
        Windows 11（10.0.28000）—— 与亚克力叠加后窗口四角正常裁切。
    """
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
    """设置系统背景材质（Windows 11 22H2+ 的 DWM_SYSTEMBACKDROP_TYPE）。

    参数:
        hwnd: 窗口句柄。
        kind: ``2`` = Mica，``3`` = Acrylic，``4`` = Mica Alt。

    返回:
        成功返回 ``True``，失败返回 ``False``。

    失败行为:
        静默返回 ``False``。

    警告:
        **不要和 :func:`make_frameless` 一起用**。给无边框窗口设置 backdrop 时，
        Windows 会顺手把原生标题栏画回来，和去边框效果冲突（本项目实测踩过）。
        想要玻璃质感请用 :func:`enable_acrylic`。
    """
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


def apply_glass(
    title: str,
    tint: tuple[int, int, int] = (18, 18, 20),
    alpha: int = 168,
) -> dict:
    """一站式：按标题找到窗口，然后去边框 + 亚克力 + 圆角。

    这是最常用的入口，一行就能把特效挂上。

    参数:
        title: 窗口标题，必须和 ``page.title`` 完全一致。
        tint: 玻璃底色 RGB。
        alpha: 0–255 不透明度。

    返回:
        一个结果字典，方便打日志判断哪一步成功::

            {"hwnd": 123456, "frameless": True, "acrylic": True, "rounded": True}

        找不到窗口时 ``hwnd`` 为 ``None``，其余全部 ``False``。

    失败行为:
        不抛异常。任何一步失败都只是把对应字段置为 ``False``，窗口照常可用。

    用法::

        info = flet_win_effects.apply_glass("My App")
        print(info)   # 这行放启动日志里，提 issue 时贴出来最有用

    已验证:
        Windows 11（10.0.28000）+ Flet 0.28.3，无边框透明窗口上三个步骤全部成功。
    """
    hwnd = find_window(title)
    result = {"hwnd": hwnd, "frameless": False, "acrylic": False, "rounded": False}
    if not hwnd:
        return result
    result["frameless"] = make_frameless(hwnd)
    result["acrylic"] = enable_acrylic(hwnd, tint, alpha)
    result["rounded"] = enable_rounded_corners(hwnd)
    return result

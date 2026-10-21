"""
悬浮番茄钟 · Floating Pomodoro
=============================

一个常驻置顶、可拖动的小窗口番茄钟，界面走「液态玻璃」风格，
闲置 5 秒自动缩到屏幕右边缘，只留一条圆角小黑条。

特性
----
* 无边框悬浮窗，始终置顶，可拖动
* Windows 11 上通过 DWM 亚克力模糊 + 圆角，做出半透明玻璃质感
* 自定义专注 / 休息时长
* 倒计时结束播放提示音（Windows 系统 beep，无需音频文件）
* 深色 / 浅色主题一键切换
* 闲置自动收起 / 点小黑条展开
* 任务栏进度条显示倒计时进度
* 完全本地运行：不联网、不收集任何数据

运行
----
    python app.py

打包
----
    flet pack app.py --name Pomodoro --icon assets/icon.ico

依赖：flet == 0.28.3（该版本把 Flutter 桌面客户端打进 wheel，不需要联网下载）

许可证：MIT
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from dataclasses import dataclass, field

import flet as ft

import flet_win_effects as win_effects   # 窗口特效组件，见 flet_win_effects/

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

APP_TITLE = "番茄钟"

# 展开态与收起态的窗口尺寸（逻辑像素）
WINDOW_W, WINDOW_H = 250, 286
STRIP_VISIBLE = 10       # 收起后露在屏幕内的宽度（窗口最小宽度受 Flutter 限制，只能推出屏幕）
STRIP_H = 96            # 收起后的高度
BAND_H = 3              # 顶部不穿透的拖动条高度（逻辑像素）
BAND_POLL_MS = 40       # 穿透模式下光标轮询间隔

FOCUS_MIN, FOCUS_MAX = 1, 120
BREAK_MIN, BREAK_MAX = 1, 60

TICK = 0.25          # 计时刷新间隔（秒）
IDLE_SECONDS = float(os.environ.get("POMODORO_IDLE_SECONDS", "5"))   # 多久没操作就收起
IDLE_POLL = 0.4      # 闲置检测轮询间隔

# 收起 / 展开的动画参数
ANIM_SLIDE_MS = 260  # 窗口滑动的目标时长
ANIM_STEPS = 12      # 缓动分几帧；每帧一次 page.update()，实测约 30ms 一帧
ANIM_FADE_MS = 140   # 面板淡入淡出的时长

COLOR_BREAK = "#30D158"

# 玻璃材质：8 位色值是 #AARRGGBB，前两位是透明度
GLASS = {
    "dark": {
        "panel": "#9E1C1C1E",        # 半透明面板，配合系统模糊就是毛玻璃
        "edge": "#30FFFFFF",         # 1px 高光描边
        "sheen": "#14FFFFFF",        # 顶部一道渐变高光
        "text": "#F5F5F7",
        "sub": "#9A9AA0",
        "accent": "#0A84FF",
        "bar_bg": "#3A3A3C",
        "strip": "#E6111113",        # 收起后的黑条
    },
    "light": {
        "panel": "#B8FFFFFF",
        "edge": "#40FFFFFF",
        "sheen": "#26FFFFFF",
        "text": "#1D1D1F",
        "sub": "#6E6E73",
        "accent": "#0071E3",
        "bar_bg": "#D8D8DD",
        "strip": "#E61A1A1C",
    },
}


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    """用户可调的时长（分钟）。"""

    focus: int = 25
    break_: int = 5


@dataclass
class State:
    """运行中的计时状态。"""

    phase: str = "focus"
    running: bool = False
    remaining: float = 0.0
    total: float = 0.0
    done_count: int = 0
    last_tick: float = field(default=0.0)


# --------------------------------------------------------------------------- #
# 纯函数（可单独测试）
# --------------------------------------------------------------------------- #
def mmss(seconds: float) -> str:
    """秒数格式化为 MM:SS。"""
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def other_phase(phase: str) -> str:
    return "break" if phase == "focus" else "focus"


def phase_seconds(phase: str, settings: Settings) -> float:
    minutes = settings.focus if phase == "focus" else settings.break_
    return float(minutes * 60)


def progress_of(remaining: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, 1 - remaining / total))


def ease_out_cubic(t: float) -> float:
    """收尾慢的缓动曲线，0→1。

    苹果的界面动效基本都是 ease-out：起步快、结束柔和，
    比线性移动主观上「顺滑」得多。
    """
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _screen_size() -> tuple[int, int]:
    """屏幕尺寸（逻辑像素）。

    本进程没有声明 DPI 感知，取到的正好是 Flet 使用的逻辑坐标，
    不用再自己按缩放比换算。
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:  # noqa: BLE001 - 非 Windows 或调用失败时给个保底值
        return 1280, 720


def _cursor_pos() -> tuple[int, int]:
    """当前鼠标位置，坐标空间和 win_effects.window_rect() 一致。"""
    try:
        import ctypes

        point = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return int(point.x), int(point.y)
    except Exception:  # noqa: BLE001
        return 0, 0


def _foreground_window() -> int:
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:  # noqa: BLE001
        return 0


def _key_down(vk: int) -> bool:
    """某个虚拟键是否按下过。

    两个位都要看：``0x8000`` 是当前按住，``0x0001`` 是「上次查询之后按下过」。
    只查前者会漏掉快速敲击（按下到松开可能只有几毫秒，轮询间隔 50ms 抓不到）。
    """
    try:
        import ctypes

        state = ctypes.windll.user32.GetAsyncKeyState(vk)
        return bool(state & 0x8000) or bool(state & 0x0001)
    except Exception:  # noqa: BLE001
        return False


async def _maybe_await(value):
    """Flet 不同小版本里窗口方法时而是协程，统一兼容。"""
    if inspect.isawaitable(value):
        await value
    return value


def beep(kind: str = "done") -> None:
    """播放提示音。用系统自带 beep，不依赖任何音频文件。"""
    try:
        import winsound
    except ImportError:
        print("\a", end="", flush=True)
        return

    def play() -> None:
        try:
            if kind == "focus_end":
                for freq, ms in ((784, 160), (988, 160), (1319, 320)):
                    winsound.Beep(freq, ms)
            elif kind == "break_end":
                for freq, ms in ((988, 140), (784, 140)):
                    winsound.Beep(freq, ms)
            else:
                winsound.Beep(880, 200)
        except RuntimeError:
            pass

    import threading

    threading.Thread(target=play, daemon=True).start()


# --------------------------------------------------------------------------- #
# 主应用
# --------------------------------------------------------------------------- #
class PomodoroApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.settings = Settings()
        self.state = State()
        self.dark = True
        self.pinned = True
        self.collapsed = False
        self._strip_side = "right"   # 收起时贴哪边："left" / "right"
        self._strip_top = 0          # 收起态的目标纵向位置
        self._strip_left = 0         # 收起态的目标横向位置
        self.click_through = False   # 是否处于穿透模式
        self.locked = False          # 是否锁定（禁止拖动）
        self._band_hot = False       # 光标是否正在顶部拖动条上
        self._dpi_scale = 1.0        # 物理像素 / 逻辑像素，挂上特效后测出来
        self._hwnd = 0               # 本窗口句柄，挂上特效后拿到
        self.last_active = time.monotonic()
        self._saved_geom: tuple = ()
        self._task: asyncio.Task | None = None

        self._build_ui()
        self._apply_theme()
        self.reset_timer()
        self.page.on_keyboard_event = self._on_key
        self.page.run_task(self._idle_watch)
        self.page.run_task(self._apply_glass)
        self.page.run_task(self._watch_band)
        self.page.run_task(self._watch_hotkey)

    # ------------------------------------------------------------- 玻璃外壳 --
    async def _apply_glass(self) -> None:
        """窗口真正显示出来之后再挂毛玻璃，太早拿不到句柄。"""
        await asyncio.sleep(1.2)
        info = win_effects.apply_glass(APP_TITLE, tint=(18, 18, 20), alpha=132)
        print(f"[pomodoro] glass = {info}", flush=True)
        self._hwnd = info.get("hwnd") or 0
        # 纯展示窗口，去掉输入法关联，否则按 P 会弹中文候选框
        if self._hwnd:
            win_effects.disable_ime(self._hwnd)

        # 量一下物理/逻辑像素比：穿透模式下判断光标是否落在 3px 拖动条里要用
        rect = win_effects.window_rect(APP_TITLE)
        if rect and rect[3]:
            self._dpi_scale = rect[3] / float(WINDOW_H)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        page = self.page
        page.title = APP_TITLE
        page.padding = 0
        page.spacing = 0
        # 关键：页面本身透明，系统的模糊效果才能透出来
        page.bgcolor = ft.Colors.TRANSPARENT

        win = page.window
        win.width = WINDOW_W
        win.height = WINDOW_H
        win.resizable = False
        win.frameless = True
        win.always_on_top = True
        win.min_height = STRIP_H    # 保证顶部 3px 拖动条永远存在（收起时也不会低于它）

        # --- 标题栏 ---
        self.title_text = ft.Text(APP_TITLE, size=11, weight=ft.FontWeight.W_600)
        self.pin_btn = ft.IconButton(
            icon=ft.Icons.PUSH_PIN, icon_size=13, width=26, height=26,
            tooltip="取消置顶", on_click=self.toggle_pin,
        )
        self.theme_btn = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE, icon_size=13, width=26, height=26,
            tooltip="切换深浅色", on_click=self.toggle_theme,
        )
        self.close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE, icon_size=13, width=26, height=26,
            tooltip="关闭", on_click=self.close_app,
        )

        self.lock_btn = ft.IconButton(
            icon=ft.Icons.LOCK_OPEN, icon_size=13, width=26, height=26,
            tooltip="锁定窗口", on_click=self.toggle_lock,
        )
        self.through_btn = ft.IconButton(
            icon=ft.Icons.TOUCH_APP, icon_size=13, width=26, height=26,
            tooltip="开启穿透（鼠标穿过本窗口）", on_click=self.toggle_click_through,
        )

        # 只有左边这块（标题 + 空白）可以拖；右侧按钮必须留在 drag area 外面，
        # 否则 WindowDragArea 会把点击吞掉，按钮点不动。
        header = ft.Container(
            content=ft.Row(
                [
                    ft.WindowDragArea(
                        content=ft.Container(
                            content=self.title_text,
                            expand=True,
                            alignment=ft.alignment.center_left,
                        ),
                        maximizable=False,
                        expand=True,
                    ),
                    self.pin_btn, self.theme_btn, self.lock_btn,
                    self.through_btn, self.close_btn,
                ],
                spacing=0,
            ),
            padding=ft.padding.only(left=12, right=2, top=2, bottom=0),
        )

        self.phase_text = ft.Text("专注", size=11, weight=ft.FontWeight.W_500)
        self.time_text = ft.Text(
            "25:00", size=40, weight=ft.FontWeight.W_300,
            text_align=ft.TextAlign.CENTER,
        )
        self.progress = ft.ProgressBar(value=0, bar_height=3, border_radius=2)

        self.start_btn = ft.FilledButton(
            text="开始", icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=self.toggle_timer, height=34, expand=True,
        )
        self.reset_btn = ft.OutlinedButton(
            text="重置",
            on_click=self.reset_timer, height=34, expand=True,
        )

        self.focus_row = self._stepper_row("专注", "focus", self.settings.focus)
        self.break_row = self._stepper_row("休息", "break_", self.settings.break_)
        self.stat_text = ft.Text("本次完成 0 个番茄", size=10)

        self.band_holder = ft.Container(content=self._build_band(), height=BAND_H)

        # 顶部一层极淡的渐变，模拟玻璃表面的高光
        self.sheen = ft.Container(
            height=44,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_center,
                end=ft.alignment.bottom_center,
                colors=["#00000000", "#00000000"],
            ),
            border_radius=ft.border_radius.only(top_left=14, top_right=14),
        )

        body = ft.Stack(
            controls=[
                self.sheen,
                ft.Container(
                    content=ft.Column(
                        [
                            # 顶部 3px 拖动条：穿透模式下唯一能接收鼠标的地方
                            self.band_holder,
                            header,
                            ft.Container(
                                content=ft.Column(
                                    [
                                        self.phase_text,
                                        self.time_text,
                                        self.progress,
                                        ft.Row(
                                            [self.start_btn, self.reset_btn],
                                            alignment=ft.MainAxisAlignment.CENTER,
                                            spacing=8,
                                        ),
                                        ft.Divider(height=1),
                                        self.focus_row,
                                        self.break_row,
                                        ft.Container(expand=True),
                                        self.stat_text,
                                    ],
                                    spacing=9,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                padding=ft.padding.symmetric(horizontal=16, vertical=4),
                                expand=True,
                            ),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                    expand=True,
                ),
            ],
            expand=True,
        )

        self._expanded_body = body   # 收起后展开时直接复用同一棵控件树

        self.root = ft.Container(
            content=body,
            bgcolor=GLASS["dark"]["panel"],
            border=ft.border.all(1, GLASS["dark"]["edge"]),
            border_radius=14,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            expand=True,
            on_hover=self._on_hover,
        )

        page.add(self.root)

    def _stepper_row(self, label: str, attr: str, value: int) -> ft.Row:
        num = ft.Text(str(value), size=12, width=26, text_align=ft.TextAlign.CENTER)
        label_ctrl = ft.Text(label, size=11, width=32)
        minus = ft.IconButton(
            icon=ft.Icons.REMOVE, icon_size=12, width=24, height=24,
            tooltip=f"减少{label}时长", data=(attr, -1), on_click=self.step_change,
        )
        plus = ft.IconButton(
            icon=ft.Icons.ADD, icon_size=12, width=24, height=24,
            tooltip=f"增加{label}时长", data=(attr, 1), on_click=self.step_change,
        )
        setattr(self, f"_num_{attr}", num)
        setattr(self, f"_label_{attr}", label_ctrl)
        setattr(self, f"_minus_{attr}", minus)
        setattr(self, f"_plus_{attr}", plus)
        return ft.Row(
            [label_ctrl, ft.Container(expand=True), minus, num, plus],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # --------------------------------------------------------------- 主题 --
    def _palette(self) -> dict:
        return GLASS["dark" if self.dark else "light"]

    def _apply_theme(self) -> None:
        c = self._palette()

        self.page.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        self.root.bgcolor = c["panel"]
        self.root.border = ft.border.all(1, c["edge"])
        self.sheen.gradient = ft.LinearGradient(
            begin=ft.alignment.top_center,
            end=ft.alignment.bottom_center,
            colors=[c["sheen"], "#00000000"],
        )

        self.title_text.color = c["sub"]
        self.phase_text.color = c["accent"]
        self.time_text.color = c["text"]
        self.stat_text.color = c["sub"]

        self.pin_btn.icon_color = c["accent"] if self.pinned else c["sub"]
        self.theme_btn.icon_color = c["sub"]
        self.close_btn.icon_color = c["sub"]
        self.lock_btn.icon_color = c["accent"] if self.locked else c["sub"]
        self.through_btn.icon_color = c["sub"]

        self.progress.color = c["accent"]
        self.progress.bgcolor = c["bar_bg"]

        for attr in ("focus", "break_"):
            getattr(self, f"_num_{attr}").color = c["text"]
            getattr(self, f"_label_{attr}").color = c["sub"]
            getattr(self, f"_minus_{attr}").icon_color = c["sub"]
            getattr(self, f"_plus_{attr}").icon_color = c["sub"]

        self.theme_btn.icon = ft.Icons.LIGHT_MODE if self.dark else ft.Icons.DARK_MODE
        self.pin_btn.icon = (
            ft.Icons.PUSH_PIN if self.pinned else ft.Icons.PUSH_PIN_OUTLINED
        )
        self.page.window.always_on_top = self.pinned
        self.page.update()

    # ------------------------------------------------------ 穿透 / 锁定 / 拖动条 --
    def _build_band(self) -> ft.Control:
        """顶部 3px 拖动条。

        规则：常态下支持拖动；**锁定后去掉拖动**（此时穿透模式只能靠 P 键退出）。
        """
        self.band_line = ft.Container(
            height=BAND_H,
            bgcolor="#00000000",
            border_radius=ft.border_radius.only(top_left=14, top_right=14),
        )
        detector = ft.GestureDetector(
            content=self.band_line,
            mouse_cursor=ft.MouseCursor.MOVE,   # 悬停显示拖动光标
            on_enter=self._on_band_enter,
            on_exit=self._on_band_exit,
        )
        if self.locked:
            return detector
        return ft.WindowDragArea(content=detector, maximizable=False)

    def _on_band_enter(self, e=None) -> None:
        """悬停：亮一条淡色提示线，告诉用户这里可以拖。"""
        self._touch()
        accent = self._palette()["accent"]
        self.band_line.bgcolor = "#40" + accent[1:]
        self.page.update()

    def _on_band_exit(self, e=None) -> None:
        self.band_line.bgcolor = "#00000000"
        self.page.update()

    async def toggle_lock(self, e=None) -> None:
        self._touch()
        self.locked = not self.locked
        self.band_holder.content = self._build_band()
        c = self._palette()
        self.lock_btn.icon = ft.Icons.LOCK if self.locked else ft.Icons.LOCK_OPEN
        self.lock_btn.icon_color = c["accent"] if self.locked else c["sub"]
        self.lock_btn.tooltip = "解锁窗口（当前锁定）" if self.locked else "锁定窗口"
        self.page.update()

    async def toggle_click_through(self, e=None) -> None:
        self._touch()
        await self._set_click_through(not self.click_through)

    async def _set_click_through(self, on: bool) -> None:
        """真正切换穿透样式，并同步按钮可见性。"""
        hwnd = win_effects.find_window(APP_TITLE, timeout=1.0)
        if not hwnd:
            return
        if not win_effects.set_click_through(hwnd, on):
            return
        self.click_through = on
        self._band_hot = False
        # 规则 3a：开启按钮只在非穿透模式可见
        self.through_btn.visible = not on
        self.page.update()

    def _on_key(self, e) -> None:
        """规则 3b / 4：窗口有焦点时，P 切换穿透。

        Flet 的 on_keyboard_event 只在 Flutter 内部有焦点控件时才会来事件，
        本程序没有输入框，所以这条基本收不到；真正的实现是 _watch_hotkey()
        的轮询。这里保留一份，某些平台/版本上它是有用的。
        """
        key = (getattr(e, "key", "") or "").lower()
        if key == "p":
            self.page.run_task(self.toggle_click_through)

    async def _watch_hotkey(self) -> None:
        """窗口在前台时，轮询 P 键切换穿透。

        为什么不用 Flet 的键盘事件：桌面端只有 Flutter 里的输入控件拿到焦点时才会派发
        键盘事件，本程序点空白处不产生焦点，按键永远收不到。GetAsyncKeyState 是全局状态，
        再用 GetForegroundWindow 限定「只有本窗口在前台才响应」，等价于规则里的
        「窗口处于焦点状态时按 P」。
        """
        was_down = False
        while True:
            await asyncio.sleep(0.05)
            try:
                if not self._hwnd or _foreground_window() != self._hwnd:
                    was_down = False
                    continue
                down = _key_down(0x50)          # 'P'
            except Exception:                   # noqa: BLE001
                continue
            if down and not was_down:
                await self.toggle_click_through()
            was_down = down

    async def _watch_band(self) -> None:
        """穿透模式下，光标进入顶部 3px 时临时关闭穿透，让拖动条能收到鼠标。

        穿透是整窗生效的，没有「半透明命中」这种东西，所以只能靠轮询光标位置 +
        临时切换样式，等价于「只有顶部 3px 不穿透」。锁定状态下完全不切换，
        于是整窗连拖动条都点不到 —— 只剩 P 键能退出。
        """
        while True:
            await asyncio.sleep(BAND_POLL_MS / 1000.0)
            if not self.click_through or self.locked:
                continue

            rect = win_effects.window_rect(APP_TITLE)
            if not rect:
                continue

            left, top = rect[0], rect[1]
            width = rect[2]
            band = BAND_H * self._dpi_scale
            cx, cy = _cursor_pos()
            hot = (left <= cx < left + width) and (top <= cy < top + band)

            if hot == self._band_hot:
                continue

            hwnd = win_effects.find_window(APP_TITLE, timeout=0.3)
            if not hwnd:
                continue
            win_effects.set_click_through(hwnd, not hot)
            self._band_hot = hot

    # ------------------------------------------------------------ 闲置收起 --
    def _touch(self) -> None:
        """记录一次用户操作，重置闲置计时。"""
        self.last_active = time.monotonic()

    def _on_hover(self, e=None) -> None:
        # 鼠标进入窗口也算一次操作
        self._touch()

    async def _idle_watch(self) -> None:
        """后台盯着闲置时间，超过阈值就收起到屏幕边缘。"""
        while True:
            await asyncio.sleep(IDLE_POLL)
            if self.collapsed:
                continue
            if time.monotonic() - self.last_active >= IDLE_SECONDS:
                await self.collapse()

    async def collapse(self) -> None:
        """缩到**离它最近的那条屏幕边缘**，留一条圆角小黑条。

        规则和 macOS 的自动隐藏一样：窗口在左半边就贴左边，在右半边就贴右边，
        纵向位置不动（比如窗口在 (3,5)，收起后仍在 y=5 这条线上）。

        Flutter 的窗口有最小宽度限制（约 135 逻辑像素），没法真的把窗口缩到
        一条缝，所以保持窗口宽度不变，把整扇窗推到屏幕外，只露出 STRIP_VISIBLE 像素。
        """
        if self.collapsed:
            return
        self.collapsed = True

        win = self.page.window
        # 优先用 Win32 读到的真实位置；Flet 的 window.left/top 在没设过时是 None
        rect = win_effects.window_rect(APP_TITLE)
        if rect:
            self._saved_geom = rect
        else:
            self._saved_geom = (win.left or 0, win.top or 0, WINDOW_W, WINDOW_H)

        left, top, width, _ = self._saved_geom
        screen_w, screen_h = _screen_size()

        # 窗口中心在屏幕左半还是右半，决定贴哪边
        center_x = left + width / 2
        self._strip_side = "left" if center_x < screen_w / 2 else "right"

        strip_top = max(0, min(top, screen_h - STRIP_H))
        target_left = (
            -(width - STRIP_VISIBLE) if self._strip_side == "left"
            else screen_w - STRIP_VISIBLE
        )
        self._strip_top = strip_top
        self._strip_left = target_left

        # 先把面板淡出：滑出去的过程中不会看到内容被生硬裁切
        self.root.animate_opacity = ft.Animation(ANIM_FADE_MS, ft.AnimationCurve.EASE_OUT)
        self.root.opacity = 0.0
        self.page.update()

        # 只做横向滑动。Flet 改窗口高度时会以垂直中心为基准，边滑边压扁会把
        # 窗口纵向位置拽走，所以高度留到最后（那时只剩一条缝，看不出来）再切。
        await self._animate_left(start=left, end=target_left, top=strip_top)

        win.height = STRIP_H
        win.top = strip_top
        win.left = target_left
        self.page.update()

        c = self._palette()
        # 换成纯色条，再把不透明度淡回来
        self.root.content = ft.Container(bgcolor="transparent")
        self.root.bgcolor = c["strip"]
        self.root.border = ft.border.all(1, "#33FFFFFF")
        self.root.border_radius = 6
        self.root.on_click = self.expand
        self.root.opacity = 1.0
        self.page.update()

        # 换内容会触发一次窗口状态回传，位置可能被刷回默认值，这里再钉一次
        await asyncio.sleep(0.25)
        self._pin_strip_geometry()

    def _pin_strip_geometry(self) -> None:
        """把收起态的三个几何值重新写一遍，防止被后续 update 覆盖。"""
        win = self.page.window
        win.height = STRIP_H
        win.top = self._strip_top
        win.left = self._strip_left
        self.page.update()

    async def _animate_left(
        self,
        start: float,
        end: float,
        top: int | None = None,
        duration_ms: int = ANIM_SLIDE_MS,
        steps: int = ANIM_STEPS,
    ) -> None:
        """只缓动窗口的横向位置，ease-out 曲线，收尾柔和。

        `top` 必须每帧一起设：Flet 单独改 left 时会把窗口纵向位置重置成默认值，
        表现就是滑动过程中窗口突然跳到屏幕顶部。
        """
        win = self.page.window
        delay = duration_ms / 1000.0 / steps
        for i in range(1, steps + 1):
            win.left = round(start + (end - start) * ease_out_cubic(i / steps))
            if top is not None:
                win.top = top
            self.page.update()
            await asyncio.sleep(delay)

    async def expand(self, e=None) -> None:
        """点小黑条展开回完整窗口，同样走缓动动画。"""
        if not self.collapsed:
            return
        self._touch()
        self.collapsed = False

        win = self.page.window
        left, top = (self._saved_geom[0], self._saved_geom[1]) if self._saved_geom else (0, 0)
        cur = win_effects.window_rect(APP_TITLE)
        start_left = cur[0] if cur else (win.left if win.left is not None else left)

        # 先恢复高度和纵向位置：此刻窗口还贴在屏幕外沿，跳变看不见
        win.height = WINDOW_H
        win.top = top
        win.left = start_left
        self.page.update()

        # 换回完整界面，先透明，边滑进来边淡入
        self.root.content = self._expanded_body
        self.root.on_click = None
        self.root.border_radius = 14
        self.root.animate_opacity = ft.Animation(ANIM_FADE_MS, ft.AnimationCurve.EASE_OUT)
        self.root.opacity = 0.0
        self._apply_theme()

        await self._animate_left(start=start_left, end=left)

        self.root.opacity = 1.0
        self._render()

    # -------------------------------------------------------------- actions --
    async def toggle_theme(self, e=None) -> None:
        self._touch()
        self.dark = not self.dark
        self._apply_theme()

    async def toggle_pin(self, e=None) -> None:
        self._touch()
        self.pinned = not self.pinned
        self.page.window.always_on_top = self.pinned
        c = self._palette()
        self.pin_btn.icon = (
            ft.Icons.PUSH_PIN if self.pinned else ft.Icons.PUSH_PIN_OUTLINED
        )
        self.pin_btn.icon_color = c["accent"] if self.pinned else c["sub"]
        self.pin_btn.tooltip = "取消置顶" if self.pinned else "保持置顶"
        self.page.update()

    async def close_app(self, e=None) -> None:
        await _maybe_await(self.page.window.close())

    async def step_change(self, e=None) -> None:
        self._touch()
        if self.state.running:
            return
        attr, delta = e.control.data
        lo, hi = (FOCUS_MIN, FOCUS_MAX) if attr == "focus" else (BREAK_MIN, BREAK_MAX)
        current = getattr(self.settings, attr)
        new_value = clamp(current + delta, lo, hi)
        if new_value == current:
            return
        setattr(self.settings, attr, new_value)
        getattr(self, f"_num_{attr}").value = str(new_value)
        self.reset_timer()

    async def toggle_timer(self, e=None) -> None:
        self._touch()
        if self.state.running:
            self._pause()
        else:
            self._start()

    def _start(self) -> None:
        if self.state.remaining <= 0:
            total = phase_seconds(self.state.phase, self.settings)
            self.state.total = total
            self.state.remaining = total
        self.state.running = True
        self.state.last_tick = time.monotonic()
        self.start_btn.text = "暂停"
        self.start_btn.icon = ft.Icons.PAUSE_ROUNDED
        self._lock_settings(True)
        self._task = self.page.run_task(self._tick)
        self._render()

    def _pause(self) -> None:
        self.state.running = False
        self._task = None
        self.start_btn.text = "开始"
        self.start_btn.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self._lock_settings(False)
        self._render()

    def _lock_settings(self, locked: bool) -> None:
        for attr in ("focus", "break_"):
            getattr(self, f"_minus_{attr}").disabled = locked
            getattr(self, f"_plus_{attr}").disabled = locked

    def reset_timer(self, e=None) -> None:
        self._touch()
        self.state.running = False
        self._task = None
        self.state.total = phase_seconds(self.state.phase, self.settings)
        self.state.remaining = self.state.total
        self.start_btn.text = "开始"
        self.start_btn.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self._lock_settings(False)
        self._render()

    # ----------------------------------------------------------------- tick --
    async def _tick(self) -> None:
        while self.state.running:
            await asyncio.sleep(TICK)
            now = time.monotonic()
            self.state.remaining -= now - self.state.last_tick
            self.state.last_tick = now

            if self.state.remaining <= 0:
                self.state.remaining = 0
                self.state.running = False
                self._task = None
                self._render()
                self._on_finished()
                return

            self._render_time_only()

    def _on_finished(self) -> None:
        finished = self.state.phase
        if finished == "focus":
            self.state.done_count += 1
            beep("focus_end")
        else:
            beep("break_end")

        self.state.phase = other_phase(finished)
        self.state.total = phase_seconds(self.state.phase, self.settings)
        self.state.remaining = self.state.total
        self.start_btn.text = "开始"
        self.start_btn.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self._lock_settings(False)
        self._render()

        if finished == "focus":
            self.page.run_task(self._bring_to_front)

    async def _bring_to_front(self) -> None:
        await _maybe_await(self.page.window.to_front())

    # --------------------------------------------------------------- render --
    def _render_time_only(self) -> None:
        self.time_text.value = mmss(self.state.remaining)
        self.progress.value = progress_of(self.state.remaining, self.state.total)
        self.page.window.progress_bar = self.progress.value
        self.page.update()

    def _render(self) -> None:
        if self.collapsed:
            return
        c = self._palette()
        is_focus = self.state.phase == "focus"
        accent = c["accent"] if is_focus else COLOR_BREAK

        self.phase_text.value = "专注" if is_focus else "休息"
        self.phase_text.color = accent
        self.time_text.value = mmss(self.state.remaining)
        self.progress.value = progress_of(self.state.remaining, self.state.total)
        self.progress.color = accent
        self.stat_text.value = f"本次完成 {self.state.done_count} 个番茄"

        self.page.window.progress_bar = (
            self.progress.value if self.state.running else None
        )
        self.page.update()


def main(page: ft.Page) -> None:
    PomodoroApp(page)


if __name__ == "__main__":
    ft.app(main)

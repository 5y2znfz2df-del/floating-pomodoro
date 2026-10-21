# flet_win_effects

给 Flet 的 Windows 窗口加**亚克力模糊 + 无边框 + 圆角**，纯 ctypes，无第三方依赖。

```python
import flet_win_effects
...
await asyncio.sleep(1.2)                                   # 等窗口创建出来
info = flet_win_effects.apply_glass("你的窗口标题")          # 一行挂上特效
```

---

## 三行接入

```python
# 1) 页面和窗口都设成透明，否则桌面透不出来
page.bgcolor = ft.Colors.TRANSPARENT
page.window.frameless = True

# 2) 窗口出现之后（通常 1 秒左右）再调，太早拿不到句柄
await asyncio.sleep(1.2)
flet_win_effects.apply_glass("你的窗口标题", tint=(18, 18, 20), alpha=132)
```

然后在页面上放一个**半透明容器**当作玻璃本体：

```python
ft.Container(
    expand=True,
    bgcolor="#9E1C1C1E",                       # 8 位色 = AARRGGBB
    border=ft.border.all(1, "#30FFFFFF"),      # 1px 高光描边
    border_radius=14,
)
```

`apply_glass()` 返回结果字典，建议打进启动日志：

```python
print(f"glass = {info}")
# glass = {'hwnd': 123456, 'frameless': True, 'acrylic': True, 'rounded': True}
```

可直接运行的完整示例：`examples/minimal.py`。

---

## 支持的 Windows 版本

| 功能 | 最低要求 | 本库实测 |
| --- | --- | --- |
| 亚克力模糊 | Windows 10 1803+ | Windows 11（10.0.28000）✅ |
| 无边框（摘 `WS_CAPTION`） | Windows 7+ | Windows 11 ✅ |
| 窗口圆角 | Windows 11 | Windows 11 ✅ |
| Mica / Acrylic backdrop | Windows 11 22H2+ | 未实测（且不推荐，见下） |

**不支持的项目**（一律静默失败，程序照常运行）：

- macOS / Linux：`IS_WINDOWS` 为 `False`，所有函数直接返回 `False` / `None`
- Windows 7 / 8：无边框能用，亚克力和圆角不行，窗口退回不透明

---

## 已知限制

**远程桌面 / 虚拟机会话**
RDP 连接下 `SetWindowCompositionAttribute` 通常返回成功但**看不到模糊效果**，
或者直接失败。这是 Windows 合成器的限制，不是代码问题。

**全屏独占游戏**
Windows 的全屏独占模式（exclusive fullscreen）会抢走置顶层，`always_on_top` 也会失效。
让游戏跑「无边框窗口」模式即可。

**老系统回退**
亚克力在 Windows 10 1803 以下不存在。此时窗口会保持不透明，但**不会崩、不会白屏**——
所有函数都是 `try/except → return False`。

**不要和 `set_backdrop()` 一起用**
给无边框窗口设置 `DWMWA_SYSTEMBACKDROP_TYPE` 时，Windows 会顺手把原生标题栏画回来，
和去边框冲突。想要玻璃质感请用 `enable_acrylic()`。

**标题必须完全一致**
`find_window()` 是精确匹配（区分大小写）。如果你在运行时改了 `page.title`，
记得用新标题重新调一次。

**改了窗口尺寸要重设圆角**
`enable_rounded_corners()` 是一次性的。程序里如果动态改了窗口大小，圆角不会跟着变，
需要再调一次（或者干脆只用容器的 `border_radius`）。

---

## 点击穿透（悬浮挂件必备）

```python
hwnd = flet_win_effects.find_window("My App")
flet_win_effects.set_click_through(hwnd, True)    # 鼠标完全穿过窗口
flet_win_effects.is_click_through(hwnd)           # -> True
```

穿透是**整窗**生效的，没有「部分穿透」。常见做法是留一条窄边当拖动条，
靠轮询光标位置临时让出鼠标：

```python
# 光标进入顶部 3px → 关闭穿透（这一条能收到鼠标）；离开 → 重新打开
rect = flet_win_effects.window_rect("My App")
inside_band = rect[1] <= cursor_y < rect[1] + 3
flet_win_effects.set_click_through(hwnd, not inside_band)
```

一定要留一个**逃生方式**，否则用户把自己锁死：窗口有焦点时按 `P` 切换，
或提供一个只在非穿透状态可见的按钮（穿透后点不到任何东西）。

---

## API

| 函数 | 作用 | 失败时返回 |
| --- | --- | --- |
| `apply_glass(title, tint, alpha)` | 一站式：无边框 + 亚克力 + 圆角 | `{"hwnd": None, ...}` |
| `find_window(title, timeout=6.0)` | 按标题找 HWND，带重试 | `None` |
| `window_rect(title)` | 取 `(left, top, width, height)` | `None` |
| `make_frameless(hwnd)` | 摘掉标题栏 / 调整边框 | `False` |
| `enable_acrylic(hwnd, tint, alpha)` | 挂亚克力 | `False` |
| `disable_acrylic(hwnd)` | 取消毛玻璃 | `False` |
| `enable_acrylic_state(hwnd, state)` | 直接设 AccentState | `False` |
| `enable_rounded_corners(hwnd)` | 窗口圆角（Win11） | `False` |
| `set_backdrop(hwnd, kind=3)` | DWM backdrop（不推荐） | `False` |
| `set_click_through(hwnd, True)` | 整窗鼠标穿透 | `False` |
| `is_click_through(hwnd)` | 查询是否穿透 | `False` |
| `disable_ime(hwnd)` | 解除输入法关联（纯展示窗口） | `False` |

坐标说明：`window_rect()` 返回的是**逻辑像素**，和 Flet 的 `page.window.left/top`
是同一个坐标系，可以直接互相赋值。

---

MIT License · 组件源码见 [`__init__.py`](__init__.py)

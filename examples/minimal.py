"""最小示例：透明背景 + 亚克力模糊 + 无边框 + 圆角。

    python examples/minimal.py

跑起来应该看到一个深色半透明小窗，能透出并模糊背后的桌面。
"""

import asyncio
import sys
from pathlib import Path

import flet as ft

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 免安装，直接从仓库跑
import flet_win_effects as fx  # noqa: E402

TITLE = "flet-win-effects · minimal"


async def main(page: ft.Page):
    page.title = TITLE
    page.padding = 0
    page.bgcolor = ft.Colors.TRANSPARENT           # 让窗口空白处透出桌面
    page.window.width, page.window.height = 320, 200
    page.window.frameless = True                   # 先让 Flet 去掉标题栏

    page.add(ft.Container(
        expand=True,
        bgcolor="#9E1C1C1E",                       # AARRGGBB：半透明面板 = 玻璃本体
        border=ft.border.all(1, "#30FFFFFF"),      # 1px 高光描边
        border_radius=14,
        alignment=ft.alignment.center,
        content=ft.Text("Acrylic + frameless", color="#F5F5F7", size=15),
    ))

    await asyncio.sleep(1.2)                       # 等窗口创建出来，太早拿不到句柄
    print(f"glass = {fx.apply_glass(TITLE, tint=(18, 18, 20), alpha=132)}", flush=True)


ft.app(main)

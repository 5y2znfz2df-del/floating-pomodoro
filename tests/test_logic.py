"""番茄钟纯逻辑单元测试。

    python tests/test_logic.py

只测不依赖界面的部分（时间格式化、区间夹取、阶段切换、进度计算），
所以不需要图形环境，CI 里也能跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台默认 GBK，打印 ✅ 会炸，强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from app import Settings, clamp, mmss, other_phase, phase_seconds, progress_of  # noqa: E402

FAILED: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ok   {name}: {got}")
    else:
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
        FAILED.append(name)


def main() -> int:
    print("mmss:")
    check("0 秒", mmss(0), "00:00")
    check("59 秒", mmss(59), "00:59")
    check("60 秒", mmss(60), "01:00")
    check("25 分钟", mmss(1500), "25:00")
    check("99 分钟", mmss(99 * 60 + 30), "99:30")
    check("负数按 0 处理", mmss(-5), "00:00")
    check("小数四舍五入", mmss(9.6), "00:10")

    print("clamp:")
    check("区间内", clamp(25, 1, 120), 25)
    check("低于下限", clamp(0, 1, 120), 1)
    check("高于上限", clamp(999, 1, 120), 120)

    print("other_phase:")
    check("专注 -> 休息", other_phase("focus"), "break")
    check("休息 -> 专注", other_phase("break"), "focus")

    print("phase_seconds:")
    check("默认专注", phase_seconds("focus", Settings()), 1500.0)
    check("默认休息", phase_seconds("break", Settings()), 300.0)
    check("自定义专注", phase_seconds("focus", Settings(focus=40, break_=8)), 2400.0)
    check("自定义休息", phase_seconds("break", Settings(focus=40, break_=8)), 480.0)

    print("progress_of:")
    check("刚开始", progress_of(1500, 1500), 0.0)
    check("过半", progress_of(750, 1500), 0.5)
    check("结束", progress_of(0, 1500), 1.0)
    check("总数为 0 不炸", progress_of(0, 0), 0.0)
    check("越界被夹住", progress_of(-10, 1500), 1.0)

    print()
    if FAILED:
        print(f"{len(FAILED)} 项失败: {', '.join(FAILED)}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

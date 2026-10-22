"""把 dist\\Pomodoro 打成 Release 用的绿色版 zip。

为什么不用 Compress-Archive / .NET 的 CreateFromDirectory：
这两个在 Windows PowerShell 5.1 / .NET Framework 下会把路径分隔符写成反斜杠
（``Pomodoro\\Pomodoro.exe``），不符合 ZIP 规范（必须用 ``/``），
winget 之类的工具解析会出问题。Python 的 zipfile 始终写 ``/``。

用法：
    python tools/make_release_zip.py                 # 默认 1.0.2
    python tools/make_release_zip.py 1.0.3
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dist" / "Pomodoro"


def build(version: str) -> Path:
    if not (SRC / "Pomodoro.exe").exists():
        raise SystemExit(f"找不到 {SRC / 'Pomodoro.exe'}，先跑 flet pack")

    out = ROOT / "dist" / f"Pomodoro-{version}-win-x64.zip"
    if out.exists():
        out.unlink()

    base = SRC.parent
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for dirpath, _dirnames, filenames in os.walk(SRC):
            for name in filenames:
                full = Path(dirpath) / name
                # 关键：把 \\ 换成 /，保证跨平台可解压
                arc = full.relative_to(base).as_posix()
                zf.write(full, arc)
                count += 1

    return out, count


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.0.2"
    out, count = build(version)

    size_mb = out.stat().st_size / (1024 * 1024)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()

    print(f"输出   : {out}")
    print(f"条目   : {count}")
    print(f"大小   : {size_mb:.1f} MB")
    print(f"SHA256 : {digest}")

    # 顺手写一份校验文件，Release 一起传
    checksum = out.with_suffix(out.suffix + ".sha256")
    checksum.write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    print(f"校验   : {checksum}")


if __name__ == "__main__":
    main()

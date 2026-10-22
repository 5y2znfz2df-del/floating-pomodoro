"""把 Release 产物传到 VirusTotal，拿分析链接。

用法（key 只从环境变量读，不写进仓库）：
    $env:VT_API_KEY = "…"
    python tools/vt_scan.py dist\\Pomodoro-Setup.exe dist\\Pomodoro-1.0.2-win-x64.zip

脚本做的事：
1. 大于 32 MB 的文件先向 /files/upload_url 要一个专用上传地址
2. multipart 上传，拿到 analysis id
3. 轮询 /analyses/{id} 直到完成
4. 打印 https://www.virustotal.com/gui/file/{sha256} —— 这个链接可以贴到 Release

依赖：只用标准库（urllib）。这台机器的 TLS 证书链有问题，所以显式跳过校验。
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import sys
import time
import urllib.request
import uuid
from pathlib import Path

API = "https://www.virustotal.com/api/v3"
CTX = ssl._create_unverified_context()
LARGE_FILE = 32 * 1024 * 1024


def _call(url: str, data: bytes | None = None, headers: dict | None = None,
          method: str | None = None) -> dict:
    key = os.environ.get("VT_API_KEY")
    if not key:
        raise SystemExit("没有设置 VT_API_KEY 环境变量")

    all_headers = {"x-apikey": key}
    if headers:
        all_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upload(path: Path) -> dict:
    size = path.stat().st_size
    url = _call(f"{API}/files/upload_url")["data"] if size > LARGE_FILE else f"{API}/files"

    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)

    return _call(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )


def wait_analysis(analysis_id: str, timeout: float = 900) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = _call(f"{API}/analyses/{analysis_id}")
        status = info["data"]["attributes"]["status"]
        if status == "completed":
            return info
        time.sleep(15)
    raise TimeoutError(f"分析超时: {analysis_id}")


def main() -> None:
    files = sys.argv[1:]
    if not files:
        raise SystemExit("用法: python tools/vt_scan.py <文件> [文件…]")

    for name in files:
        path = Path(name)
        if not path.exists():
            print(f"[跳过] 不存在: {path}")
            continue

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"\n=== {path.name} ({path.stat().st_size / 1048576:.1f} MB) ===")
        print(f"sha256 : {digest}")

        try:
            result = upload(path)
            analysis_id = result["data"]["id"]
            print(f"已提交 : {analysis_id}")

            info = wait_analysis(analysis_id)
            stats = info["data"]["attributes"].get("stats", {})
            print(f"结果   : {stats}")

            link = f"https://www.virustotal.com/gui/file/{digest}"
            print(f"报告   : {link}")
        except Exception as exc:  # noqa: BLE001
            print(f"失败   : {type(exc).__name__}: {exc}")
            # 即使分析没跑完，文件页链接对已收录的哈希依然有效
            print(f"文件页 : https://www.virustotal.com/gui/file/{digest}")


if __name__ == "__main__":
    main()

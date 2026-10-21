"""Smoke test: build the same control tree the desktop app builds, but render it
over HTTP so the result can be verified without a visible desktop session.

    python tools/smoke_test.py        # serves on http://127.0.0.1:8550
    curl http://127.0.0.1:8550        # should return the page shell
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

import app  # noqa: E402

if __name__ == "__main__":
    ft.run(app.main, view=ft.AppView.WEB_BROWSER, port=8550)
